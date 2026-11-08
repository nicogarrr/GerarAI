"""«Escéptico»: qué hace falta creer, impulsor a impulsor, y si lo compramos.

Feature aprobada por Nico (4-nov-2026, equipo de expertos: «un experto
escéptico que revise cada argumento»). Es la etapa del pipeline de la tesis
que va DESPUÉS del Recopilador (inventario de impulsores), de la mezcla de
analistas y del contraste con el consenso: lee el inventario con su puerta de
publicación (``publication_check``) y los argumentos de los analistas, y para
cada impulsor dice:

- «qué hace falta creer» para que ese impulsor dé lo que le atribuyen;
- su postura: «aceptamos», «rechazamos» (con motivo) o «abierta» (con el dato
  que la cerraría), las mismas tres etiquetas que pide la conciliación con el
  consenso (gerarai-asts3/REPORT.md §8, regla 1);
- la cita literal de la evidencia en la que se apoya.

Fail-closed: cada juicio cita evidencia de esta corrida y su cita aparece
palabra por palabra; solo se juzgan impulsores del inventario; todo impulsor
que bloquea la publicación tiene que recibir juicio. Un problema invalida la
respuesta entera (un reintento con los problemas). No escribe nada en la base:
devuelve los juicios, y ``labels_for_reconciliation`` los convierte en
etiquetas de los pasos de ``consensus_sanity`` para los inputs que afectan.

Solo corre con ``EXPERT_TEAM_ENABLED``; apagado no hace nada ni llama al LLM.
El gancho en thesis_service es de la lane c2acb5b0 (tras la mezcla de
analistas y el contraste con el consenso).
"""

from __future__ import annotations

import inspect
import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.llm.json import parse_json_response
from app.models.declared_input_value import DeclaredInputValue
from app.models.entities import Company
from app.services.expert_team.experts import ExpertSpec, Reasoner, gather_evidence
from app.services.expert_team.ledger import EvidenceLedger
from app.services.expert_team.models import RunContext, ToolOutput, ToolSpec
from app.services.value_driver_service import PublicationCheck, ValueDriverService, as_item, publication_check
from app.valuation.consensus_sanity import StepLabel

ESCEPTICO_NAME = "esceptico"
ESCEPTICO_TOOLS: tuple[str, ...] = ("value_drivers", "analyst_arguments")
POSTURES: tuple[str, ...] = ("aceptamos", "rechazamos", "abierta")
MAX_ATTEMPTS = 2
MAX_BELIEFS = 80
MAX_TEXT = 600
QUOTE_CHARS = 1500

ESCEPTICO_CONTRACT = (
    'Responde SOLO con JSON: {"beliefs": [{"driver_key": str (uno del inventario), '
    '"hace_falta_creer": str (qué tiene que pasar para que el impulsor dé lo que le atribuyen), '
    '"postura": "aceptamos|rechazamos|abierta", "motivo": str (obligatorio si rechazamos), '
    '"dato_que_lo_cierra": str|null (obligatorio si abierta), "inputs": [str] (inputs del modelo '
    'a los que afecta, opcional), "citations": ["ev-N"], "source_quote": str (literal, copiada de '
    "la evidencia citada)}]}. Un juicio por impulsor; todos los que bloquean la publicación deben "
    "tener juicio. Sin evidencia no hay juicio; no inventes cifras."
)

ExtraSource = Callable[[RunContext, Sequence[str]], Any]


@dataclass(frozen=True)
class DriverBelief:
    """Juicio del escéptico sobre un impulsor."""

    driver_key: str
    must_believe: str
    posture: str
    reason: str = ""
    closing_data: str | None = None
    inputs: tuple[str, ...] = ()
    source_url: str | None = None
    source_quote: str | None = None
    citations: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "driver_key": self.driver_key,
            "hace_falta_creer": self.must_believe,
            "postura": self.posture,
            "motivo": self.reason,
            "dato_que_lo_cierra": self.closing_data,
            "inputs": list(self.inputs),
            "fuente": self.source_url,
            "cita": self.source_quote,
        }


