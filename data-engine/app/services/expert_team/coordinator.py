"""Coordinador: plan -> expertos en paralelo acotado -> fusión -> contradicciones."""

from __future__ import annotations

import asyncio
import contextlib
import re
import unicodedata
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any

from app.llm import run_guard
from app.services.expert_team.citations import citation_validator
from app.services.expert_team.experts import ExpertSpec, Reasoner, Validator, run_expert
from app.services.expert_team.ledger import EvidenceLedger
from app.services.expert_team.models import ExpertReport, RunContext, TeamResult, ToolSpec

#: Diferencia relativa a partir de la cual dos valores de la misma métrica chocan.
METRIC_CONFLICT_TOLERANCE = 0.02
_JUDGE_LABELS = {"bullish": "positive", "bearish": "negative", "neutral": "neutral"}

Judge = Callable[[RunContext, str, str], Awaitable[str]]


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


class ExpertTeam:
    def __init__(
        self,
        experts: Sequence[ExpertSpec],
        tools: Mapping[str, ToolSpec],
        reasoner: Reasoner,
        *,
        max_parallel: int = 3,
        total_timeout_s: float = 120.0,
        validator: Validator | None = None,
        guard: run_guard.LLMRunGuard | None = None,
        judge_prompt: str = "thesis_debate_judge",
    ) -> None:
        for spec in experts:
            missing = [t for t in spec.tools if t not in tools]
            if missing:
                raise ValueError(f"expert {spec.name}: unknown tool(s) {missing}")
        if max_parallel < 1:
            raise ValueError("max_parallel must be >= 1")
        self.experts = list(experts)
        self.tools = dict(tools)
        self.reasoner = reasoner
        self.max_parallel = max_parallel
        self.total_timeout_s = total_timeout_s
        self.validator = validator or citation_validator()
        self.guard = guard
        self.judge_prompt = judge_prompt

    def plan(self, ctx: RunContext) -> list[str]:
        """Determinista: tesis = todos los aplicables; chat = por palabras clave."""
        chosen: list[str] = []
        question = _fold(ctx.question or "")
        for spec in self.experts:
            if ctx.mode not in spec.modes:
                continue
            if spec.applies is not None and not spec.applies(ctx):
                continue
            if ctx.mode == "chat" and not any(re.search(rf"\b{re.escape(k)}", question) for k in spec.keywords):
                continue
            chosen.append(spec.name)
        return chosen

    async def _one(self, spec: ExpertSpec, ctx: RunContext, ledger: EvidenceLedger, sem: asyncio.Semaphore):
        async with sem:
            try:
                return await asyncio.wait_for(
                    run_expert(
                        spec, ctx, tools=self.tools, ledger=ledger, reasoner=self.reasoner, validator=self.validator
                    ),
                    timeout=spec.timeout_s,
                )
            except TimeoutError:
                return ExpertReport(expert=spec.name, status="timeout")
            except run_guard.LLMGuardAbort as exc:
                return ExpertReport(expert=spec.name, status="error", error=str(exc))
            except Exception as exc:
                return ExpertReport(expert=spec.name, status="error", error=type(exc).__name__)

    async def run(self, ctx: RunContext) -> TeamResult:
        plan = self.plan(ctx)
        specs = [s for s in self.experts if s.name in plan]
        ledger = EvidenceLedger()
        sem = asyncio.Semaphore(self.max_parallel)
        activation = run_guard.activate(self.guard) if self.guard is not None else contextlib.nullcontext()
        with activation:
            tasks = [asyncio.create_task(self._one(s, ctx, ledger, sem)) for s in specs]
            done, pending = await asyncio.wait(tasks, timeout=self.total_timeout_s) if tasks else (set(), set())
            for task in pending:
                task.cancel()
            reports = [
                t.result() if t in done else ExpertReport(expert=s.name, status="timeout")
                for s, t in zip(specs, tasks, strict=True)
            ]
            result = TeamResult(context=ctx, plan=plan, reports=reports)
            result.sources = self._sources(reports, ledger)
            result.conflicts = self._metric_conflicts(reports)
            stance = self._stance_conflict(reports)
            if stance is not None:
                result.conflicts.append(stance)
                result.verdict = await self._judge(ctx, stance, reports)
        return result

    @staticmethod
    def _sources(reports: list[ExpertReport], ledger: EvidenceLedger) -> list[dict[str, Any]]:
        seen: dict[str, dict[str, Any]] = {}
        for report in reports:
            for claim in report.claims:
                if claim.reason:  # marcada «sin fuente»: no aporta fuentes
                    continue
                for cid in claim.citations:
                    evidence = ledger.get(cid)
                    if evidence is not None and cid not in seen:
                        seen[cid] = {"id": cid, "tool": evidence.tool, "expert": evidence.expert, **evidence.source}
        return list(seen.values())

    @staticmethod
    def _metric_conflicts(reports: list[ExpertReport]) -> list[dict[str, Any]]:
        by_metric: dict[str, list[dict[str, Any]]] = {}
        for report in reports:
            for claim in report.claims:
                if claim.metric and claim.numbers:
                    by_metric.setdefault(claim.metric, []).append(
                        {"expert": report.expert, "value": claim.numbers[0], "citations": list(claim.citations)}
                    )
        conflicts = []
        for metric, values in by_metric.items():
            nums = [v["value"] for v in values]
            low, high = min(nums), max(nums)
            if len({v["expert"] for v in values}) > 1 and high - low > METRIC_CONFLICT_TOLERANCE * max(
                abs(high), abs(low), 1e-9
            ):
                conflicts.append({"type": "metric", "metric": metric, "values": values})
        return conflicts

    @staticmethod
    def _stance_conflict(reports: list[ExpertReport]) -> dict[str, Any] | None:
        ok = [r for r in reports if r.status == "ok" and r.claims]
        positive = [r.expert for r in ok if r.stance == "positive"]
        negative = [r.expert for r in ok if r.stance == "negative"]
        if positive and negative:
            return {"type": "stance", "positive": positive, "negative": negative}
        return None

    async def _judge(
        self, ctx: RunContext, conflict: dict[str, Any], reports: list[ExpertReport]
    ) -> dict[str, str]:
        """Reutiliza el prompt del juez del debate con SOLO afirmaciones validadas."""
        from app.services.prompt_registry import get_prompt

        def case(names: list[str]) -> str:
            return "\n".join(f"- [{r.expert}] {c.text}" for r in reports if r.expert in names for c in r.claims)

        user = (
            f"Ticker: {ctx.ticker or '-'}\nCASO A FAVOR:\n{case(conflict['positive'])}\n"
            f"CASO EN CONTRA:\n{case(conflict['negative'])}"
        )
        try:
            prompt = get_prompt(self.judge_prompt, lang=ctx.lang)
            text = await self.reasoner(prompt.text, user, 200, "expert_team.judge")
        except Exception:
            return {"label": "neutral", "rationale": "", "source": "unresolved"}
        match = re.search(r"(bullish|bearish|neutral)\s*\|?\s*(.*)", text or "", re.IGNORECASE | re.DOTALL)
        if not match:
            return {"label": "neutral", "rationale": "", "source": "unresolved"}
        return {
            "label": _JUDGE_LABELS[match.group(1).lower()],
            "rationale": match.group(2).strip()[:600],
            "source": "judge",
        }
