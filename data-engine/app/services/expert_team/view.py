"""Lectura de la última tesis guardada del equipo de expertos (detrás de EXPERT_TEAM_ENABLED).

La tesis con expertos se guarda en ``workflow_runs`` (ExpertTeamThesisWorkflow)
pero no había forma de verla después. Esto la convierte en algo que la
pantalla puede pintar: una sección por experto con sus afirmaciones válidas
y sus referencias [n], y las fuentes numeradas (con enlace si lo hay). Solo
lee: ni ejecuta el equipo ni llama al LLM. El aislamiento por tenant es el
del ORM (igual que GET /thesis/jobs) y, además, se comprueba el tenant que
quedó grabado en la propia corrida.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models.entities import WorkflowRun

WORKFLOW_NAME = "ExpertTeamThesisWorkflow"
_LATEST_SCAN = 20
HISTORY_LIMIT = 5


class ExpertThesisClaimOut(BaseModel):
    text: str
    refs: list[int] = Field(default_factory=list)


class ExpertThesisSectionOut(BaseModel):
    expert: str
    status: str
    summary: str = ""
    stance: str = "neutral"
    claims: list[ExpertThesisClaimOut] = Field(default_factory=list)


class ExpertThesisSourceOut(BaseModel):
    n: int
    title: str
    url: str | None = None


class ExpertThesisVerdictOut(BaseModel):
    label: str
    rationale: str = ""


class ExpertThesisRunOut(BaseModel):
    """Resumen de una corrida anterior: fecha, veredicto y quién respondió."""

    run_id: int
    finished_at: datetime | None = None
    verdict: str | None = None
    answered: list[str] = Field(default_factory=list)
    timed_out: list[str] = Field(default_factory=list)


class ExpertThesisOut(BaseModel):
    ticker: str
    run_id: int
    finished_at: datetime | None = None
    plan: list[str] = Field(default_factory=list)
    sections: list[ExpertThesisSectionOut] = Field(default_factory=list)
    sources: list[ExpertThesisSourceOut] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    verdict: ExpertThesisVerdictOut | None = None
    history: list[ExpertThesisRunOut] = Field(default_factory=list)


def _result_of(run: WorkflowRun) -> dict[str, Any] | None:
    payload = run.result_payload if isinstance(run.result_payload, dict) else {}
    result = payload.get("result")
    return result if isinstance(result, dict) and isinstance(result.get("reports"), list) else None


def expert_thesis_runs(db: Session, ticker: str, limit: int) -> list[tuple[WorkflowRun, dict[str, Any]]]:
    """Corridas COMPLETADAS del equipo para este ticker y este tenant, la última primero."""
    symbol = ticker.strip().upper()
    tenant = db.info.get("tenant_id")
    runs = db.scalars(
        select(WorkflowRun)
        .where(
            WorkflowRun.workflow_name == WORKFLOW_NAME,
            WorkflowRun.status == "completed",
            WorkflowRun.input_payload["ticker"].as_string() == symbol,
        )
        .order_by(desc(WorkflowRun.id))
        .limit(_LATEST_SCAN)
    ).all()
    found: list[tuple[WorkflowRun, dict[str, Any]]] = []
    for run in runs:
        result = _result_of(run)
        if result is None:
            continue
        owner = (result.get("context") or {}).get("tenant_id")
        if tenant is not None and owner is not None and str(owner) != str(tenant):
            continue
        found.append((run, result))
        if len(found) >= limit:
            break
    return found


def latest_expert_thesis(db: Session, ticker: str) -> tuple[WorkflowRun, dict[str, Any]] | None:
    """Última corrida COMPLETADA del equipo para este ticker y este tenant."""
    found = expert_thesis_runs(db, ticker, 1)
    return found[0] if found else None


def _valid_claims(report: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        c
        for c in report.get("claims") or []
        if isinstance(c, dict) and not c.get("reason") and str(c.get("text") or "").strip()
    ]


def _verdict_label(result: dict[str, Any], t: dict[str, Any]) -> str | None:
    verdict = result.get("verdict") if isinstance(result.get("verdict"), dict) else None
    if not verdict or verdict.get("source") != "judge":
        return None
    label = str(verdict.get("label") or "")
    return t["labels"].get(label, label)


def run_summary(run: WorkflowRun, result: dict[str, Any], lang: str) -> ExpertThesisRunOut:
    from app.services.expert_team.chat import _LABELS

    t = _LABELS.get(lang, _LABELS["es"])
    reports = [r for r in result.get("reports") or [] if isinstance(r, dict)]
    return ExpertThesisRunOut(
        run_id=run.id,
        finished_at=run.finished_at,
        verdict=_verdict_label(result, t),
        answered=[str(r.get("expert") or "") for r in reports if _valid_claims(r)],
        timed_out=[str(r.get("expert") or "") for r in reports if r.get("status") == "timeout"],
    )


def _url(src: dict[str, Any]) -> str | None:
    url = str(src.get("url") or "").strip()
    return url if url.startswith(("https://", "http://")) else None


def thesis_view(
    run: WorkflowRun,
    result: dict[str, Any],
    lang: str,
    earlier: list[tuple[WorkflowRun, dict[str, Any]]] | None = None,
) -> ExpertThesisOut:
    from app.services.expert_team.chat import _LABELS, _source_label

    t = _LABELS.get(lang, _LABELS["es"])
    sources = [s for s in result.get("sources") or [] if isinstance(s, dict) and s.get("id")]
    numbers = {str(src["id"]): n for n, src in enumerate(sources, start=1)}
    sections: list[ExpertThesisSectionOut] = []
    for report in result.get("reports") or []:
        if not isinstance(report, dict):
            continue
        claims = [
            ExpertThesisClaimOut(
                text=str(c.get("text") or ""),
                refs=[numbers[str(cid)] for cid in c.get("citations") or [] if str(cid) in numbers],
            )
            for c in _valid_claims(report)
        ]
        sections.append(
            ExpertThesisSectionOut(
                expert=str(report.get("expert") or ""),
                status=str(report.get("status") or "error") if claims or report.get("status") != "ok" else "no_data",
                summary=str(report.get("summary") or "") if claims else "",
                stance=str(report.get("stance") or "neutral"),
                claims=claims,
            )
        )
    conflicts: list[str] = []
    for conflict in result.get("conflicts") or []:
        if not isinstance(conflict, dict):
            continue
        if conflict.get("type") == "stance":
            pos = ", ".join(t.get(e, e) for e in conflict.get("positive", []))
            neg = ", ".join(t.get(e, e) for e in conflict.get("negative", []))
            conflicts.append(t["stance"].format(pos=pos, neg=neg))
        else:
            conflicts.append(t["metric"].format(metric=conflict.get("metric", "")))
    label = _verdict_label(result, t)
    verdict_out = None
    if label is not None:
        verdict_out = ExpertThesisVerdictOut(
            label=label, rationale=str(result["verdict"].get("rationale") or "")
        )
    context = result.get("context") or {}
    return ExpertThesisOut(
        ticker=str(context.get("ticker") or (run.input_payload or {}).get("ticker") or ""),
        run_id=run.id,
        finished_at=run.finished_at,
        plan=[str(p) for p in result.get("plan") or []],
        sections=sections,
        sources=[
            ExpertThesisSourceOut(n=numbers[str(src["id"])], title=_source_label(src, lang), url=_url(src))
            for src in sources
        ],
        conflicts=conflicts,
        verdict=verdict_out,
        history=[run_summary(r, res, lang) for r, res in earlier or []],
    )