@dataclass
class EscepticoResult:
    """Qué dijo el escéptico en una corrida."""

    status: str  # disabled | no_company | no_data | ok | rejected | error
    beliefs: list[DriverBelief] = field(default_factory=list)
    publication: PublicationCheck | None = None
    problems: list[str] = field(default_factory=list)
    llm_calls: int = 0
    prompt_version: str | None = None
    tool_errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "beliefs": [b.as_dict() for b in self.beliefs],
            "publication_check": self.publication.as_dict() if self.publication else None,
            "problems": list(self.problems),
            "llm_calls": self.llm_calls,
            "prompt_version": self.prompt_version,
            "tool_errors": list(self.tool_errors),
        }


def _fold(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().casefold()


def _company(db: Session, ctx: RunContext) -> Company | None:
    if not ctx.ticker:
        return None
    return db.scalars(select(Company).where(Company.ticker == ctx.ticker)).first()


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(v) for v in value]
    return value


# ---------------------------------------------------------------------------
# Herramientas de lectura
# ---------------------------------------------------------------------------


def value_drivers_tool(db: Session, *, market_cap_usd: float | Decimal | None = None) -> ToolSpec:
    """El inventario vigente del tenant, cada impulsor con si bloquea la publicación."""

    def value_drivers(ctx: RunContext) -> list[ToolOutput]:
        company = _company(db, ctx)
        if company is None or type(ctx.tenant_id) is not int:
            return []
        rows = ValueDriverService().current(db, company_id=company.id, tenant_id=ctx.tenant_id)
        check = publication_check(rows.values(), market_cap_usd=market_cap_usd)
        blocking = {b.driver_key for b in check.blocking}
        out: list[ToolOutput] = []
        for key in sorted(rows):
            item = as_item(rows[key])
            out.append(
                ToolOutput(
                    source={
                        "table": "value_drivers",
                        "driver_key": key,
                        "url": item.source_url or "",
                        "date": item.as_of.isoformat() if item.as_of else "",
                    },
                    data={
                        "driver_key": key,
                        "name": item.name,
                        "category": item.category,
                        "status": item.status,
                        "treatment": item.treatment,
                        "economics": _jsonable(item.economics),
                        "timing": item.timing,
                        "blocks_publication": key in blocking,
                        "text": (item.source_quote or "")[:QUOTE_CHARS],
                    },
                )
            )
        return out

    return ToolSpec(
        name="value_drivers", fn=value_drivers, description="Inventario de impulsores y su puerta."
    )


def analyst_arguments_tool(db: Session, *, extra_sources: Sequence[ExtraSource] = ()) -> ToolSpec:
    """Los argumentos de los analistas: cada firma de la mezcla con su cita, más fuentes extra."""

    async def analyst_arguments(ctx: RunContext) -> list[ToolOutput]:
        company = _company(db, ctx)
        if company is None or type(ctx.tenant_id) is not int:
            return []
        rows = db.scalars(
            select(DeclaredInputValue).where(
                DeclaredInputValue.tenant_id == ctx.tenant_id,
                DeclaredInputValue.company_id == company.id,
                DeclaredInputValue.method == "analyst",
                DeclaredInputValue.superseded_at.is_(None),
            )
        ).all()
        out: list[ToolOutput] = []
        firms: set[str] = set()
        for row in sorted(rows, key=lambda r: (r.input_key, r.segment_key or "")):
            entries = (row.metadata_ or {}).get("firmas") or []
            if not entries:
                entries = [
                    {
                        "firma": row.analyst_firm,
                        "valor": float(row.base),
                        "fuente": row.source_url,
                        "cita": row.source_quote,
                    }
                ]
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                firms.add(str(entry.get("firma") or ""))
                out.append(
                    ToolOutput(
                        source={
                            "table": "declared_input_values",
                            "input": row.input_key,
                            "firm": str(entry.get("firma") or ""),
                            "url": str(entry.get("fuente") or ""),
                        },
                        data={
                            "input": row.input_key,
                            "segment": row.segment_key or "",
                            "firm": entry.get("firma"),
                            "value": entry.get("valor"),
                            "unit": row.unit,
                            "text": str(entry.get("cita") or "")[:QUOTE_CHARS],
                        },
                    )
                )
        for source in extra_sources:
            extra = source(ctx, sorted(f for f in firms if f))
            if inspect.isawaitable(extra):
                extra = await extra
            out.extend(e for e in extra or () if isinstance(e, ToolOutput))
        return out

    return ToolSpec(
        name="analyst_arguments",
        fn=analyst_arguments,
        description="Supuestos y citas de las firmas mejor puntuadas.",
    )


