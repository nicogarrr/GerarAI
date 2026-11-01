"""Workflow catalog: what ``POST /api/workflows/{name}/run`` REALLY executes.

Honesty rules this file enforces (see tests/test_workflow_truth.py):
- Every entry in ``WORKFLOW_CATALOG`` is executable through the API
  (``api_executable: True``) and declares ``implementation_status:
  "implemented"``. There is no ``partial`` and no ``descriptive`` entry: a
  concept without an execution route does not belong in a list that a screen
  renders as "ejecutable".
- ``steps`` are the steps THIS endpoint executes. ``pipeline_steps`` (when
  present) are the broader stages of the service or scheduled job it delegates
  to; they are not steps of ``/run`` and are labelled as such.
- Anything with no API route lives in ``RETIRED_WORKFLOWS`` with the reason and
  the real replacement, and disappears from ``GET /api/workflows``.
"""

WORKFLOW_CATALOG = [
    {
        "name": "ThesisShadowComparisonWorkflow",
        "implementation_status": "implemented",
        "api_executable": True,
        "truth": "POST /run executes the stage-6 shadow comparison: runs the LangGraph thesis graph under a checkpointer (control state + read-side probes), verifies node order + idempotent retry, maps classic THESIS_PHASES to graph nodes, compares every probe observation against the classic persisted state, and records divergences in a durable WorkflowRun. Every graph node is a real read-side probe or a real approval interrupt: none emits a pending placeholder. The classic ThesisService path remains the sole LLM/write executor; the shadow never mutates domain artifacts.",
        "execution_mode": "shadow",
        "input": "ticker",
        "steps": [
            "run_graph_shadow",
            "verify_idempotent_retry",
            "map_classic_phases",
            "compare_probe_observations",
            "persist_comparison",
        ],
    },
    {
        "name": "ThesisApprovalWorkflow",
        "implementation_status": "implemented",
        "api_executable": True,
        "truth": "POST /run executes the stage-6 thesis graph under a durable checkpointer until the real approval_gate interrupt and returns thread_id + approval payload (status awaiting_approval). POST /decide resumes the same thread with approve/request_changes. The graph writes control state only: assemble_candidate digests the read-side probe observations and persisted_thesis reports the classic path's publication state, so no domain publish happens inside the graph and the classic ThesisService path remains the sole LLM/write executor. An approval ends the run as approved, or as published only when a published thesis version really exists.",
        "execution_mode": "pilot",
        "input": "ticker",
        "steps": [
            "run_until_approval_gate",
            "persist_checkpoint",
            "await_human_decision",
            "resume_with_decision",
        ],
    },
    {
        "name": "GenerateThesisWorkflow",
        "implementation_status": "implemented",
        "api_executable": True,
        "truth": "POST /run executes ThesisService.generate() synchronously in ONE transaction; the single recorded step is generate_thesis and pipeline_steps are ThesisService's internal phases, not steps of this endpoint. There is no mid-flow resume here: for background generation use POST /api/thesis/generate-async, which enqueues a real WorkflowRun on Dramatiq. Langfuse: shadow tracing is optional (flag LANGFUSE_ENABLED), metadata only, never a source of truth.",
        "execution_mode": "deterministic",
        "input": "ticker",
        "steps": ["generate_thesis"],
        "pipeline_steps": [
            "resolve_ticker",
            "load_company_master",
            "fetch_SEC/FMP/IR/GDELT",
            "store_raw_documents",
            "extract_text_and_tables",
            "chunk_documents",
            "embed_to_Qdrant",
            "normalize_financial_facts",
            "build_historical_model",
            "select_valuation_method",
            "generate_assumptions",
            "run_python_valuation",
            "run_reverse_dcf",
            "analyze_calls",
            "detect_catalysts",
            "red_team",
            "source_audit",
            "write_thesis",
            "save_thesis_version",
        ],
        "pipeline_owner": "ThesisService.generate (in-process, one transaction)",
    },
    {
        "name": "DailyResearchWorkflow",
        "implementation_status": "implemented",
        "api_executable": True,
        "truth": "POST /run executes exactly ONE stage: ingesting the supplied news_items via NewsService. The rest of the daily pipeline (portfolio sync, materiality classification, claims, daily brief, risk dashboard) runs as scheduled work (scheduler job_id=daily_research and its Dramatiq actors), not through this endpoint, and is listed as pipeline_steps. Without params.news_items the endpoint answers 422 instead of pretending to run a daily cycle. POST /api/news/ingest does the same ingestion without the workflow envelope.",
        "execution_mode": "deterministic",
        "input": "params.news_items",
        "steps": ["ingest_news_items"],
        "pipeline_steps": [
            "sync_IBKR",
            "fetch_news_for_portfolio",
            "deduplicate_news",
            "classify_materiality",
            "extract_claims",
            "link_to_thesis",
            "create_alerts",
            "generate_daily_brief",
            "update_risk_dashboard",
        ],
        "pipeline_owner": "scheduler job_id=daily_research (Dramatiq), not POST /run",
    },
    {
        "name": "EarningsWorkflow",
        "implementation_status": "implemented",
        "api_executable": True,
        "truth": "POST /run executes EarningsWorkflowService via a 2-node MAF wrapper (load_context + execute_earnings_review); pipeline_steps describe the service's stages, not the graph. EarningsRun persists running->completed/failed. POST /api/earnings/{ticker}/run is the same capability outside the workflow envelope.",
        "execution_mode": "microsoft_agent_framework",
        "input": "ticker + earnings docs",
        "steps": [
            "load_earnings_context",
            "execute_earnings_review",
        ],
        "pipeline_steps": [
            "ingest_earnings_release",
            "extract_reported_numbers",
            "reconcile_SEC/FMP/company_release",
            "compare_vs_previous_period",
            "extract_guidance",
            "analyze_call",
            "update_management_claim_tracker",
            "update_assumptions",
            "rerun_valuation",
            "red_team",
            "source_audit",
            "generate_thesis_diff",
            "save_new_version",
        ],
        "pipeline_owner": "EarningsWorkflowService.run (in-process)",
    },
    {
        "name": "RedTeamWorkflow",
        "implementation_status": "implemented",
        "api_executable": True,
        "truth": "POST /run executes RedTeamService (DETERMINISTIC rules over claims/evidence/valuation) via a 2-node MAF wrapper; pipeline_steps are the service's checks, not graph nodes. It is not an autonomous agent: the MAF mode is only the wrapper around the graph.",
        "execution_mode": "microsoft_agent_framework",
        "input": "ticker",
        "steps": [
            "load_review_evidence",
            "execute_adversarial_review",
        ],
        "pipeline_steps": [
            "load_current_thesis",
            "load_supporting_and_contradictory_evidence",
            "check_unsupported_material_claims",
            "compare_ROIC_vs_WACC",
            "analyze_moat_and_peers",
            "attack_assumptions",
            "build_strongest_bear_case",
            "define_falsification_tests",
            "create_review_and_alert",
        ],
        "pipeline_owner": "RedTeamService.run (in-process, deterministic)",
    },
    {
        "name": "ExpertTeamThesisWorkflow",
        "implementation_status": "implemented",
        "api_executable": True,
        "feature_flag": "EXPERT_TEAM_ENABLED",
        "truth": "Only with EXPERT_TEAM_ENABLED=true (default off: the entry is not listed and /run answers 404 without running or recording anything). POST /run plans the expert team for the ticker (fundamental, valuation, risk, news; tax only if the caller holds the position) and runs it: each expert reads ONLY its whitelisted read-only tools filtered by the caller's tenant, makes one LLM call with its versioned prompt (expert_*), and every claim must cite evidence returned in that run with its numbers inside the cited data, or it is dropped. Stance conflicts go to the debate judge prompt. The result (sections, sources, conflicts, verdict) is returned and stored in the workflow run; it does NOT write a ThesisVersion and does not replace GenerateThesisWorkflow.",
        "execution_mode": "expert_team",
        "input": "ticker",
        "steps": ["plan_experts", "run_expert_team"],
        "pipeline_steps": [
            "gather_read_only_evidence",
            "expert_llm_call",
            "validate_citations",
            "merge_sources",
            "detect_conflicts",
            "judge_stance_conflict",
        ],
        "pipeline_owner": "ExpertTeam.run (app/services/expert_team, in-process)",
    },
]

