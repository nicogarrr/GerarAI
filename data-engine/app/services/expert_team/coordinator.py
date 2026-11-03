"""Coordinador: plan -> expertos en paralelo acotado -> fusión -> contradicciones."""

from __future__ import annotations

import asyncio
import contextlib
import re
import unicodedata
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.llm import run_guard
from app.services.expert_team.citations import citation_validator, figures_supported
from app.services.expert_team.experts import ExpertSpec, Reasoner, Validator, gather_evidence, run_expert
from app.services.expert_team.ledger import EvidenceLedger
from app.services.expert_team.models import ExpertReport, RunContext, TeamResult, ToolSpec

#: Diferencia relativa a partir de la cual dos valores de la misma métrica chocan.
METRIC_CONFLICT_TOLERANCE = 0.02
_JUDGE_LABELS = {"bullish": "positive", "bearish": "negative", "neutral": "neutral"}

Judge = Callable[[RunContext, str, str], Awaitable[str]]


@dataclass
class _Gathered:
    """Evidencia ya recogida de un experto (o el informe de error/tope si falló)."""

    evidence: list[dict[str, Any]] = field(default_factory=list)
    tool_errors: list[str] = field(default_factory=list)
    elapsed_s: float = 0.0
    error: ExpertReport | None = None

#: Preguntas amplias sobre una empresa (texto ya sin tildes y en minúsculas):
#: «¿merece la pena X?», «¿debería comprar X?», «analiza X», «is X worth it?».
#: Las contestan los expertos marcados ``broad`` aunque no digan «riesgo» o
#: «valoración». Nada de cartera/cuenta: sin empresa el equipo no entra.
_BROAD_RE = re.compile(
    r"\b(?:merece|vale)\s+la\s+pena"
    r"|\bdeberia\s+(?:comprar|invertir|entrar|mantener|vender|quedarme|salir)"
    r"|\b(?:es|seria)\b[^?.!]{0,40}\bbuena\s+(?:inversion|compra|empresa|idea|oportunidad)"
    r"|\bque\s+(?:opinas|piensas)\s+(?:de|sobre)\b|\bque\s+te\s+parece\b|\bcomo\s+ves\b"
    r"|\banaliza(?:me|r)?\b|\banalisis\s+(?:de|completo|a\s+fondo)\b|\binvertir\s+en\b"
    r"|\bworth\s+(?:it|buying|investing|holding|a\s+buy)\b"
    r"|\bshould\s+i\s+(?:buy|invest|hold|sell|keep)\b"
    r"|\bgood\s+(?:investment|buy|company|stock)\b"
    r"|\bwhat\s+do\s+you\s+think\s+(?:of|about)\b|\bthoughts\s+on\b"
    r"|\banaly[sz]e\b|\banalysis\s+of\b|\binvest\s+in\b"
    # Más formas (#lead expertos-4): futuro, pros/contras, condicional, recomendación, perspectivas.
    r"|\btiene\s+futuro\b|\bpros\s+y\s+contras\b|\bpuntos\s+fuertes\b|\bventajas\s+y\s+(?:desventajas|riesgos)\b"
    r"|\b(?:comprarias|entrarias|invertirias|venderias|mantendrias)\b"
    r"|\bbuen\s+momento\s+para\s+(?:comprar|entrar|invertir|vender|salir)\b"
    r"|\b(?:me\s+|la\s+|lo\s+)?recomiendas\b|\bopinion\s+(?:de|sobre)\b|\bperspectivas\b|\bbuen\s+negocio\b"
    r"|\bis\b[^?.!]{0,30}\ba\s+(?:buy|good\s+buy)\b|\bbuy\s+or\s+sell\b"
    r"|\bwould\s+you\s+(?:buy|invest|hold|sell|recommend)\b|\bdo\s+you\s+recommend\b"
    r"|\bpros\s+and\s+cons\b|\b(?:bull|bear)(?:\s+and\s+bear)?\s+case\b|\boutlook\b|\bprospects\b"
    r"|\bdeep\s+dive\b"
    # «¿Vendo Uber o la mantengo?», «¿compro más o espero?», «sell or hold?»: elegir
    # entre dos opciones sobre una empresa (prueba real 2026-11-03: iba a la
    # síntesis normal aunque el equipo estuviera encendido).
    r"|\b(?:vendo|compro|mantengo|aguanto)\b[^?.!]{0,40}?\bo\s+(?:no\b|(?:(?:la|lo|las|los|me\s+la|me\s+lo)\s+)?"
    r"(?:mantengo|vendo|compro|espero|aguanto|sigo|quedo)\b)"
    r"|\b(?:sell|buy|hold)\s+or\s+(?:hold|sell|buy|wait|keep)\b"
)


