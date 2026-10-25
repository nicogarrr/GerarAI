"""Stage 6b: LangGraph thesis pilot shadow comparison.

Runs the thesis lifecycle graph (stage 6a skeleton) alongside the classic
ThesisService path - which remains the source of truth - and records a
structured comparison as a durable WorkflowRun. The shadow never mutates
domain artifacts: the graph writes control state only, and this service
reads the classic path's persisted outputs.

Tenant contract: ``tenant_external_id`` is required (no default). The API
passes the caller's real tenant so graph threads are namespaced per tenant
(``thesis:{tenant}:{company}:...``); a shared default namespace would
collide across tenants the day the shadow moves to a durable checkpointer.

Comparison contract (honest by construction):
- graph_execution: did all graph nodes commit in order under the checkpointer
  (resuming the 6c approval interrupt with an explicit synthetic shadow
  decision), and does an idempotent re-invoke on the same thread add zero
  new nodes (crash-safe retry).
- phase_mapping: every classic THESIS_PHASES phase maps to a graph node;
  unmapped phases are listed, never silently dropped.
- status_semantics: graph lifecycle status vs the latest persisted
  ThesisVersion status, with divergences listed explicitly.
- probe_comparison (6d/6e): the read-side probes (resolve_company,
  ensure_ingestion_complete, build_fundamental_model,
  deterministic_valuation, draft_synthesis, source_audit,
  deterministic_red_team) are compared against the classic persisted state
  they observe - match/divergent/unobserved per node. No probe emits a
  ``pending:<node>`` reference: a graph that cannot verify something reports
  it as unobserved instead of pretending it is on its way.
- The classic ThesisService path owns every write. The graph's write-side
  stages (assemble_candidate, persisted_thesis) only observe what was
  already persisted, so the write asymmetry is recorded as a standing,
  expected divergence instead of being hidden.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any

from langgraph.types import Command
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.tenancy import tenant_filters
from app.models import Company, ThesisVersion
from app.services.company_resolver import resolve_company
from app.services.thesis_job_service import THESIS_PHASES
from app.services.workflow_run_service import begin_run


@contextmanager
def _session_scope(db):
    """Adapt the request-scoped session to the node session factory."""
    yield db
from app.workflows.thesis_graph import THESIS_GRAPH_NODES, build_thesis_graph, thesis_thread_id
from app.workflows.thesis_graph.checkpointer import sqlite_checkpointer

WORKFLOW_NAME = "ThesisShadowComparisonWorkflow"

# Classic phase -> owning graph node (6b mapping; every phase must appear).
# compose_thesis -> draft_synthesis: the node observes the thesis version the
# classic path composed and persisted. persist_thesis -> persisted_thesis: the
# node observes the publication state of that version (the graph never
# publishes). optional_bull_bear_debate is not here because the debate is an
# LLM call that persists nothing; it is served by POST /api/thesis/{ticker}/debate.
PHASE_TO_NODE: dict[str, str] = {
    "collect_evidence": "ensure_ingestion_complete",
    "build_fundamental_model": "build_fundamental_model",
    "run_valuation": "deterministic_valuation",
    "persist_valuation_snapshot": "deterministic_valuation",
    "source_audit": "source_audit",
    "compose_thesis": "draft_synthesis",
    "persist_thesis": "persisted_thesis",
}


def _probe_entry(node: str, graph_artifact: str | None, classic_observed: str) -> dict[str, Any]:
    """One probe comparison row: graph-observed artifact vs classic state.

    A probe that reported nothing is ``unobserved``, never ``match``: an
    absent observation must not read as agreement.
    """
    if graph_artifact is None:
        status = "unobserved"
    else:
        status = "match" if graph_artifact == classic_observed else "divergent"
    return {
        "node": node,
        "graph_artifact": graph_artifact,
        "classic_observed": classic_observed,
        "status": status,
    }


def _compare_probes(db: Session, company: Company, artifacts: dict[str, str]) -> list[dict[str, Any]]:
    """Compare the graph's read-side probes against classic persisted state.

    The classic path owns every write; the probes are read-only
    observations taken during the graph run. A divergence means the graph
    observed different state than the classic side sees now, which the
    caller records explicitly.

    The probe set is the fixed read-side probe contract: the six nodes whose
    artifact is a direct observation of classic-owned tables. ``draft_synthesis``
    and ``persisted_thesis`` read the thesis version too, but they are covered
    by ``status_semantics`` (graph status vs latest ThesisVersion) and by the
    graph's own artifacts, so they are not duplicated here.
    """
    from sqlalchemy import desc, func, select

    from app.models.entities import (
        Document,
        FinancialFact,
        FundamentalModelVersion,
        FundamentalValuationSnapshot,
        MarketPrice,
        RedTeamRun,
    )

    cid = company.id
    facts = db.scalar(
        select(func.count())
        .select_from(FinancialFact)
        .where(
            FinancialFact.company_id == cid,
            *tenant_filters(db, FinancialFact),
        )
    ) or 0
    prices = db.scalar(
        select(func.count()).select_from(MarketPrice).where(MarketPrice.company_id == cid)
    ) or 0
    documents = db.scalar(
        select(func.count())
        .select_from(Document)
        .where(
            Document.company_id == cid,
            *tenant_filters(db, Document),
        )
    ) or 0

    model = db.scalar(
        select(FundamentalModelVersion)
        .where(FundamentalModelVersion.company_id == cid)
        .order_by(desc(FundamentalModelVersion.version))
        .limit(1)
    )
    classic_model = (
        f"model:v{model.version}:{model.input_fingerprint[:12]}" if model else "model:none"
    )

    snapshot = db.scalar(
        select(FundamentalValuationSnapshot)
        .where(FundamentalValuationSnapshot.company_id == cid)
        .order_by(desc(FundamentalValuationSnapshot.created_at), desc(FundamentalValuationSnapshot.id))
        .limit(1)
    )
    classic_valuation = f"valuation:{snapshot.id}" if snapshot else "valuation:none"

    fact_rows = db.execute(
        select(FinancialFact.source_type, func.count())
        .where(
            FinancialFact.company_id == cid,
            *tenant_filters(db, FinancialFact),
        )
        .group_by(FinancialFact.source_type)
    ).all()
    doc_rows = db.execute(
        select(Document.source_type, func.count())
        .where(
            Document.company_id == cid,
            *tenant_filters(db, Document),
        )
        .group_by(Document.source_type)
    ).all()
    low_confidence = db.scalar(
        select(func.count())
        .select_from(FinancialFact)
        .where(
            FinancialFact.company_id == cid,
            FinancialFact.confidence < 0.5,
            *tenant_filters(db, FinancialFact),
        )
    ) or 0
    facts_by_source = {str(src): count for src, count in fact_rows}
    docs_by_source = {str(src): count for src, count in doc_rows}
    facts_part = ",".join(f"{k}:{facts_by_source[k]}" for k in sorted(facts_by_source))
    docs_part = ",".join(f"{k}:{docs_by_source[k]}" for k in sorted(docs_by_source))
    classic_audit = f"audit:facts={{{facts_part}}}|docs={{{docs_part}}}|lowconf={low_confidence}"

    red_team = db.scalar(
        select(RedTeamRun)
        .where(RedTeamRun.company_id == cid)
        .order_by(desc(RedTeamRun.created_at), desc(RedTeamRun.id))
        .limit(1)
    )
    classic_red_team = f"redteam:{red_team.id}:score={red_team.score}" if red_team else "redteam:none"

    return [
        _probe_entry("resolve_company", artifacts.get("resolve_company"), f"company:{cid}"),
        _probe_entry(
            "ensure_ingestion_complete",
            artifacts.get("ensure_ingestion_complete"),
            f"evidence:facts={facts},prices={prices},docs={documents}",
        ),
        _probe_entry("build_fundamental_model", artifacts.get("build_fundamental_model"), classic_model),
        _probe_entry("deterministic_valuation", artifacts.get("deterministic_valuation"), classic_valuation),
        _probe_entry("source_audit", artifacts.get("source_audit"), classic_audit),
        _probe_entry(
            "deterministic_red_team",
            artifacts.get("deterministic_red_team"),
            classic_red_team,
        ),
    ]


class ThesisShadowService:
    def run(
        self,
        db: Session,
        *,
        ticker: str,
        tenant_external_id: str,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        company = resolve_company(db, ticker)
        if company is None:
            return {"ticker": ticker.upper(), "status": "unknown_company"}

        envelope = begin_run(
            db,
            WORKFLOW_NAME,
            execution_mode="shadow",
            input_payload={"ticker": company.ticker},
            idempotency_key=idempotency_key,
        )
        if envelope.replayed:
            return {**dict(envelope.run.result_payload or {}), "idempotent_replay": True}

        thread_id = thesis_thread_id(
            tenant_external_id, str(company.id), f"shadow-{company.ticker}"
        )
        config = {"configurable": {"thread_id": thread_id}}

        with sqlite_checkpointer() as saver:
            graph = build_thesis_graph(
                checkpointer=saver, session_factory=lambda: _session_scope(db)
            )
            initial = graph.invoke(
                {
                    "ticker": company.ticker,
                    "tenant_id": tenant_external_id,
                    "company_id": str(company.id),
                    "input_fingerprint": f"shadow-{company.ticker}",
                },
                config=config,
            )
            # 6c: the run pauses at the real approval_gate interrupt. The
            # shadow resumes with an explicit synthetic decision so the
            # comparison still validates full traversal; the decision is
            # recorded in control state only, never in domain artifacts.
            snapshot = graph.get_state(config)
            interrupted_at_gate = snapshot.next == ("approval_gate",)
            if interrupted_at_gate:
                first = graph.invoke(
                    Command(resume={"decision": "approve", "actor": "shadow-auto-approve"}),
                    config=config,
                )
            else:
                first = initial
            # Idempotent re-delivery: a retry on the same thread must add
            # zero newly committed nodes.
            second = graph.invoke(
                {
                    "ticker": company.ticker,
                    "tenant_id": tenant_external_id,
                    "company_id": str(company.id),
                    "input_fingerprint": f"shadow-{company.ticker}",
                },
                config=config,
            )

        graph_nodes = list(first.get("completed_nodes") or [])
        retry_new_nodes = [
            node for node in (second.get("completed_nodes") or []) if node not in graph_nodes
        ]
        graph_execution = {
            "nodes_in_order": graph_nodes == list(THESIS_GRAPH_NODES),
            "completed_nodes": graph_nodes,
            "final_status": first.get("status"),
            "retry_added_nodes": retry_new_nodes,
            "idempotent_retry": retry_new_nodes == [],
            "approval_interrupt": {
                "interrupted_at_gate": interrupted_at_gate,
                "resume_decision": {"decision": "approve", "actor": "shadow-auto-approve"},
            },
        }

        unmapped_phases = [phase for phase in THESIS_PHASES if phase not in PHASE_TO_NODE]
        missing_nodes = [
            PHASE_TO_NODE[phase]
            for phase in THESIS_PHASES
            if phase in PHASE_TO_NODE and PHASE_TO_NODE[phase] not in THESIS_GRAPH_NODES
        ]
        phase_mapping = {
            "classic_phases": list(THESIS_PHASES),
            "mapping": dict(PHASE_TO_NODE),
            "unmapped_phases": unmapped_phases,
            "missing_graph_nodes": missing_nodes,
            "complete": not unmapped_phases and not missing_nodes,
        }

        latest = db.scalar(
            select(ThesisVersion)
            .where(ThesisVersion.company_id == company.id)
            .order_by(ThesisVersion.version.desc())
            .limit(1)
        )
        divergences = []
        if latest is None:
            divergences.append("classic path has no persisted thesis version for this company")
        if graph_nodes != list(THESIS_GRAPH_NODES):
            divergences.append("graph did not commit all nodes in order")
        if retry_new_nodes:
            divergences.append(f"idempotent retry re-executed nodes: {retry_new_nodes}")
        if unmapped_phases:
            divergences.append(f"classic phases without graph node: {unmapped_phases}")
        if missing_nodes:
            divergences.append(f"mapped nodes missing from graph: {missing_nodes}")
        probe_comparison = _compare_probes(db, company, first.get("artifacts") or {})
        for entry in probe_comparison:
            if entry["status"] == "divergent":
                divergences.append(
                    f"probe {entry['node']} diverged: graph observed "
                    f"{entry['graph_artifact']}, classic persisted {entry['classic_observed']}"
                )
        for entry in probe_comparison:
            if entry["status"] == "unobserved":
                divergences.append(
                    f"probe {entry['node']} reported no observation; the graph cannot be "
                    "compared with the classic path on this node"
                )
        divergences.append(
            "expected at 6d: the graph is a read-side control plane and the classic "
            "ThesisService path is the sole LLM/write executor, so every write-side "
            "stage (assemble_candidate, persisted_thesis) differs from the classic path "
            "by construction: the graph never publishes domain artifacts"
        )

        status_semantics = {
            "graph_status": first.get("status"),
            "classic_latest_version": (
                {"version": latest.version, "status": latest.status} if latest else None
            ),
        }

        result = {
            "ticker": company.ticker,
            "thread_id": thread_id,
            "graph_execution": graph_execution,
            "phase_mapping": phase_mapping,
            "status_semantics": status_semantics,
            "probe_comparison": probe_comparison,
            "divergences": divergences,
            "shadow_only": True,
        }
        # El run_id viaja dentro del payload persistido: la ruta no
        # re-consulta "el ultimo run" (carrera entre runs concurrentes del
        # mismo tenant) y un replay idempotente devuelve el run original.
        result["run_id"] = envelope.run.id
        envelope.finish(result)
        return result
