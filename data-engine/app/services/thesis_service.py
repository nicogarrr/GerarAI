"""Thesis generation with evidence fingerprinting and honest insufficient-data handling."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.models import (
    Claim,
    ClaimEvidence,
    Company,
    Document,
    FinancialFact,
    FundamentalModelVersion,
    MarketPrice,
    SourceAudit,
    ThesisVersion,
)
from app.services.claim_scope import supersede_claims_of
from app.services.company_resolver import resolve_company
from app.services.inferred_input_service import validate as validate_inferred
from app.services.long_term_model_service import LongTermModelService
from app.services.memo_text_es import date_es, money_thesis, number_es, percent_es, term_es
from app.services.number_format import format_compact_es
from app.services.source_auditor import SourceAuditor
from app.services.source_hierarchy_service import classify_source
from app.services.text_clip import clip_words
from app.services.thesis_context import retrieve_thesis_context
from app.services.thesis_narrative_llm import evidence_sections
from app.services.thesis_news_narrative import prepare_news_narrative, sin_datos
from app.services.thesis_provenance import (
    build_inputs_provenance,
    classify_origin,
    inputs_provenance_from_snapshot,
)
from app.services.valuation_service import ValuationService
from app.valuation.engines.base import MODEL_VERSION, margin_of_safety_reference
from app.valuation.financial_snapshot import FinancialSnapshotBuilder
from app.valuation.moat_framework import empty_moat_framework

_HORA_ES = {
    "time-pre-market": "antes de la apertura",
    "time-after-hours": "tras el cierre",
    "time-not-supplied": "hora no indicada",
    "before-market": "antes de la apertura",
    "after-market": "tras el cierre",
}


def _hora_es(value: object) -> str:
    return _HORA_ES.get(str(value), str(value))


logger = logging.getLogger(__name__)

PROMPT_VERSION = "thesis-render-v5-number-formats"


def latest_missing_inputs(db: Session, company_id: int) -> list[str] | None:
    """Inputs pendientes del modelo fundamental persistido mas reciente.

    Lee el snapshot completo que LongTermModelService persiste en
    FundamentalModelVersion.model_snapshot (missing_core + drivers
    obligatorios + blockers), sin tocar el esquema. None si la empresa
    no tiene modelo fundamental persistido: la UI distingue "sin
    pendientes conocidos" (lista vacia) de "sin informacion" (None).
    """
    model = db.scalar(
        select(FundamentalModelVersion)
        .where(FundamentalModelVersion.company_id == company_id)
        .order_by(desc(FundamentalModelVersion.version))
        .limit(1)
    )
    if model is None:
        return None
    snapshot = model.model_snapshot or {}
    return sorted(
        set(
            (snapshot.get("missing_inputs") or [])
            + (snapshot.get("missing_mandatory_drivers") or [])
        )
    )


def resolve_fact_sources(
    db: Session, company_id: int, fact_ids: list[int]
) -> dict[int, dict]:
    """fact_id -> fuente documental (url/fecha/titulo/tipo) resuelta desde
    FinancialFact.source_id -> Document. Nunca se toma de lo declarado."""
    sources: dict[int, dict] = {}
    if not fact_ids:
        return sources
    rows = db.execute(
        select(FinancialFact, Document)
        .join(Document, Document.id == FinancialFact.source_id)
        .where(
            FinancialFact.id.in_(fact_ids),
            FinancialFact.company_id == company_id,
        )
    ).all()
    for fact, doc in rows:
        sources[fact.id] = {
            "metric": fact.metric,
            "fact_value": fact.value,
            "unit": fact.unit,
            "period": fact.period,
            "is_reported": fact.is_reported,
            "url": doc.source_url,
            "date": doc.published_at.date().isoformat() if doc.published_at else None,
            "title": doc.title,
            "source_type": doc.source_type,
        }
    return sources


def latest_inputs_provenance(
    db: Session, company_id: int, valuation_basis: dict | None = None
) -> list[dict] | None:
    """Inputs etiquetados (dato/derivado/estimacion_llm/supuesto) del modelo
    fundamental persistido mas reciente. None si no hay modelo persistido."""
    model = db.scalar(
        select(FundamentalModelVersion)
        .where(FundamentalModelVersion.company_id == company_id)
        .order_by(desc(FundamentalModelVersion.version))
        .limit(1)
    )
    used_inputs = (valuation_basis or {}).get("inferred_inputs_used") or []
    if model is None and not used_inputs:
        return None
    items = inputs_provenance_from_snapshot(model.model_snapshot if model else {})
    fact_ids = sorted({fid for it in items for fid in (it.get("source_fact_ids") or [])})
    sources = resolve_fact_sources(db, company_id, fact_ids)
    classified = classify_origin(items, sources)
    # Politica del producto: sin base documentada no hay etiqueta INFERIDO "disfrazada";
    # el input se omite (la seccion de datos pendientes lo declara N/D).
    classified = [
        item
        for item in classified
        if not (item.get("origen") == "INFERIDO" and item.get("base_documentada") is False)
    ]
    # Inputs INFERIDO que la valoracion de ESTA tesis consumio (trace persistido
    # en valuation_basis). Se anaden aparte: no sustituyen la historia del modelo
    # (p. ej. la mediana fcf_margin), el usuario ve ambos.
    for used in (valuation_basis or {}).get("inferred_inputs_used") or []:
        key = used.get("input_key")
        value = used.get("value")
        base = used.get("base_inferencia")
        urls = list(used.get("urls_inferencia") or [])
        if validate_inferred(key, value, base, urls):
            continue
        classified.append(
            {
                "key": f"{key}_usado_en_valoracion",
                "label": "estimacion_llm",
                "value": value,
                "unit": "decimal",
                "method": base,
                "source_fact_ids": [],
                "confidence": None,
                "source_type": "inferred_input",
                "period": None,
                "origen": "INFERIDO",
                "fuentes": [],
                "base_inferencia": base,
                "urls_inferencia": urls,
                "base_documentada": True,
                "inferred_input_id": used.get("inferred_input_id"),
            }
        )
    return classified

# Etiquetas es-ES de las métricas que alimentan claims visibles. El fallback
# humaniza el código (guiones bajos a espacios) sin exponerlo tal cual.
_METRIC_LABELS_ES = {
    "revenue": "ingresos",
    "free_cash_flow": "flujo de caja libre",
    "net_debt": "deuda neta",
    "shares_diluted": "acciones diluidas",
    "fcf_margin": "margen de FCF",
    "revenue_growth": "crecimiento de ingresos",
    "operating_cash_flow": "flujo de caja operativo",
    "capital_expenditure": "gasto de capital (CapEx)",
    "cash_and_equivalents": "efectivo y equivalentes",
    "total_debt": "deuda total",
}


def _metric_claim_statement(ticker: str, metric: str, fact: FinancialFact) -> str:
    """Texto del claim de una métrica, en español y con la cifra formateada.

    Antes: "RKLB revenue is 200966000000.000000 for FY2025." (inglés y valor
    crudo de la columna Numeric(24, 6)). La unidad solo se muestra cuando es
    una divisa ISO (USD, EUR...); unidades como "shares" no aportan.
    """
    # El conjunto de métricas posibles es cerrado (DURATION_METRICS +
    # INSTANT_METRICS del snapshot) y esta tabla lo cubre entero. Si llega una
    # clave desconocida, se muestra como dato crudo entre comillas en vez de
    # "humanizarla" a una frase en inglés dentro del texto en español.
    label = _METRIC_LABELS_ES.get(metric) or f'dato "{metric}"'

    if metric in {"fcf_margin", "revenue_growth"} and fact.unit in {"decimal", "ratio"}:
        return f"{ticker}: {label} de {_thesis_percent(float(fact.value))} ({fact.period})."
    value = format_compact_es(fact.value) or str(fact.value)
    unit = fact.unit if fact.unit and len(fact.unit) == 3 and fact.unit.isupper() else None
    amount = f"{value} {unit}" if unit else value
    return f"{ticker}: {label} de {amount} ({fact.period})."

_CODE_ES = {
    "research_candidate": "candidata de investigación",
    "standard_dcf": "DCF estándar",
    "indicative_assumptions": "supuestos indicativos",
    "financial_facts": "datos financieros reportados",
    "traceable_wacc": "WACC trazable",
    "generic_fcf": "FCF genérico",
    "fact_anchored_sensitivity": "sensibilidad anclada a datos",
    "preview_only": "solo vista previa",
    "no_revenue_reported": "sin ingresos reportados",
    "revenue": "ingresos",
    "fcf_margin": "margen FCF",
    "shares_diluted": "acciones diluidas",
    "net_debt": "deuda neta",
    "market_price": "precio de mercado",
    "wacc": "WACC",
    "terminal_growth": "crecimiento terminal",
    "revenue_growth": "crecimiento de ingresos",
    "gross_margin": "margen bruto",
    "operating_margin": "margen operativo",
    "net_margin": "margen neto",
    "unassigned": "sin asignar",
}


def _code_es(code) -> str:
    """Código técnico -> texto en español; si no hay traducción, se muestra legible sin guiones bajos."""
    text = str(code if code is not None else "N/D")
    return _CODE_ES.get(text) or text.replace("_", " ")


def _thesis_money(value: float, currency: str | None) -> str:
    return money_thesis(value, currency)


def _thesis_percent(value: float) -> str:
    return percent_es(value)


def _pct_es(value: object) -> str:
    """Fracción (0,25) -> «25 %»; texto original si no es numérica."""
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return str(value)
    text = f"{number * 100:.1f}".rstrip("0").rstrip(".").replace(".", ",")
    return f"{text} %"


def _band_es(band: object) -> str:
    """Banda de margen [mín, base, máx] legible; N/D si falta."""
    if not isinstance(band, (list, tuple)) or not band:
        return "N/D"
    return " / ".join(_pct_es(v) for v in band)


class ThesisService:
    def __init__(self) -> None:
        self.valuation_service = ValuationService()
        self.auditor = SourceAuditor()

    def data_freshness(self, db: Session, company_id: int) -> datetime | None:
        """Marca temporal del dato mas reciente que alimenta una tesis.

        Mira hechos financieros, precios, noticias y documentos de la empresa;
        si alguno es posterior a thesis.created_at, la version esta obsoleta
        (stale) y conviene regenerar.
        """
        from app.models import Document, FinancialFact, MarketPrice, NewsEvent

        latest_seen: datetime | None = None
        # F317: los agregados MAX no heredan with_loader_criteria; las
        # fuentes tenant-owned se filtran explícitamente o una actualización
        # de otro tenant marcaría obsoleta esta tesis sin cambiar su
        # información. MarketPrice es global por diseño y sigue global.
        tenant_id = db.info.get("tenant_id")
        for model in (FinancialFact, MarketPrice, NewsEvent, Document):
            stmt = select(func.max(model.updated_at)).where(model.company_id == company_id)
            if tenant_id is not None and model is not MarketPrice:
                stmt = stmt.where(model.tenant_id == tenant_id)
            stamp = db.scalar(stmt)
            if stamp is not None and (latest_seen is None or stamp > latest_seen):
                latest_seen = stamp
        return latest_seen

    def latest(self, db: Session, ticker: str) -> ThesisVersion | None:
        company = resolve_company(db, ticker)
        if not company:
            return None
        return db.scalar(
            select(ThesisVersion)
            .where(ThesisVersion.company_id == company.id)
            .order_by(desc(ThesisVersion.version))
            .limit(1)
        )

    @staticmethod
    def _insufficient_signature(valuation: dict, material_fp: str) -> dict:
        """Firma estructurada de una valoracion insufficient_data.

        Motivo, motor, metodo, entradas faltantes y huella de la evidencia SIN el
        precio (documentos, hechos, noticias, modelo). Solo dos versiones con la
        misma firma completa son equivalentes.
        """
        trace = valuation.get("trace") or {}
        return {
            "reason": trace.get("reason"),
            "engine": trace.get("engine"),
            "method": trace.get("method"),
            "missing_inputs": sorted(str(x) for x in (valuation.get("missing_inputs") or [])),
            "material_fp": material_fp,
        }

    @staticmethod
    def _same_insufficient_signature(existing, signature: dict | None) -> bool:
        """True solo con evidencia previa explicita e identica; sin firma previa NO se deduplica."""
        if signature is None or existing.status != "insufficient_data":
            return False
        basis = existing.valuation_basis
        if not isinstance(basis, dict):
            return False
        previous = basis.get("insufficient_signature")
        return isinstance(previous, dict) and previous == signature

    def _input_fingerprint(
        self,
        db: Session,
        company: Company,
        valuation: dict,
        long_term_model: dict,
        news_items: list[dict] | None = None,
        include_price: bool = True,
    ) -> str:
        documents = list(
            db.execute(
                select(Document.id, Document.checksum, Document.updated_at)
                .where(Document.company_id == company.id)
                .order_by(Document.id)
            ).all()
        )
        facts = list(
            db.execute(
                select(
                    FinancialFact.id,
                    FinancialFact.metric,
                    FinancialFact.period,
                    FinancialFact.value,
                )
                .where(FinancialFact.company_id == company.id)
                .order_by(FinancialFact.id)
            ).all()
        )
        market_price = db.scalar(
            select(MarketPrice)
            .where(MarketPrice.company_id == company.id)
            .order_by(desc(MarketPrice.date))
            .limit(1)
        )
        payload = {
            "documents": [f"{d.id}:{d.checksum or d.updated_at.isoformat()}" for d in documents],
            "facts": [f"{f.id}:{f.metric}:{f.period}:{f.value}" for f in facts],
            "market_price": (
                (f"{market_price.date.isoformat()}:{market_price.close}" if market_price else None)
                if include_price
                else "excluded"
            ),
            "model_version": MODEL_VERSION,
            "prompt_version": PROMPT_VERSION,
            "valuation_status": valuation.get("status"),
            "engine": (valuation.get("trace") or {}).get("engine"),
            "input_source": (valuation.get("trace") or {}).get("input_source"),
            "fundamental_model_fingerprint": (
                long_term_model.get("persistence") or {}
            ).get("input_fingerprint"),
            "fundamental_model_status": long_term_model.get("status"),
            "missing_mandatory_drivers": long_term_model.get(
                "missing_mandatory_drivers"
            ),
            # Una noticia nueva (aunque no cambie ningun fact financiero) es
            # evidencia material: debe disparar una nueva version en generacion
            # normal. Se incluye la identidad y la procedencia COMPLETA de cada
            # noticia (id, titular integro, fecha con su procedencia, medio y
            # url): una correccion de atribucion tambien regenera la narrativa.
            "news": sorted(
                f"{item.get('id')}:{item.get('source_headline') or item.get('title') or ''}"
                f":{item.get('date') or ''}:{item.get('date_source') or ''}"
                f":{item.get('source') or ''}:{item.get('url') or ''}"
                for item in (news_items or [])
            ),
        }
        raw = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def generate(
        self,
        db: Session,
        ticker: str,
        force_new_version: bool = False,
        phase_callback=None,
        *,
        stored_evidence_only: bool = False,
        refresh_receipt: dict | None = None,
    ) -> ThesisVersion:
        """Persist model, valuation, thesis, evidence, graph and red team atomically.

        phase_callback(name) fires when generation ACTUALLY enters each real
        phase (async job progress; never synthetic progress).

        Todo el trabajo ocurre en un SAVEPOINT: un fallo revierte solo lo
        escrito por esta generación (nunca ``db.rollback()`` global, que
        descartaría trabajo ajeno pendiente en la sesión).
        """
        # La narrativa se prepara sin transacción de tesis ni sesión en red.
        narrative_sections = prepare_news_narrative(db, ticker)
        savepoint = db.begin_nested()
        try:
            thesis = self._generate_atomic(
                db, ticker, force_new_version, phase_callback, savepoint=savepoint,
                prepared_narrative=narrative_sections,
                stored_evidence_only=stored_evidence_only,
                refresh_receipt=refresh_receipt,
            )
        except Exception as exc:
            # Guard the savepoint: the phase callback and _generate_atomic both
            # commit, which closes the nested transaction. A blind
            # savepoint.rollback() then raised ResourceClosedError and MASKED the
            # real failure, so the job reported "ResourceClosedError" and could
            # not classify it as retryable. The writes already committed by
            # those callbacks stay either way, so surfacing the cause is what
            # makes the failure diagnosable.
            try:
                if savepoint.is_active:
                    savepoint.rollback()
            except Exception:  # noqa: BLE001 - never mask the original error
                logger.warning(
                    "No se pudo revertir el savepoint de la generación de tesis: %s",
                    type(exc).__name__,
                )
            raise
        return thesis

    def _generate_atomic(
        self,
        db: Session,
        ticker: str,
        force_new_version: bool = False,
        phase_callback=None,
        savepoint=None,
        prepared_narrative=None,
        stored_evidence_only=False,
        refresh_receipt=None,
    ) -> ThesisVersion:
        def _phase(name: str) -> None:
            if phase_callback is not None:
                phase_callback(name)

        company = resolve_company(db, ticker)
        if not company:
            raise ValueError(f"Unknown ticker: {ticker}")

        # Auto-ingesta best-effort (ley: ninguna tesis insufficient_data si la
        # empresa tiene filings): SEC companyfacts + Finnhub quote/profile +
        # filings/news/earnings/IR/tesis. Nunca rompe la generacion.
        _phase("collect_evidence")
        from app.services.tracked_evidence import tracked_evidence

        evidence: dict = tracked_evidence(refresh_receipt) if stored_evidence_only else {}
        try:
            from app.services.thesis_evidence_service import ThesisEvidenceService

            if not stored_evidence_only:
                evidence = ThesisEvidenceService().collect(db, company) or {}
        except Exception:
            evidence = {}

        _phase("build_fundamental_model")
        long_term_model = LongTermModelService().build(
            db, company, horizon=5, commit=False
        )
        _phase("run_valuation")
        valuation = self.valuation_service.value_company(db, company)
        missing_drivers = long_term_model.get("missing_mandatory_drivers") or []
        if missing_drivers:
            valuation["publishable"] = False
            valuation["missing_inputs"] = sorted(
                set((valuation.get("missing_inputs") or []) + missing_drivers)
            )
        valuation.setdefault("trace", {})["fundamental_model"] = {
            "model_version_id": (long_term_model.get("persistence") or {}).get(
                "model_version_id"
            ),
            "version": (long_term_model.get("persistence") or {}).get("version"),
            "framework": (long_term_model.get("framework") or {}).get("key"),
            "status": long_term_model.get("status"),
            "publishable": long_term_model.get("publishable"),
            "missing_mandatory_drivers": missing_drivers,
        }
        valuation["long_term_model"] = long_term_model
        news_items = ((evidence.get("sources") or {}).get("news") or {}).get("items") or []
        # Una tesis insufficient_data no usa el precio (no hay valoracion): el
        # precio no puede distinguir versiones, asi que queda fuera de la huella.
        fingerprint = self._input_fingerprint(
            db,
            company,
            valuation,
            long_term_model,
            news_items,
            include_price=valuation.get("status") != "insufficient_data",
        )

        existing = self.latest(db, ticker)
        if existing and not force_new_version:
            if valuation.get("status") == "insufficient_data":
                # QA-6: la decision depende de la firma estructurada completa
                # (motivo, motor, metodo, entradas faltantes, evidencia sin
                # precio). El atajo por fingerprint NO aplica aqui: no incluye
                # motivo/metodo/inputs y resucitaria una version vieja o sin firma.
                insufficient_signature = self._insufficient_signature(
                    valuation,
                    self._input_fingerprint(
                        db, company, valuation, long_term_model, news_items, include_price=False
                    ),
                )
                if self._same_insufficient_signature(existing, insufficient_signature):
                    if savepoint is not None:
                        savepoint.rollback()
                    existing.updated_at = datetime.now(UTC)
                    db.flush()
                    return existing
            elif getattr(existing, "input_fingerprint", None) == fingerprint:
                # Sin mutación previa: el fingerprint se calculó solo con
                # lecturas, así que se devuelve sin tocar la transacción
                # (el savepoint de generate() se libera solo).
                if savepoint is not None:
                    savepoint.rollback()
                return existing
            # Material evidence changed — fall through and create a new version.

        _phase("persist_valuation_snapshot")
        self.valuation_service.persist_output(db, company, valuation, commit=False)
        snapshot = FinancialSnapshotBuilder().build(db, company)
        facts = snapshot.facts

        _phase("source_audit")
        claims = self._build_claims(company, facts, valuation)
        audit = self.auditor.audit(
            claims=claims,
            calculation_trace=valuation.get("trace"),
            requires_sec_fmp_reconciliation=(valuation.get("trace") or {}).get("input_source")
            == "financial_facts",
        )

        previous = self.latest(db, ticker)
        version = (previous.version + 1) if previous else 1

        publishable = bool(valuation.get("publishable"))
        if valuation.get("status") == "insufficient_data":
            status = "insufficient_data"
        elif valuation.get("status") == "partial":
            # Rango indicativo con precio: parcial-publicable, nunca final.
            status = "draft_failed_audit" if not audit.passed else "draft"
        elif not audit.passed:
            status = "draft_failed_audit"
        elif publishable:
            status = "final"
        else:
            status = "draft"

        _phase("compose_thesis")
        hypothesis = self._hypothesis(company, valuation)
        catalysts = self._catalysts(evidence)
        invalidation = self._invalidation_criteria(company, valuation)
        scenario_probabilities = self._scenario_probabilities(long_term_model)

        summary = self._card_summary(company, valuation, hypothesis, news_items)
        # El resumen conserva los datos deterministas; el LLM redacta el
        # análisis de noticias debajo, sin otra llamada de selección de plantillas.
        # Narrativa libre INFERIDA desde noticias reales; fallo => "Sin datos".
        # Usa solo el modelo gratuito configurado, sin scheduler.
        filing_items = ((evidence.get("sources") or {}).get("filings") or {}).get("items") or []
        rag_context = retrieve_thesis_context(db, company)
        narrative_sections = prepared_narrative or sin_datos()
        thesis_markdown = self._render_markdown(
            company,
            valuation,
            audit.as_dict(),
            facts,
            long_term_model=long_term_model,
            version=version,
            evidence=evidence,
            hypothesis=hypothesis,
            catalysts=catalysts,
            invalidation_criteria=invalidation,
            scenario_probabilities=scenario_probabilities,
            fact_sources=resolve_fact_sources(
                db,
                company.id,
                sorted(
                    {
                        fid
                        for it in build_inputs_provenance(long_term_model)
                        for fid in (it.get("source_fact_ids") or [])
                    }
                ),
            ),
        )

        thesis_markdown += "\n\n## 23. Contexto y citas documentales\n"
        for section in evidence_sections(filing_items, rag_context).values():
            thesis_markdown += f"\n### {section['titulo']}\n"
            thesis_markdown += "\n\n".join(section["parrafos"]) + "\n"

        def _dec(value) -> Decimal | None:
            return None if value is None else Decimal(str(value))

        valuation_basis = self._valuation_basis(valuation)
        if valuation.get("status") == "insufficient_data":
            valuation_basis = {
                **(valuation_basis or {}),
                "insufficient_signature": self._insufficient_signature(
                    valuation,
                    self._input_fingerprint(
                        db, company, valuation, long_term_model, news_items, include_price=False
                    ),
                ),
            }

        _phase("persist_thesis")
        thesis = ThesisVersion(
            company_id=company.id,
            version=version,
            status=status,
            thesis_markdown=thesis_markdown,
            executive_summary=summary,
            rating=self._rating(
                valuation.get("margin_of_safety"),
                audit.passed,
                valuation.get("status"),
            ),
            current_price=_dec(valuation.get("current_price")),
            bear_value=_dec(valuation.get("bear_value")),
            base_value=_dec(valuation.get("base_value")),
            bull_value=_dec(valuation.get("bull_value")),
            expected_value=_dec(valuation.get("expected_value")),
            margin_of_safety=_dec(valuation.get("margin_of_safety")),
            data_confidence_score=self._confidence_score(valuation, facts),
            source_coverage_score=audit.source_coverage_score,
            red_team_score=0,
            valuation_risk_score=75 if "speculative" in (company.factor_tags or []) else 45,
            input_fingerprint=fingerprint,
            hypothesis=hypothesis,
            catalysts=catalysts,
            invalidation_criteria=invalidation,
            scenario_probabilities=scenario_probabilities,
            narrative_sections=narrative_sections,
            valuation_basis=valuation_basis,
        )
        db.add(thesis)
        db.flush()
        # Close the claims of the version this one replaces. Without this the
        # previous version's claims stay indistinguishable from the new ones:
        # every consumer that read claims by company_id saw both, so
        # red_team_score fell with each regeneration and the graph accumulated
        # nodes from superseded versions.
        if previous is not None and previous.id != thesis.id:
            # El efecto importa (marca los claims del modelo previo como
            # superados); el conteo no se usa todavia.
            supersede_claims_of(db, company.id, previous.id)
        self._persist_claims(db, company, thesis, claims)
        db.add(
            SourceAudit(
                thesis_version_id=thesis.id,
                passed=audit.passed and publishable,
                source_coverage_score=audit.source_coverage_score,
                unsupported_claims=audit.unsupported_claims,
                weak_claims=audit.weak_claims,
                data_conflicts=audit.data_conflicts,
                required_fixes=audit.required_fixes
                + (
                    [f"Faltan entradas de valoración (variables del modelo): {', '.join(valuation.get('missing_inputs') or [])}"]
                    if valuation.get("missing_inputs")
                    else []
                ),
            )
        )
        db.flush()
        from app.services.red_team_service import RedTeamService
        from app.services.thesis_graph_service import ThesisGraphService

        ThesisGraphService().build(db, company, thesis, commit=False)
        RedTeamService().run(db, company, thesis, commit=False)
        db.commit()
        db.refresh(thesis)
        # Human-in-the-loop mínimo viable: si TELEGRAM_APPROVAL_ENABLED, envía
        # el mensaje con botones inline. Best-effort: nunca rompe la generación.
        try:
            from app.services.thesis_approval_service import (
                maybe_request_thesis_approval,
            )

            if not stored_evidence_only:
                maybe_request_thesis_approval(db, thesis, company.ticker)
        except Exception:
            pass
        return thesis

    def _persist_claims(
        self,
        db: Session,
        company: Company,
        thesis: ThesisVersion,
        claims: list[dict],
    ) -> None:
        for payload in claims:
            if not payload.get("material", True):
                continue
            statement = str(payload.get("claim") or "").strip()
            if not statement:
                continue
            source_id = payload.get("source_id")
            source_type = str(payload.get("source_type") or "unknown")
            claim = Claim(
                company_id=company.id,
                thesis_version_id=thesis.id,
                statement=statement,
                claim_type=str(payload.get("predicate") or "generated_thesis"),
                status="supported" if source_id else "unverified",
                confidence=Decimal(str(payload.get("confidence", 0.5))),
                materiality_score=8,
                source_quality=classify_source(source_type).key,
                created_by="thesis_generation",
                metadata_={
                    "generated_claim_id": payload.get("claim_id"),
                    "verification_state": payload.get(
                        "verification_state", "unverified"
                    ),
                    "prompt_version": PROMPT_VERSION,
                },
            )
            db.add(claim)
            db.flush()
            if source_id:
                db.add(
                    ClaimEvidence(
                        claim_id=claim.id,
                        document_id=int(source_id),
                        evidence_type="supports",
                        summary=f"Generado desde la fuente {source_type}.",
                        confidence=claim.confidence,
                        source_tier=classify_source(source_type).key,
                        metadata_={"automatic": True, "generator": PROMPT_VERSION},
                    )
                )

    def _confidence_score(self, valuation: dict, facts: dict) -> int:
        if valuation.get("status") == "insufficient_data":
            return 15
        if not facts:
            return 25
        if valuation.get("publishable"):
            return 85
        return 55


    def _hypothesis(self, company: Company, valuation: dict) -> str:
        """Hipotesis comprobable derivada solo de datos del modelo (nunca inventada)."""
        price = valuation.get("current_price")
        base = valuation.get("base_value")
        mos = valuation.get("margin_of_safety")
        if price is None or base is None or mos is None:
            return (
                "Hipótesis en formación: faltan datos de mercado o de valoración "
                "para formular una hipótesis comprobable."
            )
        currency = valuation.get("currency") or company.currency
        price_text = _thesis_money(float(price), currency)
        base_text = _thesis_money(float(base), currency)
        if base <= 0:
            # Con un escenario base negativo o nulo el margen (base/precio - 1)
            # no es interpretable: -249% sobre una base de -84.70 se leia como
            # un dato real. Se dice tal cual, sin porcentaje.
            return (
                f"A {price_text}, el escenario base de {company.name} es {base_text} "
                f"(no positivo): el margen de seguridad no es interpretable."
            )
        reverse = valuation.get("reverse_dcf") or {}
        required_growth = reverse.get("required_revenue_growth")
        reverse_margin = reverse.get("fcf_margin")
        margin_txt = (
            f" con un margen FCF del {_thesis_percent(reverse_margin)}" if isinstance(reverse_margin, (int, float)) else ""
        )
        growth_txt = (
            f" El reverse DCF exige un crecimiento de ingresos del {_thesis_percent(required_growth)} anual{margin_txt}."
            if required_growth is not None
            else ""
        )
        # MoS = valor esperado/precio - 1 (valuation/engines/base.py): se nombra
        # explicitamente su base. Describirlo como distancia precio/base ("un X% por
        # encima del escenario base") usaria el denominador equivocado: con
        # precio 336.56 y base 106.85 diria "68% por encima" cuando el precio
        # esta un ~215% por encima.
        ref_label, ref_value = margin_of_safety_reference(valuation) or ("escenario base", base)
        ref_text = _thesis_money(float(ref_value), currency)
        # B6: la cifra es la salida real del modelo y se mantiene, pero cuando
        # la valoracion no es publicable (status "partial" o publishable False)
        # la frase viaja sola a memo, tarjeta y chat: sin la etiqueta aqui, un
        # -95 % construido sobre supuestos se leia como conclusion firme.
        indicative = valuation.get("status") == "partial" or valuation.get("publishable") is False
        prefix = "Valoración indicativa sobre supuestos: " if indicative else ""
        if mos >= 0:
            return (
                f"{prefix}A {price_text}, {company.name} cotiza con un margen de seguridad "
                f"del {_thesis_percent(mos)} respecto al {ref_label} ({ref_text}). Hipótesis: "
                f"los fundamentales modelados son alcanzables y el mercado corrige "
                f"ese descuento.{growth_txt}"
            )
        return (
            f"{prefix}A {price_text}, {company.name} cotiza con un margen de seguridad "
            f"del {_thesis_percent(mos)} respecto al {ref_label} ({ref_text}). Hipótesis: "
            f"el precio descuenta más de lo que los fundamentales modelados "
            f"soportan.{growth_txt}"
        )

    def _catalysts(self, evidence: dict) -> list[dict]:
        """Catalizadores con fecha conocida (hoy: calendario de resultados)."""
        sources = (evidence or {}).get("sources") or {}
        earnings = sources.get("earnings") or {}
        catalysts: list[dict] = []
        if earnings.get("status") == "ok" and earnings.get("next_date"):
            item: dict = {
                "label": "Próximos resultados",
                "date": earnings.get("next_date"),
                "source": "earnings_calendar",
            }
            if earnings.get("time"):
                item["time"] = earnings["time"]
            if earnings.get("eps_forecast") is not None:
                item["eps_forecast"] = earnings["eps_forecast"]
            catalysts.append(item)
        return catalysts

    def _invalidation_criteria(self, company: Company, valuation: dict) -> list[str]:
        """Condiciones observables que invalidarian la tesis, derivadas del modelo."""
        criteria: list[str] = []
        mos = valuation.get("margin_of_safety")
        base = valuation.get("base_value")
        if mos is not None and base is not None and mos >= 0:
            criteria.append(
                f"El precio supera de forma sostenida el valor base ({base:.2f}): "
                "el margen de seguridad desaparece."
            )
        reverse = valuation.get("reverse_dcf") or {}
        required_growth = reverse.get("required_revenue_growth")
        if required_growth is not None:
            criteria.append(
                f"Los ingresos reales se desvian de forma persistente del "
                f"{percent_es(required_growth)} anual que exige el reverse DCF."
            )
        moat = valuation.get("moat") or {}
        declining = [
            str(item.get("type"))
            for item in (moat.get("moats") or [])
            if item.get("trend") == "declining" and item.get("type")
        ]
        if declining:
            criteria.append(f"Deterioro confirmado del moat: {', '.join(declining)}.")
        if not criteria:
            criteria.append(
                "Tesis en formación: sin criterios automáticos hasta completar la valoración."
            )
        return criteria

    def _scenario_probabilities(self, long_term_model: dict) -> dict | None:
        """Probabilidades por escenario persistidas por el motor de modelado."""
        scenarios = (long_term_model or {}).get("scenarios") or {}
        probabilities = {
            name: scenario.get("probability")
            for name, scenario in scenarios.items()
            if isinstance(scenario, dict) and scenario.get("probability") is not None
        }
        return probabilities or None

    @staticmethod
    def _valuation_basis(valuation: dict) -> dict | None:
        """Base por accion de los escenarios tal como los dio el motor (F394).

        None si el motor no informo base: una tesis sin evidencia nunca se
        reescala a otra base.
        """
        basis = valuation.get("value_per_share_basis")
        # Inputs INFERIDO que la valoracion REALMENTE consumio (trace del motor),
        # con la version (id) del input: la procedencia se liga a esto, nunca al
        # ultimo input guardado.
        used = [
            {
                "inferred_input_id": item.get("inferred_input_id"),
                "input_key": item.get("input_key"),
                "value": item.get("value"),
                "base_inferencia": item.get("base_inferencia"),
                "urls_inferencia": list(item.get("urls_inferencia") or []),
            }
            for item in ((valuation.get("trace") or {}).get("inferred_inputs") or [])
            if isinstance(item, dict)
        ]
        if not basis and not used:
            return None
        listed = valuation.get("listed_share_values")
        extra = {"inferred_inputs_used": used} if used else {}
        # Liga verificable modelo<->tesis: el forecast solo usa horizonte y
        # probabilidades del modelo cuando ESTE fingerprint coincide. Se omite
        # la clave cuando no hay modelo ligado (contrato sin ruido).
        model_fp = (
            (valuation.get("long_term_model") or {}).get("persistence") or {}
        ).get("input_fingerprint")
        return {
            **extra,
            **({"model_input_fingerprint": model_fp} if model_fp else {}),
            "value_per_share_basis": str(basis) if basis else None,
            "adr_ratio": valuation.get("adr_ratio"),
            "listed_share_values": (
                {key: float(value) for key, value in listed.items() if value is not None}
                if isinstance(listed, dict)
                else None
            ),
        }

    def _rating(self, margin_of_safety: float | None, audit_passed: bool, status: str | None) -> str:
        if status == "insufficient_data":
            return "insufficient_data"
        if not audit_passed:
            return "blocked"
        if margin_of_safety is None:
            return "incomplete_price"
        if margin_of_safety > 0.30:
            return "attractive"
        if margin_of_safety < -0.20:
            return "expensive"
        return "watch"

    def _card_summary(
        self,
        company: Company,
        valuation: dict,
        hypothesis: str,
        news_items: list[dict] | None = None,
    ) -> str:
        """Resumen de la tarjeta "Ultima tesis": legible y en el idioma de la UI.

        La hipotesis ya se deriva solo de datos del modelo (nunca inventada);
        los estados incompletos anaden su salvedad honesta en castellano.
        El detalle de motor (bucket/engine) vive en el memo completo, no en
        la tarjeta.

        Las noticias entran como TITULARES citados VERBATIM solo cuando la
        ingesta guardo el titular original del medio (source_headline); sin
        el, el resumen compuesto por la app se presenta SIN comillas y sin
        atribuirselo al medio. La fecha solo se imprime etiquetada segun su
        procedencia (publicacion del medio, primer avistamiento GDELT o fecha
        de ingesta) y "recientes" solo se afirma cuando hay una fecha de
        publicacion real dentro de la ventana de recencia. Sin noticias
        ingeridas no se anade nada.
        """
        base: str
        if valuation.get("status") == "insufficient_data":
            missing = ", ".join(valuation.get("missing_inputs") or []) or "datos financieros basicos"
            base = (
                f"Tesis de {company.ticker} no publicable todavía: faltan {missing}. "
                "Ningún valor justo debe considerarse fiable hasta completar las fuentes."
            )
        elif valuation.get("status") == "partial":
            missing = ", ".join(valuation.get("missing_inputs") or []) or "algunos inputs"
            base = f"{hypothesis} Faltan {missing} (ver sección 13 del memo)."
        else:
            base = hypothesis

        quotes: list[str] = []
        summaries: list[str] = []
        all_recent_publications = True
        for item in (news_items or [])[:2]:
            headline = item.get("source_headline")
            headline = str(headline).strip() if isinstance(headline, str) else ""
            title = str(item.get("title") or "").strip()
            text = headline or title
            if not text:
                continue
            text = clip_words(text, 140, ellipsis="...")
            source = str(item.get("source") or "").strip()
            date_label = self._news_date_label(item)
            attribution = ", ".join(part for part in (source, date_label) if part)
            if headline:
                # Cita verbatim: solo el titular que el medio publico.
                quotes.append(f'"{text}" ({attribution})' if attribution else f'"{text}"')
                if not (
                    item.get("date_source") == "source" and self._news_is_recent(item)
                ):
                    all_recent_publications = False
            else:
                # Resumen compuesto por la app: nunca entrecomillado ni
                # atribuido como titular del medio.
                summaries.append(f"{text} ({attribution})" if attribution else text)
        if quotes:
            # "Recientes" solo si TODOS los citados son publicaciones reales
            # dentro de la ventana (0..30 dias); un solo titular viejo o de
            # procedencia no-publicacion rebaja la etiqueta del grupo.
            label = (
                "Titulares recientes"
                if all_recent_publications
                else "Titulares materiales destacados"
            )
            base = f"{base} {label}: {'; '.join(quotes)}."
        if summaries:
            base = f"{base} Noticias relevantes: {'; '.join(summaries)}."
        return base

    @staticmethod
    def _news_date_label(item: dict) -> str | None:
        """Etiqueta la fecha segun su procedencia; sin procedencia no se imprime."""
        raw = str(item.get("date") or "").strip()
        if not raw:
            return None
        # Fecha en es-ES dentro de la frase («17 de octubre de 2026»), nunca
        # en formato ISO: date_es devuelve el valor intacto si no lo reconoce.
        day = date_es(raw[:10])
        date_source = item.get("date_source")
        if date_source == "source":
            return f"publicado el {day}"
        if date_source == "gdelt_first_seen":
            return f"visto en GDELT el {day}"
        if date_source == "ingested_at_fallback":
            return f"fecha de ingesta {day}"
        return None

    @staticmethod
    def _news_is_recent(item: dict, window_days: int = 30) -> bool:
        """Recencia real: fecha de publicacion dentro de la ventana."""
        raw = str(item.get("date") or "").strip()
        if not raw:
            return False
        try:
            published = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return False
        if published.tzinfo is None:
            published = published.replace(tzinfo=UTC)
        delta_days = (datetime.now(UTC) - published).days
        # Una fecha FUTURA no es una publicacion reciente: se rechaza igual
        # que una demasiado vieja.
        return 0 <= delta_days <= window_days

    def _build_claims(
        self,
        company: Company,
        facts: dict[str, FinancialFact],
        valuation: dict,
    ) -> list[dict]:
        """Build structured claims. Metadata is non-material; facts are material."""
        claims: list[dict] = []

        # Non-material metadata — must not gate the audit as unsupported "financial" claims.
        claims.append(
            {
                "claim_id": f"{company.ticker}:company_type",
                "subject": company.ticker,
                "predicate": "company_type",
                "object": company.company_type,
                "claim": f"{company.ticker} se sigue como {_code_es(company.company_type)}.",
                "source_id": None,
                "source_type": "company_master",
                "confidence": 1.0,
                "material": False,
                "materiality": "metadata",
                "verification_state": "internal",
            }
        )
        claims.append(
            {
                "claim_id": f"{company.ticker}:valuation_model",
                "subject": company.ticker,
                "predicate": "valuation_model",
                "object": company.valuation_model,
                "claim": f"Método de valoración elegido: {_code_es(company.valuation_model)}.",
                "source_id": None,
                "source_type": "company_master",
                "confidence": 1.0,
                "material": False,
                "materiality": "metadata",
                "verification_state": "internal",
            }
        )

        for metric, fact in facts.items():
            claims.append(
                {
                    "claim_id": f"{company.ticker}:{metric}:{fact.period}",
                    "subject": company.ticker,
                    "predicate": metric,
                    "object": float(fact.value),
                    "unit": fact.unit,
                    "period": fact.period,
                    "claim": _metric_claim_statement(company.ticker, metric, fact),
                    "source_id": fact.source_id,
                    "source_type": fact.source_type,
                    "source_document_id": fact.source_id,
                    "confidence": float(fact.confidence),
                    "material": metric
                    in {"revenue", "free_cash_flow", "net_debt", "shares_diluted", "fcf_margin"},
                    "materiality": "high"
                    if metric in {"revenue", "free_cash_flow", "shares_diluted"}
                    else "medium",
                    "verification_state": "reported" if fact.is_reported else "derived",
                }
            )

        if valuation.get("status") == "insufficient_data":
            claims.append(
                {
                    "claim_id": f"{company.ticker}:valuation_blocked",
                    "subject": company.ticker,
                    "predicate": "valuation_status",
                    "object": "insufficient_data",
                    "claim": (
                        f"El valor razonable de {company.ticker} está bloqueado a la espera de: "
                        f"{', '.join(_code_es(m) for m in (valuation.get('missing_inputs') or []))}."
                    ),
                    "source_id": None,
                    "source_type": "valuation_engine",
                    "confidence": 1.0,
                    "material": False,
                    "materiality": "process",
                    "verification_state": "system",
                }
            )

        assumed = (valuation.get("trace") or {}).get("assumed")
        if (valuation.get("trace") or {}).get("valuation_basis") == "indicative_assumptions" and assumed:
            claims.append(
                {
                    "claim_id": f"{company.ticker}:indicative_assumptions",
                    "subject": company.ticker,
                    "predicate": "valuation_assumptions",
                    "object": "indicative",
                    "claim": (
                        f"El rango indicativo de {company.ticker} supone "
                        f"un margen FCF base de {_pct_es(assumed.get('fcf_margin_base'))} "
                        f"(banda {_band_es(assumed.get('fcf_margin_band'))})"
                        + (
                            " y un suelo de ingresos de $1"
                            if assumed.get("revenue_floor_used")
                            else ""
                        )
                        + "; no son datos reportados."
                    ),
                    "source_id": None,
                    "source_type": "valuation_engine",
                    "confidence": 1.0,
                    "material": False,
                    "materiality": "process",
                    "verification_state": "assumption",
                }
            )

        return claims

    def _facts_markdown(self, facts: dict[str, FinancialFact]) -> str:
        if not facts:
            return (
                "No hay un snapshot financiero coherente disponible. "
                "Ingiere hechos SEC/FMP antes de cualquier valoración publicable."
            )
        rows = [
            "| Métrica | Valor | Unidad | Periodo | Fuente |",
            "| --- | ---: | --- | --- | --- |",
        ]
        for metric, fact in facts.items():
            rows.append(
                f"| {term_es(metric)} | {format_compact_es(fact.value) or number_es(fact.value)} | {fact.unit} | {fact.period} | "
                f"{term_es(fact.source_type)} #{fact.source_id or 's/d'} |"
            )
        return "\n".join(rows)

    def _valuation_markdown(self, valuation: dict) -> str:
        if valuation.get("status") == "insufficient_data":
            missing = "\n".join(f"- {item}" for item in (valuation.get("missing_inputs") or []))
            return (
                "**SIN VALORACIÓN — datos insuficientes**\n\n"
                f"Motor: {term_es((valuation.get('trace') or {}).get('engine', 'unknown'))}\n\n"
                f"Faltan:\n{missing or '- inputs requeridos'}\n\n"
                "GerarAI no publica un valor justo a partir de supuestos de arranque."
            )

        if valuation.get("status") == "partial":
            trace = valuation.get("trace") or {}
            assumed = trace.get("assumed") or {}
            missing = "\n".join(f"- {item}" for item in (valuation.get("missing_inputs") or []))
            supuestos = (
                f"margen FCF base {_pct_es(assumed.get('fcf_margin_base'))} "
                f"(banda {_band_es(assumed.get('fcf_margin_band'))})"
                + ("; suelo de ingresos de 1 $ (sin ingresos coherentes)" if assumed.get("revenue_floor_used") else "")
                + f"; crecimiento de ingresos {assumed.get('revenue_growth')}"
                + f"; WACC {assumed.get('wacc')}"
                + f"; terminal {assumed.get('terminal_growth')}"
            )
            return (
                "**RANGO INDICATIVO PARCIAL — no es un valor justo final**\n\n"
                f"Motor: {term_es(trace.get('engine', 'unknown'))} "
                f"(base: {_code_es(trace.get('valuation_basis', 'indicative_assumptions'))}).\n\n"
                f"{self._range_lines(valuation)}\n\n"
                f"Supuestos del motor de valoración (NO son datos reportados): {supuestos}. "
                "N/D significa que este motor no los pudo fijar; el modelo a largo plazo "
                "usa otros supuestos, con su procedencia en la sección 22.\n\n"
                f"DCF inverso frente a precio de mercado: ver sección 14.\n\n"
                "Aún falta antes de publicar:\n"
                f"{missing or '- este motor no lista inputs faltantes; revisa los datos pendientes de la sección 21'}\n\n"
                f"{trace.get('notice', '')}"
            )

        return "\n".join(
            [
                f"- Estado: `{valuation.get('status')}` publicable={valuation.get('publishable')}",
                *self._range_lines(valuation).split("\n"),
                f"- Fuente de inputs: {term_es((valuation.get('trace') or {}).get('input_source', 'unknown'))}",
                f"- Motor: {term_es((valuation.get('trace') or {}).get('engine', 'unknown'))}",
            ]
        )

    def _range_lines(self, valuation: dict) -> str:
        price = valuation.get("current_price")
        mos = valuation.get("margin_of_safety")
        price_txt = f"{price:.2f}" if price is not None else "N/D (sin precio de mercado)"
        mos_txt = percent_es(mos) if mos is not None else "N/D (requiere precio de mercado)"

        def fmt(v):
            return f"{v:.2f}" if v is not None else "N/D"

        return "\n".join(
            [
                f"- Precio actual: {price_txt}",
                f"- Valor bear: {fmt(valuation.get('bear_value'))}",
                f"- Valor base: {fmt(valuation.get('base_value'))}",
                f"- Valor bull: {fmt(valuation.get('bull_value'))}",
                f"- Valor esperado: {fmt(valuation.get('expected_value'))}",
                f"- Margen de seguridad: {mos_txt}",
            ]
        )

    def _moat_markdown(self, company: Company, valuation: dict) -> str:
        moat = valuation.get("moat") or empty_moat_framework(
            company.company_type, company.factor_tags or [], company.special_risks or []
        )
        lines = [
            moat.get("note", "Se requiere evidencia con fuente antes de afirmaciones cualitativas finales."),
            "",
            "| Tipo | Fuerza | Tendencia | Confianza | Estado |",
            "| --- | ---: | --- | ---: | --- |",
        ]
        for item in moat.get("moats") or []:
            lines.append(
                f"| {item.get('type')} | {item.get('strength', 0):.2f} | {item.get('trend')} | "
                f"{item.get('confidence', 0):.2f} | {item.get('status')} |"
            )
        return "\n".join(lines)

    def _earnings_markdown(self, sources: dict) -> str:
        earnings = sources.get("earnings") or {}
        transcript = sources.get("transcript") or {}
        lines = [
            "Las afirmaciones de las calls se guardan aparte y se verifican después contra lo reportado."
        ]
        if earnings.get("status") == "ok":
            extra = f" {_hora_es(earnings['time'])}" if earnings.get("time") else ""
            eps = earnings.get("eps_forecast")
            eps_txt = f", EPS estimado {eps}" if eps is not None else ""
            lines.append(f"Próximos resultados: {earnings.get('next_date')}{extra}{eps_txt}.")
        else:
            lines.append(
                f"Próximos resultados: pendiente ({earnings.get('detail', 'sin fecha de resultados')})."
            )
            if earnings.get("action"):
                lines.append(f"Acción: {earnings['action']}")
        if transcript.get("status") == "ok":
            lines.append(
                f"Última transcripción: {transcript.get('title')} ({transcript.get('period')})."
            )
        else:
            lines.append(
                f"Transcripción: {transcript.get('detail', 'pendiente transcripción')}."
            )
            if transcript.get("action"):
                lines.append(f"Acción: {transcript['action']}")
        return "\n".join(lines)

    def _news_markdown(self, sources: dict) -> str:
        news = sources.get("news") or {}
        base = (
            "Las noticias materiales requieren auditoría de fuentes y aprobación "
            "humana antes de versionar la tesis."
        )
        items = news.get("items") or []
        if not items:
            pending = news.get("detail", "sin noticias ingeridas")
            action = f" Acción: {news['action']}" if news.get("action") else ""
            return f"{base}\nÚltimas noticias materiales: pendiente ({pending}).{action}"
        rows = [base, "", "Últimas noticias materiales:"]
        for item in items:
            rows.append(
                f"- {item.get('date', '?')} [{item.get('source', '?')}] "
                f"{item.get('title', '')} (materialidad {item.get('materiality', '?')})"
            )
        return "\n".join(rows)

    def _sources_markdown(self, sources: dict) -> str:
        ok: list[str] = ["- Semilla maestra de la empresa"]
        pending: list[str] = []
        labels = {
            "fundamentals": "Fundamentales",
            "market": "Precio/perfil de mercado",
            "filings": "Filings 10-K/10-Q/8-K",
            "news": "Noticias",
            "earnings": "Fecha de resultados",
            "transcript": "Transcripción",
            "ir": "Relación con inversores",
            "external_theses": "Tesis externas",
        }
        for key, label in labels.items():
            block = sources.get(key) or {}
            if block.get("status") == "ok":
                detail = self._source_ok_detail(key, block)
                ok.append(f"- {label}: conseguido ({detail})")
            else:
                reason = block.get("detail", "pendiente") if block else "no intentado"
                action = f" | Acción: {block['action']}" if block.get("action") else ""
                pending.append(f"- {label}: pendiente ({reason}){action}")
        lines = ["Conseguido:"] + ok
        if pending:
            lines += ["", "Pendiente:"] + pending
        return "\n".join(lines)

    def _source_ok_detail(self, key: str, block: dict) -> str:
        if key == "fundamentals":
            metrics = ", ".join(block.get("metrics") or [])
            if block.get("detail"):
                timestamp = block.get("last_refreshed_at")
                return f"{block['source']}: {block['detail']}" + (f" Fecha: {timestamp}." if timestamp else "")
            imported = block.get("facts_imported") or 0
            already = block.get("already_present") or 0
            if imported == 0 and already:
                # Refresco sin novedades: los hechos ya estaban importados.
                # El copy anterior («0 hechos: <metricas>») se contradecia:
                # decia 0 hechos y a la vez listaba metricas cubiertas.
                base = f"{block.get('source')}: {already} hechos ya importados, sin novedades"
            else:
                base = f"{block.get('source')}, {imported} hechos importados"
                if already:
                    base += f" ({already} ya presentes)"
            return base + (f". Métricas cubiertas: {metrics}" if metrics else "")
        if key == "market":
            parts = []
            if block.get("price") is not None:
                parts.append(f"precio {block['price']}")
            if block.get("market_cap") is not None:
                parts.append(f"capitalización {block['market_cap']:.0f}")
            if block.get("name"):
                parts.append(f"nombre '{block['name']}'")
            return f"{block.get('source')}" + (f": {', '.join(parts)}" if parts else "")
        if key == "filings":
            forms = ", ".join(
                f"{i.get('form')} {i.get('filing_date')}" for i in (block.get("items") or [])
            )
            return f"{block.get('source')}: {forms}"
        if key == "news":
            return f"{len(block.get('items') or [])} eventos materiales"
        if key == "earnings":
            return f"próximos {block.get('next_date')}"
        if key == "transcript":
            return f"{block.get('title')} ({block.get('period')})"
        if key == "ir":
            titles = "; ".join(
                str(i.get("title") or "") for i in (block.get("items") or [])[:3]
            )
            return f"{block.get('source')}: {len(block.get('items') or [])} comunicados ({titles})"
        if key == "external_theses":
            return f"{len(block.get('items') or [])} tesis pegadas"
        return str(block.get("source") or "ok")

    @staticmethod
    def _provenance_markdown(items: list[dict]) -> str:
        if not items:
            return "Sin inputs etiquetables: el modelo no tiene aún datos con procedencia."
        lines = [
            "Cada input del modelo lleva su etiqueta: **dato** (línea reportada "
            "con cita), **derivado** (fórmula documentada + inputs), "
            "**estimacion_llm** (método + confianza) o **supuesto** (justificación).",
            "",
            "| input | etiqueta | valor | método | cita |",
            "|---|---|---|---|---|",
        ]
        for item in items:
            value = item.get("value")
            value_txt = "s/d" if value is None else number_es(f"{float(value):.4g}")
            facts = item.get("source_fact_ids") or []
            ids = ", ".join(str(f) for f in facts)
            citation = (f"{len(facts)} hecho citado ({ids})" if len(facts) == 1 else f"{len(facts)} hechos citados ({ids})") if facts else "-"
            method = (item.get("method") or "-").replace("|", "/")
            lines.append(
                f"| {term_es(item.get('key'))} | {item.get('label')} | {value_txt} | {method} | {citation} |"
            )
        return "\n".join(lines)

    # Human-in-the-loop (spec 2026-09-30): la tesis sale SIEMPRE con lo que
    # hay; lo que falta se declara pendiente y se pide, nunca se inventa.
    _PENDING_INPUT_HINTS = {
        "revenue_history_two_periods": (
            "faltan al menos dos períodos de ingresos reportados; llegan con el "
            "10-K/10-Q más reciente (SEC) o la presentación de resultados."
        ),
        "normalized_fcf_margin": (
            "falta el margen FCF normalizado; se deriva de cash-flows reportados "
            "o se aporta como supuesto etiquetado (método + fecha)."
        ),
        "normalized_fcf_or_fcf_margin": (
            "falta un FCF o margen FCF reportado; si hay un margen estimado con base "
            "y fuentes https, se usa solo como valor indicativo no publicable."
        ),
        "net_debt": (
            "falta la deuda neta; se deriva de deuda total menos efectivo (mismo "
            "período) cuando ambos constan en un filing."
        ),
        "shares_diluted": (
            "faltan las acciones diluidas; constan en el último 10-K/10-Q o en "
            "la presentación de resultados."
        ),
        "traceable_wacc": (
            "el WACC no es trazable a una métrica calculada; se aporta como "
            "supuesto documentado (método + fecha + inputs)."
        ),
        "fiscal_year": (
            "falta el ejercicio fiscal de anclaje; llega con los filings anuales."
        ),
    }

    @classmethod
    def _pending_input_hint(cls, key: str) -> str:
        if key in cls._PENDING_INPUT_HINTS:
            return cls._PENDING_INPUT_HINTS[key]
        return (
            "dato pendiente: se aporta con fuente verificable (filing, KPI "
            "aprobado o supuesto etiquetado) y la tesis se regenera al "
            "incorporarlo."
        )

    def _pendings_markdown(
        self,
        valuation: dict,
        long_term_model: dict,
        sources: dict,
        fact_sources: dict[int, dict] | None = None,
    ) -> str:
        missing = sorted(
            set(
                (valuation.get("missing_inputs") or [])
                + (long_term_model.get("missing_inputs") or [])
            )
        )
        lines: list[str] = []
        if missing:
            lines.append(
                "Inputs que faltan para completar la tesis. La tesis se publica "
                "con lo que hay; estos datos se piden al usuario y nunca se "
                "inventan:"
            )
            for key in missing:
                lines.append(f"- `{key}`: {self._pending_input_hint(key)}")
        # Politica del producto: un supuesto sin base documentada no se muestra como
        # INFERIDO; se declara N/D (sin datos), igual que cualquier input pendiente.
        nd_keys = sorted(
            {
                str(item.get("key"))
                for item in classify_origin(build_inputs_provenance(long_term_model), fact_sources or {})
                if item.get("origen") == "INFERIDO" and item.get("base_documentada") is False
            }
        )
        if nd_keys:
            if lines:
                lines.append("")
            lines.append(
                "Supuestos sin base documentada (N/D, no se muestran como inferidos):"
            )
            for key in nd_keys:
                lines.append(f"- `{key}`: N/D (supuesto sin base documentada).")
        pending_sources = [
            (name, block.get("source"), block.get("detail"))
            for name, block in sorted((sources or {}).items())
            if isinstance(block, dict) and block.get("status") == "pending"
        ]
        if pending_sources:
            if lines:
                lines.append("")
            lines.append("Fuentes de evidencia pendientes de captura:")
            for name, source, detail in pending_sources:
                suffix = f" ({detail})" if detail else ""
                lines.append(f"- {name}: {source or 'fuente no disponible'}{suffix}")
        if not lines:
            return "Sin datos pendientes: la tesis se apoya en la evidencia disponible."
        return "\n".join(lines)

    def _render_markdown(
        self,
        company: Company,
        valuation: dict,
        audit: dict,
        facts: dict[str, FinancialFact],
        *,
        long_term_model: dict,
        version: int,
        evidence: dict | None = None,
        hypothesis: str | None = None,
        catalysts: list | None = None,
        invalidation_criteria: list | None = None,
        scenario_probabilities: dict | None = None,
        fact_sources: dict[int, dict] | None = None,
    ) -> str:
        reverse = valuation.get("reverse_dcf") or {}
        required_growth = reverse.get("required_revenue_growth")
        reverse_line = (
            f"Crecimiento de ingresos requerido: {percent_es(required_growth)}"
            if required_growth is not None
            else "DCF inverso no disponible (falta el precio de mercado o inputs de valoración)."
        )
        scenario_style = (valuation.get("trace") or {}).get("scenario_style", "n/a")
        framework = long_term_model.get("framework") or {}
        mandatory_missing = long_term_model.get("missing_mandatory_drivers") or []
        market_opportunity = long_term_model.get("market_opportunity") or {}
        evidence = evidence or {}
        sources = evidence.get("sources") or {}
        hypothesis = hypothesis or self._hypothesis(company, valuation)
        catalysts = catalysts if catalysts is not None else self._catalysts(evidence)
        invalidation_criteria = (
            invalidation_criteria
            if invalidation_criteria is not None
            else self._invalidation_criteria(company, valuation)
        )
        scenario_probabilities = (
            scenario_probabilities
            if scenario_probabilities is not None
            else self._scenario_probabilities(long_term_model)
        )
        probabilities_line = (
            "Probabilidades (modelo): "
            + " · ".join(f"{name} {percent_es(prob, 0)}" for name, prob in scenario_probabilities.items())
            if scenario_probabilities
            else "Probabilidades: pendiente (el modelo no las ha persistido)."
        )
        pendings_section = self._pendings_markdown(
            valuation, long_term_model, sources, fact_sources
        )
        provenance_section = self._provenance_markdown(
            build_inputs_provenance(long_term_model)
        )
        catalysts_lines = "\n".join(
            f"- {item.get('label')}: {item.get('date')}"
            + (f" {_hora_es(item.get('time'))}" if item.get('time') else "")
            + (f" (EPS estimado {item.get('eps_forecast')})" if item.get("eps_forecast") is not None else "")
            for item in catalysts
        ) or "- Sin catalizadores con fecha conocida; pendiente del calendario de resultados."
        invalidation_lines = "\n".join(f"- {criterion}" for criterion in invalidation_criteria)

        return f"""# Tesis de {company.ticker} — v{version}