# Concepts that were advertised here without an execution route. They are not
# in GET /api/workflows any more; the API answers 404 for them with the reason
# and the replacement below, so a client that still asks gets a true answer.
RETIRED_WORKFLOWS = [
    {
        "name": "ManualNewsWorkflow",
        "reason": "No execution route of its own: manual news ingestion is served end to end by POST /api/news/manual, with its own real stages (dedup, materiality classification, review). Listing a 12-step pipeline here announced stages that never ran.",
        "replaced_by": "POST /api/news/manual",
    },
    {
        "name": "ChatWorkflow",
        "reason": "The chat has its own route and its own synthesis service; it is not a workflow of /api/workflows and never was one.",
        "replaced_by": "POST /api/chat",
    },
    {
        "name": "ContradictionWorkflow",
        "reason": "Contradiction scanning is real, but it runs from POST /api/reviews/contradictions/scan and from the scheduled contradiction_scan job, never from POST /run.",
        "replaced_by": "POST /api/reviews/contradictions/scan",
    },
    {
        "name": "DeepResearchWorkflow",
        "reason": "There is no deep-research pipeline (plan, primary sources, cited synthesis, evaluation) in this codebase. POST /api/research/assistant answers from persisted structured data only and is NOT equivalent, so it is named as a pointer, not as the same capability.",
        "replaced_by": "POST /api/research/assistant",
    },
    {
        "name": "ThesisReviewWorkflow",
        "reason": "Thesis reviews are produced by the real flows that create them (earnings, red team, contradiction scans) and resolved with PATCH /api/reviews/{review_id}; no /run route dispatches a review on its own.",
        "replaced_by": "PATCH /api/reviews/{review_id}",
    },
]

API_EXECUTABLE_WORKFLOWS = frozenset(
    workflow["name"] for workflow in WORKFLOW_CATALOG if workflow.get("api_executable")
)
RETIRED_WORKFLOW_NAMES = frozenset(entry["name"] for entry in RETIRED_WORKFLOWS)


def find_workflow(name: str) -> dict | None:
    return next((w for w in WORKFLOW_CATALOG if w["name"] == name), None)


def find_retired(name: str) -> dict | None:
    return next((w for w in RETIRED_WORKFLOWS if w["name"] == name), None)


def flag_enabled(workflow: dict) -> bool:
    """Una entrada con ``feature_flag`` solo existe hacia fuera con su flag encendido."""
    flag = workflow.get("feature_flag")
    if not flag:
        return True
    from app.core.config import get_settings

    return bool(getattr(get_settings(), str(flag).lower(), False))


def visible_catalog() -> list[dict]:
    """El catálogo que ve GET /api/workflows: sin las entradas con flag apagado."""
    return [workflow for workflow in WORKFLOW_CATALOG if flag_enabled(workflow)]
