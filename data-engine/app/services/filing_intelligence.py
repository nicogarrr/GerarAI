"""Tenant-bound filing changes and earnings excerpts in the existing document store.

Vínculo directo filing -> criterio de tesis: tras analizar un documento, si la
tesis vigente tiene criterios ``metrica:X`` y ESTE filing aporta un
``FinancialFact`` de X posterior al último evaluado, el criterio se evalúa al
momento (``result["thesis_check"]``, mismo ajuste de splits y misma exclusión
de trimestres en flujos que ``thesis_invalidation_rules.observe``). Un
criterio cruzado emite una alerta ``thesis_invalidation_filing`` de severidad
``high`` con métrica, umbral, valor y cita (URL + checksum); su fingerprint
lleva ``rule_name`` + ``fact_id``, así que el mismo hecho nunca avisa dos
veces y dos criterios distintos sí avisan por separado. Sin cruce, el
comportamiento es el de siempre. ``observe()`` no cambia: el evaluador
periódico sigue su camino; esto solo adelanta el aviso al filing que lo
causa. Sin LLM, sin red y sin commit: el llamante posee la transacción.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from urllib.parse import quote, urlsplit

from sqlalchemy import desc, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    Company,
    Document,
    DocumentChunk,
    FinancialFact,
    Position,
    ResearchAlert,
    ThesisVersion,
    WatchItem,
)
from app.services.company_resolver import resolve_company
from app.services.earnings_releases import summarize_release
from app.services.filing_changes import comparable, compare_sections, reported_period
from app.services.notification_service import record_in_app_delivery
from app.services.split_adjustment import split_factor_for_fact
from app.services.thesis_invalidation_rules import (
    METRIC_PREFIX,
    PER_SHARE_METRICS,
    QUARTER_LABELS,
    SHARE_COUNT_METRICS,
    describe_rule,
    normalize_rules,
)
from app.services.ttm_fundamentals import FLOW_METRICS

logger = logging.getLogger(__name__)

VERSION = "filing-intelligence-v1"
KEY = "filing_intelligence"
MAX_CHUNKS = 2000


def official_document(document: Document) -> bool:
    try:
        url = urlsplit(document.source_url or "")
    except ValueError:
        return False
    return (
        url.scheme == "https"
        and not url.username
        and not url.password
        and (
            (url.hostname in {"www.sec.gov", "sec.gov"} and url.path.startswith("/Archives/edgar/data/"))
            or url.hostname in {"www.cnmv.es", "cnmv.es"}
        )
        and document.source_type.lower() in {"sec", "cnmv", "primary_official", "esef"}
    )


def _chunks(db: Session, document: Document) -> list[dict] | None:
    rows = db.scalars(
        select(DocumentChunk)
        .where(
            DocumentChunk.tenant_id == document.tenant_id,
            DocumentChunk.document_id == document.id,
        )
        .order_by(DocumentChunk.chunk_index)
        .limit(MAX_CHUNKS + 1)
    ).all()
    if len(rows) > MAX_CHUNKS:
        return None
    return [{"id": row.id, "chunk_index": row.chunk_index, "text": row.text} for row in rows]


def _citation(document: Document) -> dict:
    return {
        "document_id": document.id,
        "url": document.source_url,
        "checksum": document.checksum,
        "published_at": document.published_at.isoformat() if document.published_at else None,
        "reported_period": (
            reported_period(document.metadata_ or {}).isoformat()
            if reported_period(document.metadata_ or {})
            else None
        ),
    }


def _facts_query(tenant: int, company_id: int, name: str):
    query = select(FinancialFact).where(
        FinancialFact.tenant_id == tenant,
        FinancialFact.company_id == company_id,
        FinancialFact.metric == name,
    )
    if name in FLOW_METRICS:
        # Misma regla que observe(): un flujo trimestral no se compara con un umbral anual.
        query = query.where(
            or_(
                FinancialFact.fiscal_quarter.is_(None),
                FinancialFact.fiscal_quarter.not_in(QUARTER_LABELS),
            ),
            ~or_(*(FinancialFact.period.like(f"%:{q}") for q in QUARTER_LABELS)),
        )
    return query


def _quarter_rank(fact: FinancialFact) -> int:
    q = fact.fiscal_quarter
    return QUARTER_LABELS.index(q) + 1 if q in QUARTER_LABELS else 0


def _period_key(fact: FinancialFact) -> tuple:
    """Orden explícito de periodo: (ejercicio, trimestre, etiqueta de periodo).

    Un ratio/balance del Q3 2026 es dato NUEVO frente al Q1 2026 del mismo
    ejercicio; la comparación por año solo los trataba como reingesta. Los
    flujos trimestrales ya están excluidos en ``_facts_query`` (umbral anual).
    """
    return (fact.fiscal_year or 0, _quarter_rank(fact), fact.period or "")


def _latest(facts: Sequence[FinancialFact]) -> FinancialFact | None:
    return max(facts, key=lambda f: (*_period_key(f), f.id or 0), default=None)


def _fact_value(db: Session, company_id: int, name: str, fact: FinancialFact) -> Decimal | None:
    """Valor comparable con el umbral: reexpresado por splits como en observe()."""
    if fact.value is None:
        return None
    value = Decimal(fact.value)
    if name in PER_SHARE_METRICS or name in SHARE_COUNT_METRICS:
        factor = split_factor_for_fact(
            db, company_id, period=fact.period, filed=fact.filed, cutoff=datetime.now(UTC).date()
        )
        value = value / factor if name in PER_SHARE_METRICS else value * factor
    return value


def _crossed(observed: Decimal, operator: str, threshold: Decimal) -> bool:
    return {
        ">": observed > threshold,
        "<": observed < threshold,
        ">=": observed >= threshold,
        "<=": observed <= threshold,
        "==": observed == threshold,
        "!=": observed != threshold,
    }[operator]


def _thesis_check(
    db: Session, tenant: int, document: Document, company: Company, thesis: ThesisVersion
) -> list[dict]:
    """Cruce filing -> criterio ``metrica:X``: si ESTE filing aporta un FinancialFact
    de X posterior al último conocido, se evalúa contra el umbral. Sin LLM ni red.
    Estados: ``crossed`` | ``not_crossed`` | ``missing`` (sin dato nuevo: nunca dispara)."""
    try:
        rules = normalize_rules(thesis.invalidation_rules or [])
    except ValueError:
        return []  # criterios corruptos guardados: no rompen el análisis del filing
    checks: list[dict] = []
    for rule in rules:
        metric = str(rule.get("metric") or "")
        if not metric.startswith(METRIC_PREFIX):
            continue  # precio/margen/variación: los evalúa el evaluador periódico (observe)
        name = metric[len(METRIC_PREFIX) :].strip()
        rule_name = f"{company.ticker}: invalidación de tesis · {describe_rule(rule)}"
        base = {
            "rule_name": rule_name,
            "metric": name,
            "observed": None,
            "threshold": rule.get("threshold"),
            "operator": rule.get("operator"),
            "fact_id": None,
        }
        new_fact = _latest(
            db.scalars(
                _facts_query(tenant, company.id, name).where(FinancialFact.source_id == document.id)
            ).all()
        )
        if new_fact is None:
            checks.append({**base, "status": "missing"})
            continue
        previous = _latest(
            db.scalars(
                _facts_query(tenant, company.id, name).where(
                    # ``!=`` en SQL excluye NULL: los hechos previos sin
                    # source_id (importados sin documento) también cuentan.
                    or_(FinancialFact.source_id != document.id, FinancialFact.source_id.is_(None))
                )
            ).all()
        )
        if previous is not None and _period_key(new_fact) <= _period_key(previous):
            # No es dato nuevo (reingesta del mismo periodo): no reevalúa ni dispara.
            checks.append({**base, "status": "missing", "fact_id": new_fact.id})
            continue
        observed = _fact_value(db, company.id, name, new_fact)
        if observed is None:
            checks.append({**base, "status": "missing", "fact_id": new_fact.id})
            continue
        threshold = Decimal(str(rule["threshold"]))
        crossed = _crossed(observed, str(rule["operator"]), threshold)
        checks.append(
            {
                **base,
                "observed": float(observed),
                "status": "crossed" if crossed else "not_crossed",
                "fact_id": new_fact.id,
                "period": new_fact.period,
            }
        )
    return checks


def analyze_document(db: Session, document: Document) -> dict:
    """No commit, network calls or LLM. Caller owns transaction and retries."""
    tenant = db.info.get("tenant_id")
    if tenant is None or tenant != document.tenant_id:
        raise ValueError("Tenant context required for filing analysis")
    if not official_document(document):
        return {"status": "insufficient_data", "reason": "Sin documento SEC/CNMV con URL oficial."}
    company = db.get(Company, document.company_id) if document.company_id else None
    chunks = _chunks(db, document)
    meta = document.metadata_ or {}
    result = {"version": VERSION, "source": _citation(document)}
    if not chunks:
        # El hecho estructurado no depende del texto: la tesis se evalúa
        # también sin chunks; un criterio cruzado eleva la alerta igual que
        # con texto, y reason queda en metadata.
        result["status"] = "insufficient_data"
        result["reason"] = "Sin texto completo disponible dentro del límite de análisis."
        thesis = (
            db.scalar(
                select(ThesisVersion)
                .where(
                    ThesisVersion.tenant_id == tenant,
                    ThesisVersion.company_id == document.company_id,
                )
                .order_by(desc(ThesisVersion.version))
                .limit(1)
            )
            if company
            else None
        )
        result["thesis_check"] = (
            _thesis_check(db, tenant, document, company, thesis) if company and thesis else []
        )
        document.metadata_ = {**meta, KEY: result}
        db.flush()
        if company:
            _alert(db, company, document, result, event_type="new_filing")
        return result
    form = meta.get("form")
    if form == "8-K" or (str(form).startswith("EX-99") and meta.get("parent_form") == "8-K"):
        result["earnings"] = summarize_release(chunks, meta)
        result["status"] = result["earnings"]["status"]
    else:
        prior = None
        # SQL bounds by declared period year, not ingestion date; no arbitrary
        # latest-N window can starve a valid year-ago report after re-ingestion.
        period = reported_period(meta)
        if period and form in {"10-K", "10-Q", "20-F", "40-F", "annual_report"}:
            candidates = db.scalars(
                select(Document)
                .where(
                    Document.tenant_id == tenant,
                    Document.company_id == document.company_id,
                    Document.id != document.id,
                    Document.metadata_["form"].as_string() == form,
                    or_(
                        Document.metadata_["report_date"].as_string().like(f"{period.year - 1}-%"),
                        Document.metadata_["period_of_report"].as_string().like(f"{period.year - 1}-%"),
                    ),
                )
                .order_by(desc(Document.published_at), desc(Document.id))
            )
            for candidate in candidates:
                if official_document(candidate) and comparable(meta, candidate.metadata_ or {}):
                    prior = candidate
                    break
        before = _chunks(db, prior) if prior else None
        if prior is None or not before:
            result["status"] = "insufficient_data"
            result["reason"] = "Sin informe comparable del mismo periodo del año anterior."
        else:
            result["previous_source"] = _citation(prior)
            result["diff"] = compare_sections(chunks, before)
            result["status"] = result["diff"]["status"]
    company = db.get(Company, document.company_id) if document.company_id else None
    thesis = (
        db.scalar(
            select(ThesisVersion)
            .where(
                ThesisVersion.tenant_id == tenant,
                ThesisVersion.company_id == document.company_id,
            )
            .order_by(desc(ThesisVersion.version))
            .limit(1)
        )
        if company
        else None
    )
    result["thesis_version_id"] = thesis.id if thesis else None
    result["thesis_path"] = f"/research/{quote(company.ticker, safe='')}" if company else None
    result["thesis_check"] = (
        _thesis_check(db, tenant, document, company, thesis) if company and thesis else []
    )
    # Metadata replacement is required for SQLAlchemy JSON dirty tracking.
    document.metadata_ = {**meta, KEY: result}
    db.flush()
    if company:
        _alert(
            db,
            company,
            document,
            result,
            event_type=None if result["status"] in {"changed", "ready"} else "new_filing",
        )
    return result


def _watched(db: Session, tenant: int, company: Company) -> bool:
    """¿Sigue el tenant a esta compañía? Resolución por símbolo cacheada en
    ``db.info`` por (tenant, símbolo): la caché vive TODA la sesión (la
    unidad de trabajo), no una pasada; un símbolo añadido o que se haga
    resoluble a mitad de sesión no se refleja hasta la siguiente. Se asume
    que la watchlist no cambia dentro de la sesión y un símbolo no resoluble
    no bloquea ni se reintenta. Los no resueltos se cuentan en el log
    (métrica unresolved_watch_symbols)."""
    symbols = db.scalars(select(WatchItem.symbol).where(WatchItem.tenant_id == tenant)).all()
    cache = db.info.setdefault("watch_resolution_cache", {})
    unresolved = 0
    watched = False
    for symbol in symbols:
        key = (tenant, symbol)
        if key not in cache:
            resolved = resolve_company(db, symbol)
            cache[key] = resolved.id if resolved is not None else None
        company_id = cache[key]
        if company_id is None:
            unresolved += 1
            continue
        if company_id == company.id:
            watched = True
            break
    if unresolved:
        logger.info(
            "unresolved_watch_symbols",
            extra={"tenant_id": tenant, "unresolved_watch_symbols": unresolved},
        )
    return watched


def _alert(
    db: Session, company: Company, document: Document, result: dict, *, event_type: str | None = None
) -> None:
    tenant = db.info["tenant_id"]
    held = db.scalar(
        select(Position.id)
        .where(
            Position.tenant_id == tenant,
            Position.company_id == company.id,
            Position.quantity > 0,
        )
        .limit(1)
    )
    watched = _watched(db, tenant, company)
    if held is None and not watched:
        return
    matching = (["cartera"] if held is not None else []) + (["watchlist"] if watched else [])
    crossed = [c for c in result.get("thesis_check") or [] if c.get("status") == "crossed"]
    if crossed:
        # Un criterio de invalidación cruzado por ESTE filing: alerta high con
        # métrica, umbral, valor y cita. Fingerprint por regla + hecho: el mismo
        # hecho nunca avisa dos veces; dos criterios distintos avisan por separado.
        for check in crossed:
            fingerprint = hashlib.sha256(
                f"{VERSION}|{tenant}|{company.id}|{document.source_url}|{document.checksum}"
                f"|{check['rule_name']}|{check['fact_id']}".encode()
            ).hexdigest()
            if (
                db.scalar(
                    select(ResearchAlert.id).where(
                        ResearchAlert.tenant_id == tenant,
                        ResearchAlert.fingerprint == fingerprint,
                    )
                )
                is not None
            ):
                continue
            title = f"{company.ticker}: criterio de tesis cruzado por un filing"
            message = (
                f"El filing aporta {check['metric']} = {check['observed']} "
                f"(criterio {check['operator']} {check['threshold']}). "
                f"Fuente: {document.source_url} (checksum {document.checksum})."
            )
            try:
                with db.begin_nested():
                    alert = ResearchAlert(
                        tenant_id=tenant,
                        company_id=company.id,
                        severity="high",
                        status="open",
                        alert_type="thesis_invalidation_filing",
                        title=title,
                        message=message,
                        fingerprint=fingerprint,
                        channels=["in_app"],
                        last_triggered_at=datetime.now(UTC),
                        metadata_={
                            **result,
                            "document_id": document.id,
                            "source_url": document.source_url,
                            "matching": matching,
                            "thesis_rule": check,
                        },
                    )
                    db.add(alert)
                    db.flush()
                    record_in_app_delivery(db, alert)
            except IntegrityError:
                if (
                    db.scalar(
                        select(ResearchAlert.id).where(
                            ResearchAlert.tenant_id == tenant,
                            ResearchAlert.fingerprint == fingerprint,
                        )
                    )
                    is None
                ):
                    raise
        return
    fingerprint = hashlib.sha256(
        f"{VERSION}|{tenant}|{company.id}|{document.source_url}|{document.checksum}".encode()
    ).hexdigest()
    if (
        db.scalar(
            select(ResearchAlert.id).where(
                ResearchAlert.tenant_id == tenant,
                ResearchAlert.fingerprint == fingerprint,
            )
        )
        is not None
    ):
        return
    earnings = "earnings" in result
    title = f"{company.ticker}: {'comunicado de resultados' if earnings else 'cambios en el informe'}"
    message = (
        "Comunicado de resultados disponible con citas originales."
        if earnings
        else "Cambios textuales frente al mismo periodo del año anterior. No implican por sí solos materialidad financiera."
    )
    if event_type == "new_filing":
        title = f"Documento oficial nuevo: {company.ticker}"
        message = "Documento SEC/CNMV disponible. El análisis puede estar pendiente o sin datos; revisa la fuente antes de cambiar la tesis."
    try:
        with db.begin_nested():
            alert = ResearchAlert(
                tenant_id=tenant,
                company_id=company.id,
                severity="medium",
                status="open",
                alert_type=event_type or ("earnings_release" if earnings else "filing_changes"),
                title=title,
                message=message,
                fingerprint=fingerprint,
                channels=["in_app"],
                last_triggered_at=datetime.now(UTC),
                metadata_={
                    **result,
                    "document_id": document.id,
                    "source_url": document.source_url,
                    "matching": matching,
                },
            )
            db.add(alert)
            db.flush()
            record_in_app_delivery(db, alert)
    except IntegrityError:
        # Only suppress the unique-fingerprint race, not another integrity bug.
        if (
            db.scalar(
                select(ResearchAlert.id).where(
                    ResearchAlert.tenant_id == tenant,
                    ResearchAlert.fingerprint == fingerprint,
                )
            )
            is None
        ):
            raise