def fold(text: str) -> str:
    """Minúsculas y sin tildes, igual que el plan (lo usa también la plantilla)."""
    return _fold(text)


def keyword_hit(question: str, keyword: str) -> bool:
    """Palabra clave del plan sobre el texto ya plegado: por defecto vale como
    prefijo («valor» → «valoración»); con espacio final, solo la palabra entera
    («cara » no salta con «características»)."""
    word = keyword.rstrip()
    tail = r"\b" if keyword != word else ""
    return re.search(rf"\b{re.escape(word)}{tail}", question) is not None


def is_broad_question(question: str) -> bool:
    return bool(_BROAD_RE.search(_fold(question)))


def _fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


#: Espera máxima a que los expertos cancelados por el tope total terminen de cancelarse.
CANCEL_GRACE_S = 0.5


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
        judge_timeout_s: float = 30.0,
        cancel_grace_s: float = CANCEL_GRACE_S,
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
        #: Al vencer el tope total, cuánto se espera como mucho a que los
        #: expertos cancelados terminen de cancelarse (corto: cabe en el margen del chat).
        self.cancel_grace_s = cancel_grace_s
        #: Tope propio del juez: si no llega, el equipo contesta sin veredicto
        #: en vez de perder todo lo que dijeron los expertos.
        self.judge_timeout_s = judge_timeout_s

    def plan(self, ctx: RunContext) -> list[str]:
        """Determinista: tesis = todos los aplicables; chat = por palabras clave o pregunta amplia."""
        chosen: list[str] = []
        question = _fold(ctx.question or "")
        broad = ctx.mode == "chat" and bool(_BROAD_RE.search(question))
        for spec in self.experts:
            if ctx.mode not in spec.modes:
                continue
            if spec.applies is not None and not spec.applies(ctx):
                continue
            if (
                ctx.mode == "chat"
                and not (broad and spec.broad)
                and not any(keyword_hit(question, k) for k in spec.keywords)
            ):
                continue
            chosen.append(spec.name)
        return chosen

    async def _one(
        self,
        spec: ExpertSpec,
        ctx: RunContext,
        ledger: EvidenceLedger,
        sem: asyncio.Semaphore,
        gathered: _Gathered | None = None,
    ):
        async with sem:
            timeout = spec.timeout_s
            if isinstance(gathered, _Gathered):
                if gathered.error is not None:
                    return gathered.error
                # El tope del experto sigue contando la recogida de evidencia (como antes).
                timeout = max(0.0, spec.timeout_s - gathered.elapsed_s)
            try:
                return await asyncio.wait_for(
                    run_expert(
                        spec,
                        ctx,
                        tools=self.tools,
                        ledger=ledger,
                        reasoner=self.reasoner,
                        validator=self.validator,
                        gathered=(gathered.evidence, gathered.tool_errors) if gathered is not None else None,
                    ),
                    timeout=timeout,
                )
            except TimeoutError:
                return ExpertReport(expert=spec.name, status="timeout")
            except run_guard.LLMGuardAbort as exc:
                return ExpertReport(expert=spec.name, status="error", error=str(exc))
            except Exception as exc:
                return ExpertReport(expert=spec.name, status="error", error=type(exc).__name__)

    async def _gather_one(self, spec: ExpertSpec, ctx: RunContext, ledger: EvidenceLedger) -> _Gathered:
        loop = asyncio.get_running_loop()
        started = loop.time()
        try:
            evidence, tool_errors = await asyncio.wait_for(
                gather_evidence(spec, ctx, self.tools, ledger), timeout=spec.timeout_s
            )
        except TimeoutError:
            return _Gathered(error=ExpertReport(expert=spec.name, status="timeout"))
        except Exception as exc:
            return _Gathered(error=ExpertReport(expert=spec.name, status="error", error=type(exc).__name__))
        return _Gathered(evidence=evidence, tool_errors=tool_errors, elapsed_s=loop.time() - started)

    async def run(self, ctx: RunContext) -> TeamResult:
        plan = self.plan(ctx)
        specs = [s for s in self.experts if s.name in plan]
        ledger = EvidenceLedger()
        sem = asyncio.Semaphore(self.max_parallel)
        activation = run_guard.activate(self.guard) if self.guard is not None else contextlib.nullcontext()
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.total_timeout_s
        with activation:
            # 1) Evidencia de TODOS los expertos primero, en el orden del plantel: es
            #    trabajo local (base de datos) de milisegundos y deja los ids ev-N
            #    igual que antes. 2) Las llamadas al modelo, con el mismo tope de
            #    paralelo, empiezan por los expertos más lentos: con 5 expertos y 3
            #    huecos, el fiscal (12-22 s) ya no espera a que acabe el de valoración.
            gather_tasks = [asyncio.create_task(self._gather_one(s, ctx, ledger)) for s in specs]
            gathered: dict[str, _Gathered] = {}
            if gather_tasks:
                g_done, g_pending = await asyncio.wait(gather_tasks, timeout=max(0.0, deadline - loop.time()))
                for task in g_pending:
                    task.cancel()
                if g_pending:
                    await asyncio.wait(g_pending, timeout=max(0.0, self.cancel_grace_s))
                for spec, task in zip(specs, gather_tasks, strict=True):
                    if task in g_done:
                        gathered[spec.name] = task.result()
            launch = sorted((s for s in specs if s.name in gathered), key=lambda s: -s.typical_s)
            by_name = {s.name: asyncio.create_task(self._one(s, ctx, ledger, sem, gathered[s.name])) for s in launch}
            tasks = list(by_name.values())
            done, pending = (
                await asyncio.wait(tasks, timeout=max(0.0, deadline - loop.time())) if tasks else (set(), set())
            )
            for task in pending:
                task.cancel()
            if pending:
                # Esperarlas (con tope corto) para que ningún experto siga vivo
                # cuando el equipo ya contestó; uno que no se deja cancelar no
                # bloquea la respuesta y cuenta como «no respondió a tiempo».
                await asyncio.wait(pending, timeout=max(0.0, self.cancel_grace_s))
            reports = [
                by_name[s.name].result()
                if s.name in by_name and by_name[s.name] in done
                else ExpertReport(expert=s.name, status="timeout")
                for s in specs
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
                        # El «id» de la fila (aviso de riesgo, tesis) no puede pisar el de la
                        # evidencia: es el que llevan las citas [n]. Se guarda como «row_id».
                        source = dict(evidence.source)
                        row_id = source.pop("id", None)
                        seen[cid] = {**source, "id": cid, "tool": evidence.tool, "expert": evidence.expert}
                        if row_id is not None:
                            seen[cid]["row_id"] = row_id
        return list(seen.values())

    @staticmethod
    def _metric_conflicts(reports: list[ExpertReport]) -> list[dict[str, Any]]:
        by_metric: dict[str, list[dict[str, Any]]] = {}
        for report in reports:
            for claim in report.claims:
                if claim.metric and claim.numbers and not claim.reason:  # solo con fuente
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
        ok = [r for r in reports if r.status == "ok" and any(not c.reason for c in r.claims)]
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
            return "\n".join(
                f"- [{r.expert}] {c.text}" for r in reports if r.expert in names for c in r.claims if not c.reason
            )

        user = (
            f"Ticker: {ctx.ticker or '-'}\nCASO A FAVOR:\n{case(conflict['positive'])}\n"
            f"CASO EN CONTRA:\n{case(conflict['negative'])}"
        )
        try:
            prompt = get_prompt(self.judge_prompt, lang=ctx.lang)
            text = await asyncio.wait_for(
                self.reasoner(prompt.text, user, 200, "expert_team.judge"), timeout=max(0.0, self.judge_timeout_s)
            )
        except TimeoutError:
            return {"label": "neutral", "rationale": "", "source": "timeout"}
        except Exception:
            return {"label": "neutral", "rationale": "", "source": "unresolved"}
        match = re.search(r"(bullish|bearish|neutral)\s*\|?\s*(.*)", text or "", re.IGNORECASE | re.DOTALL)
        if not match:
            return {"label": "neutral", "rationale": "", "source": "unresolved"}
        rationale = match.group(2).strip()[:600]
        # El juez solo vio afirmaciones validadas: una cifra que no está en ellas
        # sería inventada, así que su frase no se enseña (el veredicto sí).
        if not figures_supported(rationale, user):
            rationale = ""
        return {"label": _JUDGE_LABELS[match.group(1).lower()], "rationale": rationale, "source": "judge"}
