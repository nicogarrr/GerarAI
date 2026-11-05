"""«Mezcla de analistas»: rellena los inputs que faltan con las hipótesis de las mejores firmas.

Feature aprobada por Nico (4-nov-2026, 12:22–12:44): el equipo de expertos
infiere solo los inputs que faltan, sin números a mano. Es la etapa del
pipeline de la tesis que va DESPUÉS del Recopilador y de la detección de
huecos (``DeclaredInputService.detect_gaps``) y ANTES de valorar
(SPEC_ADDENDUM §6.6, «mezcla de analistas cuando falten datos»).

Cómo trabaja (nada por ticker):

1. Si la empresa no tiene huecos en su modelo declarado (datos completos), la
   etapa NO hace nada: ni LLM ni escritura (``status='full_data'``). Las
   hipótesis de analistas nunca sustituyen datos propios.
2. Firmas que cuentan: las del ranking por historial de esa empresa
   (``AnalystHistoryService``, #4543) en su mejor horizonte, que baten a sus
   pares (error relativo < 0) con muestra suficiente (≥ ``MIN_PEER_SCORED_SAMPLES``
   objetivos comparados con pares). Si no hay ninguna, no se mezcla nada.
3. Evidencia: pasajes de los documentos ingeridos y noticias del tenant que
   nombran a esas firmas, más las fuentes extra que se le pasen (la costura
   para las notas de analista estructuradas de #4582 cuando se fusione).
4. Un LLM devuelve, input a input y firma a firma, el supuesto que esa firma
   publica, con su cita literal. Fail-closed: la cita tiene que aparecer
   palabra por palabra en la evidencia citada, la firma tiene que salir en esa
   evidencia y estar entre las que cuentan, y el input tiene que ser un hueco.
   Un problema invalida la respuesta entera (un reintento con los problemas).
5. Se descarta lo que viola límites económicos (crecimiento perpetuo por
   encima del PIB nominal a largo plazo; reposición nula de activos con vida
   finita) y se dice por qué.
6. Por input: valor base = mediana de las firmas; bajo/alto = el rango que
   cubren. Se guarda en ``declared_input_values`` con ``method='analyst'``
   (estado «estimado»), la firma, la URL y la cita de la mejor firma, y en
   ``metadata`` el método «mezcla de analistas» con cada firma, su valor y su
   cita. La precedencia del servicio impide pisar un dato oficial o manual.

Solo corre con ``EXPERT_TEAM_ENABLED``; apagado no hace nada ni llama al LLM.
No toca la tesis: el gancho en thesis_service es de la lane c2acb5b0
(``run_analyst_blend`` tras ``run_recopilador`` y antes de valorar).
"""

from __future__ import annotations

import inspect
import json
import math
import re
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from statistics import median
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.llm.json import parse_json_response
from app.models.entities import Company, Document, DocumentChunk, NewsEvent
from app.services.analyst_history_service import AnalystHistory, FirmScore
from app.services.declared_input_service import (
    DeclaredInput,
    DeclaredInputError,
    DeclaredInputService,
    InputGap,
)
from app.services.expert_team.experts import ExpertSpec, Reasoner, gather_evidence
from app.services.expert_team.ledger import EvidenceLedger
from app.services.expert_team.models import RunContext, ToolOutput, ToolSpec
from app.valuation.dividend_equity import STAGE2_GROWTH_CEILING

BLEND_NAME = "mezcla_analistas"
#: Nombre del método tal y como lo ve el usuario («de analista X, estimado»).
BLEND_METHOD_LABEL = "mezcla de analistas"
BLEND_TOOLS: tuple[str, ...] = ("analyst_passages",)
MAX_ATTEMPTS = 2
MAX_ASSUMPTIONS = 120
#: SPEC §6.6: solo firmas que baten a sus pares con n ≥ 4 objetivos comparados.
MIN_PEER_SCORED_SAMPLES = 4
#: Evidencia: documentos recientes revisados, pasajes por documento y ventana de noticias.
DOC_MAX_DOCUMENTS = 40
DOC_MAX_PASSAGES_PER_DOC = 4
DOC_PASSAGE_CHARS = 1500
NEWS_WINDOW_DAYS = 365
NEWS_MAX = 60
#: Crecimiento perpetuo máximo: el PIB nominal a largo plazo (mismo techo que el DDM).
PERPETUAL_GROWTH_CEILING = STAGE2_GROWTH_CEILING
#: Último componente de la clave que indica un crecimiento perpetuo.
PERPETUAL_GROWTH_KEYS: frozenset[str] = frozenset(
    {"terminal_growth", "perpetual_growth", "long_term_growth", "terminal_growth_rate"}
)
#: Último componente de la clave que indica la reposición de activos con vida finita.
REPLACEMENT_KEYS: frozenset[str] = frozenset(
    {"replacement_capex", "maintenance_capex", "maintenance_capex_pct", "replacement_rate", "life_years"}
)
ANALYST_FIRM_MAX_CHARS = 160