def build_esceptico_tools(
    db: Session, *, market_cap_usd: float | Decimal | None = None, extra_sources: Sequence[ExtraSource] = ()
) -> dict[str, ToolSpec]:
    return {
        "value_drivers": value_drivers_tool(db, market_cap_usd=market_cap_usd),
        "analyst_arguments": analyst_arguments_tool(db, extra_sources=extra_sources),
    }


# ---------------------------------------------------------------------------
# Validación (fail-closed)
# ---------------------------------------------------------------------------


def _text(raw: Any) -> str:
    return str(raw).strip()[:MAX_TEXT] if isinstance(raw, str) else ""


def parse_beliefs(
    parsed: Any,
    ledger: EvidenceLedger,
    *,
    driver_keys: Sequence[str],
    blocking: Sequence[str] = (),
    expert: str = ESCEPTICO_NAME,
) -> tuple[list[DriverBelief], list[str]]:
    """JSON del modelo → juicios verificados, o la lista de problemas (uno invalida todo)."""
    if not isinstance(parsed, dict) or not isinstance(parsed.get("beliefs"), list):
        return [], ["el JSON no trae la lista «beliefs»"]
    raw_items = parsed["beliefs"]
    if len(raw_items) > MAX_BELIEFS:
        return [], [f"más de {MAX_BELIEFS} juicios"]
    known = set(driver_keys)
    problems: list[str] = []
    out: list[DriverBelief] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_items):
        if not isinstance(raw, dict):
            problems.append(f"#{index + 1}: no es un objeto")
            continue
        key = str(raw.get("driver_key") or "").strip()
        label = key or f"#{index + 1}"
        if key not in known:
            problems.append(f"{label}: no es un impulsor del inventario")
            continue
        if key in seen:
            problems.append(f"{label}: juicio repetido")
        seen.add(key)
        must = _text(raw.get("hace_falta_creer"))
        posture = str(raw.get("postura") or "").strip()
        reason = _text(raw.get("motivo"))
        closing = _text(raw.get("dato_que_lo_cierra")) or None
        if not must:
            problems.append(f"{label}: falta «qué hace falta creer»")
        if posture not in POSTURES:
            problems.append(f"{label}: postura no válida {posture!r}")
        if posture == "rechazamos" and not reason:
            problems.append(f"{label}: rechazar exige motivo")
        if posture == "abierta" and not closing:
            problems.append(f"{label}: una postura abierta exige el dato que la cierra")
        citations = [c for c in raw.get("citations") or () if isinstance(c, str)]
        cited = [ledger.get(c) for c in citations]
        cited = [e for e in cited if e is not None and e.expert == expert]
        if not citations or len(cited) != len(citations):
            problems.append(f"{label}: no cita evidencia de esta corrida")
            continue
        corpus = " ".join(_fold(json.dumps(e.data, ensure_ascii=False, default=str)) for e in cited)
        corpus += " " + " ".join(_fold(e.data.get("text")) for e in cited if isinstance(e.data, dict))
        quote = _fold(raw.get("source_quote"))
        if not quote or quote not in corpus:
            problems.append(f"{label}: la cita no aparece literal en la evidencia citada")
        urls = [str(e.source.get("url") or "") for e in cited if e.source.get("url")]
        inputs = tuple(str(i).strip() for i in raw.get("inputs") or () if isinstance(i, str) and i.strip())
        out.append(
            DriverBelief(
                driver_key=key,
                must_believe=must,
                posture=posture,
                reason=reason,
                closing_data=closing,
                inputs=inputs,
                source_url=urls[0] if urls else None,
                source_quote=str(raw.get("source_quote") or "").strip() or None,
                citations=tuple(citations),
            )
        )
    missing = sorted(set(blocking) - seen)
    if missing:
        problems.append("impulsores que bloquean la publicación sin juicio: " + ", ".join(missing))
    if problems:
        return [], problems
    return out, []


def labels_for_reconciliation(beliefs: Sequence[DriverBelief]) -> dict[str, StepLabel]:
    """Etiqueta de cada input del modelo según los juicios que lo citan.

    Si dos juicios no coinciden en un input, queda «abierta» (no se decide por mayoría).
    """
    grouped: dict[str, list[DriverBelief]] = {}
    for belief in beliefs:
        for key in belief.inputs:
            grouped.setdefault(key, []).append(belief)
    labels: dict[str, StepLabel] = {}
    for key, items in grouped.items():
        postures = {b.posture for b in items}
        if len(postures) == 1:
            first = items[0]
            posture = first.posture
            reason = first.reason if posture != "abierta" else (first.closing_data or first.reason)
            labels[key] = StepLabel(posture, reason or first.must_believe)
        else:
            keys = ", ".join(b.driver_key for b in items)
            labels[key] = StepLabel("abierta", f"juicios distintos sobre este input ({keys})")
    return labels