## 1. Resumen ejecutivo
{company.name} se sigue como {term_es(company.company_type)} con el modelo {term_es(company.valuation_model)}.
Fuente de los inputs de valoración: {term_es((valuation.get("trace") or {}).get("input_source", "unknown"))}.
Motor: {term_es((valuation.get("trace") or {}).get("engine", "unknown"))}.

## 2. Hipótesis
{hypothesis}
La pregunta invertible es si la evidencia respalda los supuestos detrás del modelo elegido, no si la salida de un modelo parece atractiva de forma aislada.

## 3. Modelo de negocio
Sector: {company.sector}. Industria: {company.industry}.
Marco específico de la empresa: {term_es(framework.get("key", "unknown"))}. Pregunta primaria: {str(framework.get("primary_question") or "desconocida").rstrip(" .?!")}.
Drivers obligatorios ausentes: {", ".join(mandatory_missing) if mandatory_missing else "ninguno"}.

## 4. Últimos resultados
{self._facts_markdown(facts)}

## 5. Histórico financiero
Los últimos resultados con su fuente y periodo están en la sección 4. La serie histórica completa está en la pestaña «Financieros» de la ficha.

## 6. Flujo de caja libre
El flujo de caja libre de la sección 4 solo se muestra si procede de hechos reportados del mismo ejercicio. Sin ese dato la valoración no se presenta como definitiva.

