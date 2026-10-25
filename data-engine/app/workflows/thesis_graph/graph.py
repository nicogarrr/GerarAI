"""Thesis lifecycle graph: durable control plane over read-side probes.

Flow:
    resolve_company -> freeze_input_snapshot -> ensure_ingestion_complete
    -> build_fundamental_model -> deterministic_valuation -> draft_synthesis
    -> source_audit -> deterministic_red_team -> assemble_candidate
    -> approval_gate -> persisted_thesis

Boundary (the honest one):
- The classic ``ThesisService.generate()`` path is the SOLE LLM/write executor.
  This graph never writes a domain artifact: it resolves the company, freezes
  the input fingerprint and then *observes* what the classic path persisted
  (evidence coverage, model, valuation, thesis draft, source audit, red team)
  before asking a human to approve a candidate.
- Every node commits a REAL artifact reference or fails loudly. There is no
  ``pending:<node>`` anywhere: a node either reports something it verified or
  it raises. The absence of an observation is reported as an explicit
  ``*:none`` reference, never as a pending stand-in.
- ``session_factory`` is MANDATORY. A probe that cannot reach the database can
  only report what it did not check, so the graph refuses to compile without
  one instead of degrading into placeholders.

Nodes retired from the graph, with the reason and the replacement:
- ``optional_bull_bear_debate``: RETIRED. The bull/bear debate is an LLM call
  (``debate_thesis``) that persists nothing, so a node could only fake a result
  or duplicate LLM spend. It is exposed for real by
  ``POST /api/thesis/{ticker}/debate``; the classic path stays its executor.
- ``publish``: RENAMED to ``persisted_thesis``. The graph does not publish. The
  node observes the classic path's persisted thesis version and only sets
  ``status="published"`` when that version is genuinely published; otherwise the
  run ends as ``approved``, which is exactly what a human approval buys.

Other invariants:
- The approval gate is a real ``interrupt()`` in its own node with no side
  effects before the interrupt (a node restarts from the beginning on resume);
  ``request_changes`` ends the run as ``changes_requested`` with the decision
  recorded in metadata.
- thread_id = thesis:{tenant_id}:{company_id}:{input_fingerprint}, so a
  Dramatiq retry resumes the same thread instead of starting a second thesis.
- The shadow comparison (``ThesisShadowService``) validates node order,
  idempotent retry and every probe observation against the classic persisted
  state on each run; divergences are recorded explicitly.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from app.core.tenancy import tenant_filters
from app.workflows.thesis_graph.state import ThesisGraphState

THESIS_GRAPH_NODES: tuple[str, ...] = (
    "resolve_company",
    "freeze_input_snapshot",
    "ensure_ingestion_complete",
    "build_fundamental_model",
    "deterministic_valuation",
    "draft_synthesis",
    "source_audit",
    "deterministic_red_team",
    "assemble_candidate",
    "approval_gate",
    "persisted_thesis",
)

APPROVAL_DECISIONS: tuple[str, ...] = ("approve", "request_changes")

# Probes that must run before the approval gate so the candidate is grounded.
CANDIDATE_INPUT_NODES: tuple[str, ...] = (
    "resolve_company",
    "ensure_ingestion_complete",
    "build_fundamental_model",
    "deterministic_valuation",
    "draft_synthesis",
    "source_audit",
    "deterministic_red_team",
)


def _require_company_id(state: ThesisGraphState, node: str) -> int:
    company_id = state.get("company_id")
    if not company_id:
        raise ValueError(f"{node} requires company_id")
    return int(company_id)


def _resolve_company_node(session_factory: Callable[[], Any]):
    """Real deterministic node: resolve the ticker to a Company.

    An unknown ticker raises - the run fails loudly and the checkpoint
    preserves progress; a company is never invented.
    """

    def node(state: ThesisGraphState) -> dict:
        artifacts = dict(state.get("artifacts") or {})
        if "resolve_company" in artifacts:
            return {}
        from sqlalchemy import select

        from app.models import Company

        with session_factory() as db:
            company = db.scalar(
                select(Company).where(Company.ticker == (state.get("ticker") or "").upper())
            )
        if company is None:
            raise ValueError(f"unknown_company:{state.get('ticker')}")
        artifacts["resolve_company"] = f"company:{company.id}"
        return {
            "artifacts": artifacts,
            "completed_nodes": ["resolve_company"],
            "status": "running",
            "company_id": str(company.id),
        }

    node.__name__ = "resolve_company"
    return node


def _freeze_input_snapshot_node():
    """Real deterministic node: freeze a stable input fingerprint.

    Records a sha256 over (ticker, company_id, tenant_id) as the node
    artifact. A caller-provided input_fingerprint (e.g. the thread id seed)
    always wins; the node only fills it when absent.
    """

    def node(state: ThesisGraphState) -> dict:
        artifacts = dict(state.get("artifacts") or {})
        if "freeze_input_snapshot" in artifacts:
            return {}
        payload = "|".join(
            [
                (state.get("ticker") or "").upper(),
                str(state.get("company_id") or ""),
                str(state.get("tenant_id") or ""),
            ]
        )
        fingerprint = hashlib.sha256(payload.encode()).hexdigest()[:16]
        artifacts["freeze_input_snapshot"] = f"sha256:{fingerprint}"
        update: dict = {
            "artifacts": artifacts,
            "completed_nodes": ["freeze_input_snapshot"],
            "status": "running",
        }
        if not state.get("input_fingerprint"):
            update["input_fingerprint"] = fingerprint
        return update

    node.__name__ = "freeze_input_snapshot"
    return node


def _ensure_ingestion_complete_node(session_factory: Callable[[], Any]):
    """Real deterministic node: evidence coverage probe.

    Read-only: counts the persisted evidence the classic pipeline models
    from (financial facts, market prices, documents) and records the counts
    as the node artifact + state metadata. Zero coverage is an honest
    state, never an error; the node never triggers network ingestion (the
    classic ThesisService path owns that) and never claims completeness it
    cannot verify.
    """

    def node(state: ThesisGraphState) -> dict:
        artifacts = dict(state.get("artifacts") or {})
        if "ensure_ingestion_complete" in artifacts:
            return {}
        company_id = _require_company_id(state, "ensure_ingestion_complete")
        from sqlalchemy import func, select

        from app.models import Document, FinancialFact, MarketPrice

        with session_factory() as db:
            facts = db.scalar(
                select(func.count())
                .select_from(FinancialFact)
                .where(
                    FinancialFact.company_id == company_id,
                    *tenant_filters(db, FinancialFact),
                )
            ) or 0
            prices = db.scalar(
                select(func.count())
                .select_from(MarketPrice)
                .where(MarketPrice.company_id == company_id)
            ) or 0
            documents = db.scalar(
                select(func.count())
                .select_from(Document)
                .where(
                    Document.company_id == company_id,
                    *tenant_filters(db, Document),
                )
            ) or 0
        coverage = {"financial_facts": facts, "market_prices": prices, "documents": documents}
        artifacts["ensure_ingestion_complete"] = (
            f"evidence:facts={facts},prices={prices},docs={documents}"
        )
        meta = dict(state.get("meta") or {})
        meta["evidence_coverage"] = coverage
        return {
            "artifacts": artifacts,
            "completed_nodes": ["ensure_ingestion_complete"],
            "status": "running",
            "meta": meta,
        }

    node.__name__ = "ensure_ingestion_complete"
    return node


def _build_fundamental_model_node(session_factory: Callable[[], Any]):
    """Read-side deterministic node: latest fundamental model.

    Records the latest persisted FundamentalModelVersion as the artifact
    (version + input fingerprint prefix), or an honest ``model:none``.
    The graph never writes model artifacts: the classic ThesisService path
    builds and persists models.
    """

    def node(state: ThesisGraphState) -> dict:
        artifacts = dict(state.get("artifacts") or {})
        if "build_fundamental_model" in artifacts:
            return {}
        company_id = _require_company_id(state, "build_fundamental_model")
        from sqlalchemy import desc, select

        from app.models.entities import FundamentalModelVersion

        with session_factory() as db:
            model = db.scalar(
                select(FundamentalModelVersion)
                .where(FundamentalModelVersion.company_id == company_id)
                .order_by(desc(FundamentalModelVersion.version))
                .limit(1)
            )
        meta = dict(state.get("meta") or {})
        if model is None:
            artifacts["build_fundamental_model"] = "model:none"
            meta["fundamental_model"] = None
        else:
            artifacts["build_fundamental_model"] = (
                f"model:v{model.version}:{model.input_fingerprint[:12]}"
            )
            meta["fundamental_model"] = {
                "version": model.version,
                "status": model.status,
                "publishable": model.publishable,
                "framework_key": model.framework_key,
            }
        return {
            "artifacts": artifacts,
            "completed_nodes": ["build_fundamental_model"],
            "status": "running",
            "meta": meta,
        }

    node.__name__ = "build_fundamental_model"
    return node


def _deterministic_valuation_node(session_factory: Callable[[], Any]):
    """Read-side deterministic node: latest valuation snapshot.

    Records the latest persisted FundamentalValuationSnapshot id and
    fingerprint, or an honest ``valuation:none``. The graph never computes
    or writes valuations.
    """

    def node(state: ThesisGraphState) -> dict:
        artifacts = dict(state.get("artifacts") or {})
        if "deterministic_valuation" in artifacts:
            return {}
        company_id = _require_company_id(state, "deterministic_valuation")
        from sqlalchemy import desc, select

        from app.models.entities import FundamentalValuationSnapshot

        with session_factory() as db:
            snapshot = db.scalar(
                select(FundamentalValuationSnapshot)
                .where(FundamentalValuationSnapshot.company_id == company_id)
                .order_by(
                    desc(FundamentalValuationSnapshot.created_at),
                    desc(FundamentalValuationSnapshot.id),
                )
                .limit(1)
            )
        meta = dict(state.get("meta") or {})
        if snapshot is None:
            artifacts["deterministic_valuation"] = "valuation:none"
            meta["valuation_snapshot"] = None
        else:
            artifacts["deterministic_valuation"] = f"valuation:{snapshot.id}"
            meta["valuation_snapshot"] = {
                "id": snapshot.id,
                "fingerprint": snapshot.valuation_snapshot_fingerprint[:12],
                "current_price": (
                    float(snapshot.current_price)
                    if snapshot.current_price is not None
                    else None
                ),
            }
        return {
            "artifacts": artifacts,
            "completed_nodes": ["deterministic_valuation"],
            "status": "running",
            "meta": meta,
        }

    node.__name__ = "deterministic_valuation"
    return node


def _draft_synthesis_node(session_factory: Callable[[], Any]):
    """Read-side deterministic node: the latest persisted thesis draft.

    This is the observation of what ``ThesisService`` composed and saved
    (classic phase ``compose_thesis``): the newest ThesisVersion with its
    status, rating, confidence scores, section count and a stable digest of
    the markdown. An empty portfolio is an honest ``thesis:none``. The graph
    never composes prose and never writes a version.
    """

    def node(state: ThesisGraphState) -> dict:
        artifacts = dict(state.get("artifacts") or {})
        if "draft_synthesis" in artifacts:
            return {}
        company_id = _require_company_id(state, "draft_synthesis")
        from sqlalchemy import desc, func, select

        from app.models import ThesisSection, ThesisVersion

        with session_factory() as db:
            version = db.scalar(
                select(ThesisVersion)
                .where(ThesisVersion.company_id == company_id)
                .order_by(desc(ThesisVersion.version))
                .limit(1)
            )
            sections = 0
            if version is not None:
                sections = (
                    db.scalar(
                        select(func.count())
                        .select_from(ThesisSection)
                        .where(
                            ThesisSection.thesis_version_id == version.id,
                            *tenant_filters(db, ThesisSection),
                        )
                    )
                    or 0
                )
        meta = dict(state.get("meta") or {})
        if version is None:
            artifacts["draft_synthesis"] = "thesis:none"
            meta["thesis_draft"] = None
        else:
            digest = hashlib.sha256((version.thesis_markdown or "").encode()).hexdigest()[:12]
            artifacts["draft_synthesis"] = (
                f"thesis:v{version.version}:{version.status}:sections={sections}:sha={digest}"
            )
            meta["thesis_draft"] = {
                "version": version.version,
                "status": version.status,
                "rating": version.rating,
                "sections": sections,
                "markdown_sha256": digest,
                "data_confidence_score": version.data_confidence_score,
                "source_coverage_score": version.source_coverage_score,
            }
        return {
            "artifacts": artifacts,
            "completed_nodes": ["draft_synthesis"],
            "status": "running",
            "meta": meta,
        }

    node.__name__ = "draft_synthesis"
    return node


def _source_audit_node(session_factory: Callable[[], Any]):
    """Read-side deterministic node: evidence provenance audit.

    Records the observed distribution of persisted FinancialFact and
    Document rows by ``source_type`` (sorted, deterministic) plus the
    count of low-confidence facts (< 0.5). source_type is a free-form
    vocabulary (SEC, FMP, FRED, IR, seed, ...); the probe reports the
    observed distribution verbatim and never invents a classification.
    Read-only: the classic path owns audit interpretation; the graph
    never writes audit artifacts.
    """

    def node(state: ThesisGraphState) -> dict:
        artifacts = dict(state.get("artifacts") or {})
        if "source_audit" in artifacts:
            return {}
        company_id = _require_company_id(state, "source_audit")
        from sqlalchemy import func, select

        from app.models import Document, FinancialFact

        with session_factory() as db:
            fact_rows = db.execute(
                select(FinancialFact.source_type, func.count())
                .where(
                    FinancialFact.company_id == company_id,
                    *tenant_filters(db, FinancialFact),
                )
                .group_by(FinancialFact.source_type)
            ).all()
            doc_rows = db.execute(
                select(Document.source_type, func.count())
                .where(
                    Document.company_id == company_id,
                    *tenant_filters(db, Document),
                )
                .group_by(Document.source_type)
            ).all()
            low_confidence = db.scalar(
                select(func.count())
                .select_from(FinancialFact)
                .where(
                    FinancialFact.company_id == company_id,
                    FinancialFact.confidence < 0.5,
                    *tenant_filters(db, FinancialFact),
                )
            ) or 0
        facts_by_source = {str(src): count for src, count in fact_rows}
        docs_by_source = {str(src): count for src, count in doc_rows}
        facts_part = ",".join(f"{k}:{facts_by_source[k]}" for k in sorted(facts_by_source))
        docs_part = ",".join(f"{k}:{docs_by_source[k]}" for k in sorted(docs_by_source))
        artifacts["source_audit"] = (
            f"audit:facts={{{facts_part}}}|docs={{{docs_part}}}|lowconf={low_confidence}"
        )
        meta = dict(state.get("meta") or {})
        meta["source_audit"] = {
            "facts_by_source_type": facts_by_source,
            "documents_by_source_type": docs_by_source,
            "low_confidence_facts": low_confidence,
        }
        return {
            "artifacts": artifacts,
            "completed_nodes": ["source_audit"],
            "status": "running",
            "meta": meta,
        }

    node.__name__ = "source_audit"
    return node


def _deterministic_red_team_node(session_factory: Callable[[], Any]):
    """Read-side deterministic node: latest red-team run.

    Records the latest persisted RedTeamRun (id, status, score,
    prompt_version) as the node artifact + state metadata, or an honest
    ``redteam:none``. The graph never runs or writes red-team artifacts:
    the classic RedTeamService path owns them.
    """

    def node(state: ThesisGraphState) -> dict:
        artifacts = dict(state.get("artifacts") or {})
        if "deterministic_red_team" in artifacts:
            return {}
        company_id = _require_company_id(state, "deterministic_red_team")
        from sqlalchemy import desc, select

        from app.models.entities import RedTeamRun

        with session_factory() as db:
            run = db.scalar(
                select(RedTeamRun)
                .where(RedTeamRun.company_id == company_id)
                .order_by(desc(RedTeamRun.created_at), desc(RedTeamRun.id))
                .limit(1)
            )
        meta = dict(state.get("meta") or {})
        if run is None:
            artifacts["deterministic_red_team"] = "redteam:none"
            meta["red_team_run"] = None
        else:
            artifacts["deterministic_red_team"] = f"redteam:{run.id}:score={run.score}"
            meta["red_team_run"] = {
                "id": run.id,
                "status": run.status,
                "score": run.score,
                "prompt_version": run.prompt_version,
            }
        return {
            "artifacts": artifacts,
            "completed_nodes": ["deterministic_red_team"],
            "status": "running",
            "meta": meta,
        }

    node.__name__ = "deterministic_red_team"
    return node


def _assemble_candidate_node():
    """Real deterministic node: compose the approval candidate.

    No I/O and no writes: the candidate is a deterministic digest of the
    references the probes above already committed, so two runs that observed
    the same classic state produce the same candidate id. The artifact says
    exactly what it is - a reference bundle - and ``meta['candidate']`` carries
    the bundle itself so the approval interrupt can show a human what is being
    approved instead of an empty placeholder.
    """

    def node(state: ThesisGraphState) -> dict:
        artifacts = dict(state.get("artifacts") or {})
        if "assemble_candidate" in artifacts:
            return {}
        references = {
            name: artifacts[name]
            for name in CANDIDATE_INPUT_NODES
            if name in artifacts
        }
        missing = [name for name in CANDIDATE_INPUT_NODES if name not in references]
        if missing:
            raise ValueError(f"assemble_candidate missing probes: {missing}")
        digest = hashlib.sha256(
            "|".join(f"{name}={references[name]}" for name in sorted(references)).encode()
        ).hexdigest()[:16]
        artifacts["assemble_candidate"] = f"candidate:sha256:{digest}"
        meta = dict(state.get("meta") or {})
        meta["candidate"] = {
            "digest": digest,
            "ticker": (state.get("ticker") or "").upper() or None,
            "company_id": state.get("company_id"),
            "input_fingerprint": state.get("input_fingerprint"),
            "observations": references,
            "executor": "classic_thesis_service_path",
        }
        return {
            "artifacts": artifacts,
            "completed_nodes": ["assemble_candidate"],
            "status": "running",
            "meta": meta,
        }

    node.__name__ = "assemble_candidate"
    return node


def _approval_gate_node(state: ThesisGraphState) -> dict:
    """Real approval interrupt with an idempotent resume contract.

    Nothing mutates before ``interrupt()``: the payload only reads control
    state (a node restarts from the beginning on resume). The resume value
    must be ``{"decision": "approve"}`` or
    ``{"decision": "request_changes", "notes": <str>}``; the decision is
    recorded in ``meta.approval`` and as the node artifact (the decision
    itself IS the artifact - there is nothing pending about it).
    """
    artifacts = dict(state.get("artifacts") or {})
    if "approval_gate" in artifacts:
        # Idempotent re-delivery on an already-decided thread.
        return {}
    decision: dict[str, Any] = interrupt(
        {
            "type": "thesis_approval",
            "ticker": state.get("ticker"),
            "candidate_artifact": artifacts.get("assemble_candidate"),
            "candidate": (state.get("meta") or {}).get("candidate"),
            "completed_nodes": list(state.get("completed_nodes") or []),
            "expected_decisions": list(APPROVAL_DECISIONS),
        }
    ) or {}
    choice = decision.get("decision")
    if choice not in APPROVAL_DECISIONS:
        raise ValueError(f"approval decision must be one of {APPROVAL_DECISIONS}")
    artifacts["approval_gate"] = f"approval:{choice}"
    meta = dict(state.get("meta") or {})
    meta["approval"] = {
        "decision": choice,
        "notes": decision.get("notes"),
        "actor": decision.get("actor"),
    }
    return {
        "artifacts": artifacts,
        "completed_nodes": ["approval_gate"],
        "status": "running" if choice == "approve" else "changes_requested",
        "meta": meta,
    }


def _persisted_thesis_node(session_factory: Callable[[], Any]):
    """Read-side deterministic node (was ``publish``): publication state.

    The graph does not publish anything, so it does not claim to. This node
    observes the classic path's persisted thesis version and reports it
    verbatim:

    - published version  -> ``thesis_published:v{n}``, run ends ``published``
    - version, not published -> ``thesis_unpublished:v{n}:{status}``, ``approved``
    - no version at all -> ``thesis:none``, ``approved``

    An approval is therefore never reported as a publication that did not
    happen.
    """

    def node(state: ThesisGraphState) -> dict:
        artifacts = dict(state.get("artifacts") or {})
        if "persisted_thesis" in artifacts:
            return {}
        approval = (state.get("meta") or {}).get("approval") or {}
        if approval.get("decision") != "approve":
            raise ValueError("persisted_thesis requires an approve decision")
        company_id = _require_company_id(state, "persisted_thesis")
        from sqlalchemy import desc, select

        from app.models import ThesisVersion

        with session_factory() as db:
            version = db.scalar(
                select(ThesisVersion)
                .where(ThesisVersion.company_id == company_id)
                .order_by(desc(ThesisVersion.version))
                .limit(1)
            )
        meta = dict(state.get("meta") or {})
        if version is None:
            artifacts["persisted_thesis"] = "thesis:none"
            meta["published_thesis"] = None
            status = "approved"
        elif version.status == "published":
            artifacts["persisted_thesis"] = f"thesis_published:v{version.version}"
            meta["published_thesis"] = {"version": version.version, "status": version.status}
            status = "published"
        else:
            artifacts["persisted_thesis"] = (
                f"thesis_unpublished:v{version.version}:{version.status}"
            )
            meta["published_thesis"] = {"version": version.version, "status": version.status}
            status = "approved"
        return {
            "artifacts": artifacts,
            "completed_nodes": ["persisted_thesis"],
            "status": status,
            "meta": meta,
        }

    node.__name__ = "persisted_thesis"
    return node


def _route_after_approval(state: ThesisGraphState) -> str:
    approval = (state.get("meta") or {}).get("approval") or {}
    return "persisted_thesis" if approval.get("decision") == "approve" else END


# name -> node factory. Every entry is a REAL implementation; a node without a
# builder is a programming error, not a licence to emit a placeholder.
_NODE_BUILDERS: dict[str, Callable[[Callable[[], Any]], Callable[[ThesisGraphState], dict]]] = {
    "resolve_company": _resolve_company_node,
    "freeze_input_snapshot": lambda _session_factory: _freeze_input_snapshot_node(),
    "ensure_ingestion_complete": _ensure_ingestion_complete_node,
    "build_fundamental_model": _build_fundamental_model_node,
    "deterministic_valuation": _deterministic_valuation_node,
    "draft_synthesis": _draft_synthesis_node,
    "source_audit": _source_audit_node,
    "deterministic_red_team": _deterministic_red_team_node,
    "assemble_candidate": lambda _session_factory: _assemble_candidate_node(),
    "approval_gate": lambda _session_factory: _approval_gate_node,
    "persisted_thesis": _persisted_thesis_node,
}


def build_thesis_graph(checkpointer=None, session_factory=None):
    """Compile the thesis lifecycle graph with an optional checkpointer.

    Pass a LangGraph checkpointer (PostgresSaver in prod, SqliteSaver in
    tests). Without one the graph still compiles for shape/structure tests,
    but crash recovery, the approval interrupt and resume require a durable
    checkpointer.

    ``session_factory`` is a contextmanager factory yielding a SQLAlchemy
    Session. It is REQUIRED: every probe in this graph verifies something in
    the database, and a probe without a session could only report a
    placeholder. Compiling without one raises instead of degrading silently.
    """
    if session_factory is None:
        raise ValueError(
            "session_factory is required: the thesis graph nodes are read-side probes "
            "and must not compile into unverified placeholders"
        )
    if tuple(_NODE_BUILDERS) != THESIS_GRAPH_NODES:
        raise RuntimeError(
            f"graph nodes {THESIS_GRAPH_NODES} and node builders {tuple(_NODE_BUILDERS)} "
            "disagree: every node needs a real implementation"
        )
    graph = StateGraph(ThesisGraphState)
    for name, build_node in _NODE_BUILDERS.items():
        graph.add_node(name, build_node(session_factory))
    graph.add_edge(START, THESIS_GRAPH_NODES[0])
    for previous, following in zip(THESIS_GRAPH_NODES[:-1], THESIS_GRAPH_NODES[1:-1]):
        graph.add_edge(previous, following)
    graph.add_conditional_edges(
        "approval_gate",
        _route_after_approval,
        {"persisted_thesis": "persisted_thesis", END: END},
    )
    graph.add_edge("persisted_thesis", END)
    return graph.compile(checkpointer=checkpointer)