# ---------------------------------------------------------------------------
# Etapa
# ---------------------------------------------------------------------------


async def run_esceptico(
    db: Session,
    *,
    ctx: RunContext,
    reasoner: Reasoner,
    market_cap_usd: float | Decimal | None = None,
    extra_sources: Sequence[ExtraSource] = (),
    consensus_reconciliation: Mapping[str, Any] | None = None,
    spec: ExpertSpec | None = None,
    tools: Mapping[str, ToolSpec] | None = None,
    enabled: bool | None = None,
) -> EscepticoResult:
    """Corre el escéptico sobre el inventario de ``ctx.ticker`` (no escribe nada).

    ``enabled`` None = ``EXPERT_TEAM_ENABLED``. Apagado: no llama al LLM.
    ``consensus_reconciliation`` (opcional) es ``trace.consensus_reconciliation``
    para que el escéptico vea qué inputs explican la distancia al consenso.
    """
    from app.core.config import get_settings
    from app.services.expert_team.roster import esceptico_expert
    from app.services.prompt_registry import get_prompt

    if enabled is None:
        enabled = bool(get_settings().expert_team_enabled)
    if not enabled:
        return EscepticoResult(status="disabled")
    if type(ctx.tenant_id) is not int or not ctx.ticker:
        return EscepticoResult(status="no_company", problems=["hace falta tenant y empresa"])
    company = _company(db, ctx)
    if company is None:
        return EscepticoResult(status="no_company")
    rows = ValueDriverService().current(db, company_id=company.id, tenant_id=ctx.tenant_id)
    check = publication_check(rows.values(), market_cap_usd=market_cap_usd)
    result = EscepticoResult(status="no_data", publication=check)
    if not rows:
        return result
    spec = spec or esceptico_expert()
    tools = (
        tools
        if tools is not None
        else build_esceptico_tools(db, market_cap_usd=market_cap_usd, extra_sources=extra_sources)
    )
    ledger = EvidenceLedger()
    evidence, tool_errors = await gather_evidence(spec, ctx, tools, ledger)
    prompt = get_prompt(spec.prompt_name, lang="es")
    result.prompt_version = prompt.version
    result.tool_errors = tool_errors
    if not evidence:
        return result
    blocking = [b.driver_key for b in check.blocking]
    payload: dict[str, Any] = {
        "ticker": ctx.ticker,
        "company": company.name,
        "publication_check": check.as_dict(),
        "evidence": evidence,
    }
    if consensus_reconciliation:
        payload["consensus_reconciliation"] = dict(consensus_reconciliation)
    system = f"{prompt.text}\n\n{ESCEPTICO_CONTRACT}"
    beliefs: list[DriverBelief] = []
    for _ in range(MAX_ATTEMPTS):
        result.llm_calls += 1
        try:
            text = await reasoner(
                system,
                json.dumps(payload, ensure_ascii=False, default=str),
                spec.max_tokens,
                f"expert_team.{spec.name}",
            )
        except Exception as exc:  # sin LLM o sin presupuesto
            result.status = "error"
            result.problems = [f"llm:{type(exc).__name__}"]
            return result
        try:
            parsed = parse_json_response(text)
        except Exception:
            parsed = None
        beliefs, problems = parse_beliefs(
            parsed, ledger, driver_keys=sorted(rows), blocking=blocking, expert=spec.name
        )
        if not problems:
            break
        result.problems = problems
        payload["problems_previous_answer"] = problems[:20]
    else:
        result.status = "rejected"
        return result
    result.status = "ok"
    result.problems = []
    result.beliefs = beliefs
    return result


__all__ = [
    "ESCEPTICO_CONTRACT",
    "ESCEPTICO_NAME",
    "ESCEPTICO_TOOLS",
    "POSTURES",
    "DriverBelief",
    "EscepticoResult",
    "analyst_arguments_tool",
    "build_esceptico_tools",
    "labels_for_reconciliation",
    "parse_beliefs",
    "run_esceptico",
    "value_drivers_tool",
]