## 7. Balance
Caja, deuda total y deuda neta de la sección 4 corresponden al mismo ejercicio que la cuenta de resultados cuando están disponibles; si falta alguno, aparece como pendiente en la sección 21.

## 8. Asignación de capital
Recompras, dilución y dividendos se consultan en las pestañas «Dilución y recompras» y «Financieros» de la ficha.

## 9. Equipo directivo y calls
{self._earnings_markdown(sources)}

## 10. Noticias y catalizadores
{catalysts_lines}
{self._news_markdown(sources)}

## 11. Riesgos
{", ".join(company.special_risks) or "Sin riesgos específicos registrados para esta empresa."}

## 12. Competencia y foso
{self._moat_markdown(company, valuation)}

## 13. Valoración
{self._valuation_markdown(valuation)}

### Motor fundamental de largo plazo
Versión persistida del modelo: `{(long_term_model.get("persistence") or {}).get("version")}`.
Estado del modelo: `{long_term_model.get("status")}`. Veredicto de oportunidad de mercado: `{(market_opportunity.get("verdict") or {}).get("label", "unknown")}`.

## 14. DCF inverso
{reverse_line}

## 15. Bear / Base / Bull
Estilo de escenarios: `{scenario_style}`. {probabilities_line}

## 16. Red team
Pregunta primaria del red team: ¿qué supuesto se rompería primero si el próximo filing contradice el modelo actual?

## 17. Qué invalidaría la tesis
{invalidation_lines}
Invalidadores estructurales: afirmaciones sin respaldo, trazas de cálculo ausentes, filings primarios adversos, snapshots incoherentes o deriva material de supuestos.

## 18. Qué vigilar
{", ".join(company.special_sources) or "Sin fuentes específicas registradas para esta empresa; ver la sección 20."}

## 19. Auditoría de fuentes
Superada: {"sí" if audit["passed"] else "no"}
Cobertura de fuentes: {audit["source_coverage_score"]} %
Afirmaciones sin respaldo: {len(audit["unsupported_claims"] or [])}

## 20. Fuentes
{self._sources_markdown(sources)}

## 21. Datos pendientes
{pendings_section}

## 22. Procedencia de los inputs
{provenance_section}
Fingerprint: el hash del conjunto de evidencia gobierna el versionado.
"""