BLEND_CONTRACT = (
    'Responde SOLO con JSON: {"assumptions": [{"input_key": str (uno de los huecos), "segment_key": '
    'str ("" = empresa entera), "firm": str (una de las firmas dadas), "value": numero, "low": '
    'numero|null, "high": numero|null, "unit": str (la del hueco; tasas en decimal, 5 % = 0.05), '
    '"citations": ["ev-N"], "source_url": str, "source_quote": str (literal, copiada de la '
    'evidencia citada), "as_of": "AAAA-MM-DD"|null}]}. Un supuesto por firma e input, solo si la '
    "firma lo publica en la evidencia citada; la URL es la de esa evidencia y la cita está copiada "
    "de ella palabra por palabra. Si una firma no da cifra para un input, no lo pongas. No inventes "
    "ni promedies tú: la mezcla la hace el código. Lista vacía si no hay nada."
)

#: Fuente extra de evidencia (p. ej. las notas de analista de #4582): recibe el
#: contexto y las firmas que cuentan; devuelve salidas citables.
ExtraSource = Callable[[RunContext, Sequence[str]], Any]
HistoryLoader = Callable[[str], Awaitable[AnalystHistory]]


@dataclass(frozen=True)
class AnalystAssumption:
    """El supuesto que una firma publica para un input, con su cita verificada."""

    input_key: str
    segment_key: str
    firm: str
    value: float
    unit: str
    low: float | None = None
    high: float | None = None
    source_url: str | None = None
    source_quote: str | None = None
    document_id: int | None = None
    as_of: date | None = None
    citations: tuple[str, ...] = ()


@dataclass
class AnalystBlendResult:
    """Qué hizo la mezcla de analistas en una corrida."""

    # disabled | no_company | full_data | no_firms | no_data | no_assumptions | stored | rejected | error
    status: str
    stored: int = 0
    unchanged: int = 0
    kept: int = 0
    inputs: list[DeclaredInput] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    firms: list[str] = field(default_factory=list)
    discarded: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    llm_calls: int = 0
    prompt_version: str | None = None
    tool_errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "stored": self.stored,
            "unchanged": self.unchanged,
            "kept": self.kept,
            "inputs": [
                f"{i.input_key}@{i.segment_key}" if i.segment_key else i.input_key for i in self.inputs
            ],
            "gaps": list(self.gaps),
            "firms": list(self.firms),
            "discarded": list(self.discarded),
            "problems": list(self.problems),
            "llm_calls": self.llm_calls,
            "prompt_version": self.prompt_version,
            "tool_errors": list(self.tool_errors),
        }


