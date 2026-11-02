"""Un experto: recoge evidencia con su lista blanca y razona con 1 llamada LLM."""

from __future__ import annotations

import inspect
import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from app.llm.json import parse_json_response
from app.services.expert_team.ledger import EvidenceLedger
from app.services.expert_team.models import Claim, ExpertReport, RunContext, ToolOutput, ToolSpec

#: ``(system, user, max_tokens, task) -> texto``. Inyectable: los tests usan uno falso.
Reasoner = Callable[[str, str, int, str], Awaitable[str]]
#: Devuelve "" si la afirmación es válida o el motivo del descarte.
Validator = Callable[[Claim, EvidenceLedger, "ExpertSpec"], str]

MAX_FORMAT_ATTEMPTS = 2
MAX_EVIDENCE_CHARS = 4000
_STANCES = {"positive", "negative", "neutral"}

OUTPUT_CONTRACT = {
    "es": (
        "Responde SOLO con JSON: {\"summary\": str, \"stance\": \"positive|negative|neutral\", "
        "\"claims\": [{\"text\": str, \"numbers\": [numero], \"metric\": str|null, "
        "\"citations\": [\"ev-N\"]}]}. Cada afirmación cita los ids de la evidencia de "
        "la que sale y cada número debe estar en esa evidencia. Sin evidencia, no hay afirmación."
    ),
    "en": (
        "Answer ONLY with JSON: {\"summary\": str, \"stance\": \"positive|negative|neutral\", "
        "\"claims\": [{\"text\": str, \"numbers\": [number], \"metric\": str|null, "
        "\"citations\": [\"ev-N\"]}]}. Every claim cites the evidence ids it comes from and "
        "every number must appear in that evidence. No evidence, no claim."
    ),
}


@dataclass(frozen=True)
class ExpertSpec:
    name: str
    prompt_name: str
    tools: tuple[str, ...]
    timeout_s: float = 45.0
    max_tokens: int = 900
    modes: frozenset[str] = field(default_factory=lambda: frozenset({"thesis", "chat"}))
    #: Palabras (sin tildes, minúsculas) que activan al experto en el chat.
    keywords: tuple[str, ...] = ()
    #: Condición extra del plan (p. ej. fiscal solo con posición).
    applies: Callable[[RunContext], bool] | None = None
    #: Entra también en preguntas amplias del chat («¿merece la pena X?»).
    broad: bool = False


def basic_citation_check(claim: Claim, ledger: EvidenceLedger, spec: ExpertSpec) -> str:
    """Una cita vale si apunta a evidencia de ESTA corrida recogida por ESTE experto."""
    if not claim.citations:
        return "uncited"
    for cid in claim.citations:
        evidence = ledger.get(cid)
        if evidence is None:
            return "unknown_citation"
        if evidence.expert != spec.name or evidence.tool not in spec.tools:
            return "foreign_citation"
    return ""


async def gather_evidence(
    spec: ExpertSpec, ctx: RunContext, tools: Mapping[str, ToolSpec], ledger: EvidenceLedger
) -> tuple[list[dict[str, Any]], list[str]]:
    evidence: list[dict[str, Any]] = []
    errors: list[str] = []
    for name in spec.tools:
        try:
            out = tools[name].fn(ctx)
            if inspect.isawaitable(out):
                out = await out
        except Exception as exc:  # una herramienta rota no tumba al experto
            errors.append(f"{name}:{type(exc).__name__}")
            continue
        for one in out if isinstance(out, list) else [out]:
            if not isinstance(one, ToolOutput):
                continue
            item = ledger.add(expert=spec.name, tool=name, source=one.source, data=one.data)
            data: Any = item.data
            raw = json.dumps(data, ensure_ascii=False, default=str)
            if len(raw) > MAX_EVIDENCE_CHARS:
                data = raw[:MAX_EVIDENCE_CHARS] + "…"
            evidence.append({"id": item.id, "tool": name, "source": dict(item.source), "data": data})
    return evidence, errors


def _parse_claims(raw: Any) -> list[Claim]:
    claims: list[Claim] = []
    for entry in raw if isinstance(raw, list) else []:
        if not isinstance(entry, dict) or not str(entry.get("text") or "").strip():
            continue
        numbers = tuple(
            float(n) for n in entry.get("numbers") or () if isinstance(n, int | float) and not isinstance(n, bool)
        )
        citations = tuple(str(c) for c in entry.get("citations") or () if isinstance(c, str))
        metric = entry.get("metric")
        claims.append(
            Claim(
                text=str(entry["text"]).strip(),
                numbers=numbers,
                citations=citations,
                metric=str(metric) if isinstance(metric, str) and metric else None,
            )
        )
    return claims


def _checked_summary(
    summary: str, evidence: list[dict[str, Any]], ledger: EvidenceLedger, spec: ExpertSpec, validator: Validator
) -> str:
    """El resumen se pinta junto a las afirmaciones: sus cifras deben salir de la
    evidencia de ESTE experto, igual que las de una afirmación. Si alguna no
    sale, el resumen se quita (las afirmaciones validadas siguen)."""
    if not summary or not evidence:
        return summary
    probe = Claim(text=summary, citations=tuple(ev["id"] for ev in evidence))
    reason = validator(probe, ledger, spec)
    return "" if reason else summary


async def run_expert(
    spec: ExpertSpec,
    ctx: RunContext,
    *,
    tools: Mapping[str, ToolSpec],
    ledger: EvidenceLedger,
    reasoner: Reasoner,
    validator: Validator,
) -> ExpertReport:
    from app.services.prompt_registry import get_prompt

    evidence, tool_errors = await gather_evidence(spec, ctx, tools, ledger)
    prompt = get_prompt(spec.prompt_name, lang=ctx.lang)
    report = ExpertReport(
        expert=spec.name, status="no_data", prompt_version=prompt.version, tool_errors=tool_errors
    )
    if not evidence:
        return report
    lang = "en" if prompt.lang == "en" else "es"
    system = f"{prompt.text}\n\n{OUTPUT_CONTRACT[lang]}"
    user = json.dumps(
        {"ticker": ctx.ticker, "question": ctx.question, "mode": ctx.mode, "evidence": evidence},
        ensure_ascii=False,
        default=str,
    )
    parsed: Any = None
    for _ in range(MAX_FORMAT_ATTEMPTS):
        report.llm_calls += 1
        text = await reasoner(system, user, spec.max_tokens, f"expert_team.{spec.name}")
        try:
            parsed = parse_json_response(text)
        except Exception:
            parsed = None
        if isinstance(parsed, dict):
            break
    if not isinstance(parsed, dict):
        report.status = "error"
        report.error = "invalid_json"
        return report
    stance = str(parsed.get("stance") or "neutral").lower()
    report.stance = stance if stance in _STANCES else "neutral"  # type: ignore[assignment]
    report.summary = _checked_summary(str(parsed.get("summary") or "").strip(), evidence, ledger, spec, validator)
    for claim in _parse_claims(parsed.get("claims")):
        claim.reason = validator(claim, ledger, spec)
        # Motivo con prefijo «mark:» = se conserva marcada como «sin fuente».
        kept = not claim.reason or claim.reason.startswith("mark:")
        (report.claims if kept else report.dropped).append(claim)
    report.status = "ok"
    return report
