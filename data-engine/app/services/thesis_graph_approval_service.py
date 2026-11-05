"""Stage 6c: durable approval interrupt for the thesis graph pilot.

The thesis lifecycle graph (6a skeleton) pauses at a real ``approval_gate``
interrupt. This service runs the graph under a durable checkpointer
(Postgres in prod, file-backed sqlite locally) so the pause survives across
requests and processes, and resumes the same thread when a decision arrives.

Distinct from ``thesis_approval_service`` (Telegram human-in-the-loop on the
classic path): this pilot operates on graph control state only and never
publishes domain artifacts.

Honesty contract:
- every graph node is a real read-side probe or a real approval interrupt;
  no artifact is a ``pending:<node>`` stand-in. The classic ThesisService path
  stays the sole LLM/write executor;
- a thread that ends as ``approved`` was approved but nothing was published,
  and it only ends as ``published`` when a published thesis version exists;
- every start/decide is recorded as a durable WorkflowRun envelope;
- re-delivery is safe: an idempotency-key replay returns the stored result,
  a repeated start on an already-waiting thread returns the pending state
  without re-executing, and a decide on an already-decided thread reports
  ``already_decided`` instead of deciding twice.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any

from langgraph.types import Command
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.services.company_resolver import resolve_company
from app.services.workflow_run_service import begin_run


@contextmanager
def _session_scope(db):
    """Adapt the request-scoped session to the node session factory."""
    yield db
from app.workflows.thesis_graph import build_thesis_graph, thesis_thread_id
from app.workflows.thesis_graph.checkpointer import durable_checkpointer

WORKFLOW_NAME = "ThesisApprovalWorkflow"
DECISIONS = ("approve", "request_changes")
# Statuses terminales tras una decision. "approved" NO es "published": el
# grafo aprueba un candidato y nunca publica; "published" solo aparece cuando
# hay de verdad una ThesisVersion publicada de la ruta clasica.
DECIDED_STATUSES = frozenset({"published", "approved", "changes_requested"})


class ThesisGraphApprovalService:
    def __init__(
        self,
        *,
        checkpoint_path: str | None = None,
        database_url: str | None = None,
    ) -> None:
        self._checkpoint_path = checkpoint_path
        self._database_url = database_url

    def _checkpointer(self):
        settings = get_settings()
        url = self._database_url or settings.database_url
        path = self._checkpoint_path or str(settings.thesis_graph_checkpoint_path)
        return durable_checkpointer(url, sqlite_path=path)

    @staticmethod
    def _pending_approval(snapshot) -> dict[str, Any] | None:
        """Interrupt payload when the thread is paused at the approval gate."""
        if snapshot.next != ("approval_gate",):
            return None
        for task in snapshot.tasks:
            for pending in task.interrupts:
                return dict(pending.value)
        return {"type": "thesis_approval"}

    def start(
        self,
        db: Session,
        *,
        ticker: str,
        tenant_external_id: str = "default",
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        company = resolve_company(db, ticker)
        if company is None:
            return {"ticker": ticker.upper(), "status": "unknown_company"}

        envelope = begin_run(
            db,
            WORKFLOW_NAME,
            execution_mode="pilot",
            input_payload={"ticker": company.ticker, "phase": "start"},
            idempotency_key=idempotency_key,
        )
        if envelope.replayed:
            return {**dict(envelope.run.result_payload or {}), "idempotent_replay": True}

        thread_id = thesis_thread_id(
            tenant_external_id, str(company.id), f"approval-{company.ticker}"
        )
        config = {"configurable": {"thread_id": thread_id}}

        try:
            with self._checkpointer() as saver:
                graph = build_thesis_graph(
                    checkpointer=saver, session_factory=lambda: _session_scope(db)
                )
                snapshot = graph.get_state(config)
                pending = self._pending_approval(snapshot)
                if pending is None and not snapshot.next and not snapshot.values:
                    # Fresh thread: run until the approval gate interrupt.
                    graph.invoke(
                        {
                            "ticker": company.ticker,
                            "tenant_id": tenant_external_id,
                            "company_id": str(company.id),
                            "input_fingerprint": f"approval-{company.ticker}",
                        },
                        config=config,
                    )
                    snapshot = graph.get_state(config)
                    pending = self._pending_approval(snapshot)
        except Exception as exc:
            envelope.fail(exc)
            raise

        if pending is not None:
            result: dict[str, Any] = {
                "ticker": company.ticker,
                "thread_id": thread_id,
                "status": "awaiting_approval",
                "awaiting_approval": True,
                "approval_request": pending,
            }
        else:
            # Already decided (or finished) thread: report current state.
            result = {
                "ticker": company.ticker,
                "thread_id": thread_id,
                "status": snapshot.values.get("status"),
                "awaiting_approval": False,
            }
        envelope.finish(result)
        return result

    def decide(
        self,
        db: Session,
        *,
        thread_id: str,
        decision: str,
        notes: str | None = None,
        actor: str = "user",
        idempotency_key: str | None = None,
        tenant_external_id: str | None = None,
    ) -> dict[str, Any]:
        if decision not in DECISIONS:
            raise ValueError(f"decision must be one of {DECISIONS}")
        if tenant_external_id is not None and not thread_id.startswith(
            f"thesis:{tenant_external_id}:"
        ):
            # Thread belongs to another tenant (or is forged): never touch its
            # checkpoint and do not reveal that it exists.
            return {"thread_id": thread_id, "status": "unknown_thread"}

        envelope = begin_run(
            db,
            WORKFLOW_NAME,
            execution_mode="pilot",
            input_payload={"thread_id": thread_id, "phase": "decide", "decision": decision},
            idempotency_key=idempotency_key,
        )
        if envelope.replayed:
            return {**dict(envelope.run.result_payload or {}), "idempotent_replay": True}

        config = {"configurable": {"thread_id": thread_id}}
        try:
            with self._checkpointer() as saver:
                graph = build_thesis_graph(
                    checkpointer=saver, session_factory=lambda: _session_scope(db)
                )
                snapshot = graph.get_state(config)
                if self._pending_approval(snapshot) is None:
                    status = (snapshot.values or {}).get("status")
                    if status in DECIDED_STATUSES:
                        result = {
                            "thread_id": thread_id,
                            "status": status,
                            "already_decided": True,
                        }
                    elif snapshot.values:
                        result = {
                            "thread_id": thread_id,
                            "status": "not_awaiting_approval",
                            "pending_nodes": list(snapshot.next),
                        }
                    else:
                        result = {"thread_id": thread_id, "status": "unknown_thread"}
                    envelope.finish(result)
                    return result
                graph.invoke(
                    Command(resume={"decision": decision, "notes": notes, "actor": actor}),
                    config=config,
                )
                snapshot = graph.get_state(config)
        except Exception as exc:
            envelope.fail(exc)
            raise

        final = snapshot.values
        result = {
            "thread_id": thread_id,
            "status": final.get("status"),
            "decision": decision,
            "completed_nodes": list(final.get("completed_nodes") or []),
            "approval": (final.get("meta") or {}).get("approval"),
        }
        envelope.finish(result)
        return result