def _fold(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().casefold()


def _last(key: str) -> str:
    return key.rsplit(".", 1)[-1]


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _as_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return date.fromisoformat(value.strip()[:10])
        except ValueError:
            return None
    return None


# ---------------------------------------------------------------------------
# Firmas que cuentan (pura)
# ---------------------------------------------------------------------------


def qualifying_firms(history: AnalystHistory | None) -> list[FirmScore]:
    """Firmas del mejor horizonte que baten a sus pares con muestra suficiente, de mejor a peor."""
    if history is None or history.status != "available" or history.best_horizon is None:
        return []
    summary = next((h for h in history.horizons if h.horizon == history.best_horizon), None)
    if summary is None:
        return []
    firms = [
        f
        for f in summary.top
        if not f.small_sample
        and f.relative_error is not None
        and f.relative_error < 0
        and f.peer_scored_samples >= MIN_PEER_SCORED_SAMPLES
    ]
    return sorted(firms, key=lambda f: (f.relative_error if f.relative_error is not None else 0.0, f.firm))


# ---------------------------------------------------------------------------
# Evidencia
# ---------------------------------------------------------------------------


def _mentions(text: str, folded_firms: Sequence[str]) -> bool:
    folded = _fold(text)
    return any(firm and firm in folded for firm in folded_firms)


def analyst_passages_tool(
    db: Session,
    firms: Sequence[str],
    *,
    extra_sources: Sequence[ExtraSource] = (),
    today: date | None = None,
) -> ToolSpec:
    """Pasajes de documentos y noticias del tenant que nombran a las firmas que cuentan."""
    folded_firms = [_fold(f) for f in firms if _fold(f)]

    async def analyst_passages(ctx: RunContext) -> list[ToolOutput]:
        out: list[ToolOutput] = []
        if not ctx.ticker or not folded_firms:
            return out
        company = db.scalars(select(Company).where(Company.ticker == ctx.ticker)).first()
        if company is None:
            return out
        docs = db.scalars(
            select(Document)
            .where(
                Document.tenant_id == ctx.tenant_id,
                Document.company_id == company.id,
                Document.retention_tombstoned_at.is_(None),
            )
            .order_by(Document.published_at.desc().nullslast(), Document.id.desc())
            .limit(DOC_MAX_DOCUMENTS)
        ).all()
        for doc in docs:
            chunks = db.scalars(
                select(DocumentChunk)
                .where(DocumentChunk.tenant_id == ctx.tenant_id, DocumentChunk.document_id == doc.id)
                .order_by(DocumentChunk.chunk_index)
            ).all()
            hits = [c for c in chunks if _mentions(c.text or "", folded_firms)]
            for chunk in hits[:DOC_MAX_PASSAGES_PER_DOC]:
                out.append(
                    ToolOutput(
                        source={
                            "table": "document_chunks",
                            "document_id": str(doc.id),
                            "title": doc.title or "",
                            "source_type": doc.source_type or "",
                            "url": doc.source_url or "",
                            "date": doc.published_at.date().isoformat() if doc.published_at else "",
                        },
                        data={"text": (chunk.text or "")[:DOC_PASSAGE_CHARS]},
                    )
                )
        since = (today or date.today()) - timedelta(days=NEWS_WINDOW_DAYS)
        news = db.scalars(
            select(NewsEvent)
            .where(
                NewsEvent.tenant_id == ctx.tenant_id,
                NewsEvent.company_id == company.id,
                NewsEvent.date >= since,
            )
            .order_by(NewsEvent.date.desc(), NewsEvent.id.desc())
            .limit(NEWS_MAX * 4)
        ).all()
        kept = 0
        for n in news:
            text = f"{n.title or ''} {n.summary or ''}"
            if not _mentions(text, folded_firms):
                continue
            out.append(
                ToolOutput(
                    source={
                        "table": "news_events",
                        "id": str(n.id),
                        "source": n.source or "",
                        "url": n.url or "",
                        "date": n.date.isoformat() if n.date else "",
                    },
                    data={"title": n.title or "", "text": (n.summary or "")[:DOC_PASSAGE_CHARS]},
                )
            )
            kept += 1
            if kept >= NEWS_MAX:
                break
        for source in extra_sources:
            extra = source(ctx, list(firms))
            if inspect.isawaitable(extra):
                extra = await extra
            out.extend(e for e in extra or () if isinstance(e, ToolOutput))
        return out

    return ToolSpec(
        name="analyst_passages",
        fn=analyst_passages,
        description="Pasajes de notas, documentos y noticias que nombran a las firmas mejor puntuadas.",
    )


# ---------------------------------------------------------------------------
# Validación de la salida del modelo (fail-closed)
# ---------------------------------------------------------------------------


def parse_assumptions(
    parsed: Any,
    ledger: EvidenceLedger,
    *,
    gaps: Sequence[InputGap],
    firms: Sequence[str],
    expert: str = BLEND_NAME,
) -> tuple[list[AnalystAssumption], list[str]]:
    """JSON del modelo → supuestos verificados, o la lista de problemas (uno invalida todo)."""
    if not isinstance(parsed, dict) or not isinstance(parsed.get("assumptions"), list):
        return [], ["el JSON no trae la lista «assumptions»"]
    raw_items = parsed["assumptions"]
    if len(raw_items) > MAX_ASSUMPTIONS:
        return [], [f"más de {MAX_ASSUMPTIONS} supuestos"]
    gap_keys = {(g.key, g.segment_key or "") for g in gaps}
    firm_by_fold = {_fold(f): f for f in firms}
    service = DeclaredInputService()
    problems: list[str] = []
    out: list[AnalystAssumption] = []
    seen: set[tuple[str, str, str]] = set()
    for index, raw in enumerate(raw_items):
        if not isinstance(raw, dict):
            problems.append(f"#{index + 1}: no es un objeto")
            continue
        key = str(raw.get("input_key") or "").strip()
        segment = str(raw.get("segment_key") or "").strip()
        label = f"{key or '#' + str(index + 1)}/{raw.get('firm') or '?'}"
        if (key, segment) not in gap_keys:
            problems.append(f"{label}: el input no es un hueco del modelo (no se pisan datos propios)")
            continue
        firm = firm_by_fold.get(_fold(raw.get("firm")))
        if firm is None:
            problems.append(f"{label}: la firma no está entre las mejor puntuadas")
            continue
        citations = [c for c in raw.get("citations") or () if isinstance(c, str)]
        cited = [ledger.get(c) for c in citations]
        cited = [e for e in cited if e is not None and e.expert == expert]
        if not citations or len(cited) != len(citations):
            problems.append(f"{label}: no cita evidencia de esta corrida")
            continue
        url = str(raw.get("source_url") or "").strip()
        urls = {str(e.source.get("url") or "").strip() for e in cited} - {""}
        if not url or url not in urls:
            problems.append(f"{label}: la URL no es la de la evidencia citada")
        corpus = " ".join(_fold(json.dumps(e.data, ensure_ascii=False, default=str)) for e in cited)
        corpus += " " + " ".join(_fold(e.data.get("text")) for e in cited if isinstance(e.data, dict))
        corpus += " " + " ".join(_fold(e.data.get("title")) for e in cited if isinstance(e.data, dict))
        quote = _fold(raw.get("source_quote"))
        if not quote or quote not in corpus:
            problems.append(f"{label}: la cita no aparece literal en la evidencia citada")
        if _fold(firm) not in corpus:
            problems.append(f"{label}: la firma no aparece en la evidencia citada")
        value = _number(raw.get("value"))
        low = _number(raw.get("low")) if raw.get("low") is not None else None
        high = _number(raw.get("high")) if raw.get("high") is not None else None
        if value is None:
            problems.append(f"{label}: el valor no es un número")
            continue
        if (raw.get("low") is not None and low is None) or (raw.get("high") is not None and high is None):
            problems.append(f"{label}: bajo/alto no son números")
            continue
        if (key, segment, firm) in seen:
            problems.append(f"{label}: supuesto repetido para la misma firma")
        seen.add((key, segment, firm))
        unit = str(raw.get("unit") or "").strip()
        document_ids = [
            int(e.source["document_id"]) for e in cited if str(e.source.get("document_id", "")).isdigit()
        ]
        assumption = AnalystAssumption(
            input_key=key,
            segment_key=segment,
            firm=firm,
            value=value,
            unit=unit,
            low=low,
            high=high,
            source_url=url or None,
            source_quote=str(raw.get("source_quote") or "").strip() or None,
            document_id=document_ids[0] if document_ids else None,
            as_of=_as_date(raw.get("as_of")),
            citations=tuple(citations),
        )
        # Mismas reglas de unidad, límites y fuente que cualquier input declarado.
        problems.extend(f"{label}: {p}" for p in service.validate(_single_input(assumption)))
        out.append(assumption)
    if problems:
        return [], problems
    return out, []


def _single_input(a: AnalystAssumption) -> DeclaredInput:
    return DeclaredInput(
        input_key=a.input_key,
        segment_key=a.segment_key,
        base=a.value,
        low=a.low,
        high=a.high,
        unit=a.unit,
        method="analyst",
        source_url=a.source_url,
        source_quote=a.source_quote,
        document_id=a.document_id,
        analyst_firm=a.firm,
        as_of=a.as_of,
    )


def economic_limit_violation(a: AnalystAssumption) -> str | None:
    """Motivo si el supuesto viola un límite económico; None si es admisible."""
    last = _last(a.input_key)
    if last in PERPETUAL_GROWTH_KEYS and a.value > PERPETUAL_GROWTH_CEILING:
        return (
            f"crecimiento perpetuo {a.value:.1%} por encima del PIB nominal a largo plazo "
            f"({PERPETUAL_GROWTH_CEILING:.0%})"
        )
    if last in REPLACEMENT_KEYS and a.value <= 0:
        return "supone no reponer activos con vida finita"
    return None


# ---------------------------------------------------------------------------
# Mezcla (pura)
# ---------------------------------------------------------------------------


def blend_assumptions(
    assumptions: Iterable[AnalystAssumption], firms: Sequence[str]
) -> tuple[list[DeclaredInput], list[str]]:
    """Por input: mediana de las firmas como base y el rango que cubren como bajo/alto.

    Devuelve los inputs listos para guardar y las notas de lo que no se mezcló.
    """
    rank = {f: i for i, f in enumerate(firms)}
    groups: dict[tuple[str, str], list[AnalystAssumption]] = {}
    for a in assumptions:
        groups.setdefault((a.input_key, a.segment_key), []).append(a)
    inputs: list[DeclaredInput] = []
    notes: list[str] = []
    for (key, segment), items in sorted(groups.items()):
        items = sorted(items, key=lambda a: rank.get(a.firm, len(rank)))
        units = {a.unit for a in items}
        if len(units) != 1:
            notes.append(
                f"{key}: las firmas dan unidades distintas ({', '.join(sorted(units))}); no se mezcla"
            )
            continue
        values = [a.value for a in items]
        base = float(median(values))
        lows = values + [a.low for a in items if a.low is not None]
        highs = values + [a.high for a in items if a.high is not None]
        best = items[0]
        names = ", ".join(a.firm for a in items)
        if len(names) > ANALYST_FIRM_MAX_CHARS:
            names = names[: ANALYST_FIRM_MAX_CHARS - 1] + "…"
        inputs.append(
            DeclaredInput(
                input_key=key,
                segment_key=segment,
                base=base,
                low=min(lows),
                high=max(highs),
                unit=best.unit,
                method="analyst",
                source_url=best.source_url,
                source_quote=best.source_quote,
                document_id=best.document_id,
                analyst_firm=names,
                as_of=max((a.as_of for a in items if a.as_of is not None), default=None),
                metadata={
                    "metodo": BLEND_METHOD_LABEL,
                    "estado": "estimado",
                    "agregado": "mediana" if len(items) > 1 else "una firma",
                    "expert": BLEND_NAME,
                    "firmas": [
                        {
                            "firma": a.firm,
                            "valor": a.value,
                            "bajo": a.low,
                            "alto": a.high,
                            "fuente": a.source_url,
                            "cita": a.source_quote,
                            "fecha": a.as_of.isoformat() if a.as_of else None,
                        }
                        for a in items
                    ],
                },
            )
        )
    return inputs, notes


# ---------------------------------------------------------------------------
# Etapa
# ---------------------------------------------------------------------------


async def _default_history(symbol: str) -> AnalystHistory:
    from app.services.analyst_history_service import analyst_history_service

    return await analyst_history_service.get(symbol)


async def run_analyst_blend(
    db: Session,
    *,
    ctx: RunContext,
    reasoner: Reasoner,
    history: AnalystHistory | None = None,
    load_history: HistoryLoader | None = None,
    extra_sources: Sequence[ExtraSource] = (),
    spec: ExpertSpec | None = None,
    tools: Mapping[str, ToolSpec] | None = None,
    extra_inputs: Iterable[str] = (),
    enabled: bool | None = None,
) -> AnalystBlendResult:
    """Rellena los huecos del modelo de ``ctx.ticker`` con la mezcla de las mejores firmas.

    ``enabled`` None = ``EXPERT_TEAM_ENABLED``. Apagado: no llama al LLM ni escribe.
    Una empresa sin huecos (datos completos) sale con ``full_data`` sin tocar nada.
    """
    from app.core.config import get_settings
    from app.services.expert_team.roster import analyst_blend_expert
    from app.services.prompt_registry import get_prompt

    if enabled is None:
        enabled = bool(get_settings().expert_team_enabled)
    if not enabled:
        return AnalystBlendResult(status="disabled")
    if type(ctx.tenant_id) is not int or not ctx.ticker:
        return AnalystBlendResult(status="no_company", problems=["hace falta tenant y empresa"])
    company = db.scalars(select(Company).where(Company.ticker == ctx.ticker)).first()
    if company is None:
        return AnalystBlendResult(status="no_company")
    service = DeclaredInputService()
    try:
        report = service.detect_gaps(db, company=company, tenant_id=ctx.tenant_id, extra_inputs=extra_inputs)
    except DeclaredInputError as exc:
        return AnalystBlendResult(status="error", problems=exc.problems)
    gaps = list(report.gaps)
    result = AnalystBlendResult(status="full_data", gaps=[g.key for g in gaps])
    if not gaps:
        return result
    if history is None:
        try:
            history = await (load_history or _default_history)(ctx.ticker)
        except Exception as exc:  # sin historial no hay a quién hacer caso
            result.status = "no_firms"
            result.problems = [f"historial:{type(exc).__name__}"]
            return result
    firms = [f.firm for f in qualifying_firms(history)]
    result.firms = firms
    if not firms:
        result.status = "no_firms"
        return result
    spec = spec or analyst_blend_expert()
    tools = (
        tools
        if tools is not None
        else {"analyst_passages": analyst_passages_tool(db, firms, extra_sources=extra_sources)}
    )
    ledger = EvidenceLedger()
    evidence, tool_errors = await gather_evidence(spec, ctx, tools, ledger)
    prompt = get_prompt(spec.prompt_name, lang="es")
    result.prompt_version = prompt.version
    result.tool_errors = tool_errors
    if not evidence:
        result.status = "no_data"
        return result
    system = f"{prompt.text}\n\n{BLEND_CONTRACT}"
    payload: dict[str, Any] = {
        "ticker": ctx.ticker,
        "company": company.name,
        "gaps": [g.as_dict() for g in gaps],
        "firms": [
            {"firm": f.firm, "relative_error": f.relative_error, "samples": f.peer_scored_samples}
            for f in qualifying_firms(history)
        ],
        "evidence": evidence,
    }
    assumptions: list[AnalystAssumption] = []
    for _ in range(MAX_ATTEMPTS):
        result.llm_calls += 1
        try:
            text = await reasoner(
                system,
                json.dumps(payload, ensure_ascii=False, default=str),
                spec.max_tokens,
                f"expert_team.{spec.name}",
            )
        except Exception as exc:  # sin LLM o sin presupuesto: no se escribe nada
            result.status = "error"
            result.problems = [f"llm:{type(exc).__name__}"]
            return result
        try:
            parsed = parse_json_response(text)
        except Exception:
            parsed = None
        assumptions, problems = parse_assumptions(parsed, ledger, gaps=gaps, firms=firms, expert=spec.name)
        if not problems:
            break
        result.problems = problems
        payload["problems_previous_answer"] = problems[:20]
    else:
        result.status = "rejected"
        return result
    result.problems = []
    admissible: list[AnalystAssumption] = []
    for a in assumptions:
        reason = economic_limit_violation(a)
        if reason is None:
            admissible.append(a)
        else:
            result.discarded.append(f"{a.input_key} ({a.firm}): {reason}")
    inputs, notes = blend_assumptions(admissible, firms)
    result.discarded.extend(notes)
    if not inputs:
        result.status = "no_assumptions"
        return result
    # Todo validado antes de escribir: o entra la mezcla entera o nada.
    problems = [f"{i.input_key}: {p}" for i in inputs for p in service.validate(i)]
    if problems:
        result.status = "rejected"
        result.problems = problems
        return result
    for item in inputs:
        outcome = service.upsert(db, company=company, tenant_id=ctx.tenant_id, item=item)
        if outcome.reason == "kept_higher_precedence":
            result.kept += 1
        elif outcome.changed:
            result.stored += 1
        else:
            result.unchanged += 1
    result.inputs = inputs
    result.status = "stored"
    return result


__all__ = [
    "BLEND_CONTRACT",
    "BLEND_METHOD_LABEL",
    "BLEND_NAME",
    "BLEND_TOOLS",
    "MIN_PEER_SCORED_SAMPLES",
    "PERPETUAL_GROWTH_CEILING",
    "AnalystAssumption",
    "AnalystBlendResult",
    "analyst_passages_tool",
    "blend_assumptions",
    "economic_limit_violation",
    "parse_assumptions",
    "qualifying_firms",
    "run_analyst_blend",
]
