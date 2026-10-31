"""The workflow catalog and the run endpoint never overstate what they do.

Every workflow in GET /api/workflows is executable through POST /run, and
every workflow that is not executable is retired with a reason and a real
replacement instead of being advertised.
"""


import main
from app.workflows.catalog import (
    RETIRED_WORKFLOW_NAMES,
    RETIRED_WORKFLOWS,
    WORKFLOW_CATALOG,
    find_workflow,
)
from tests.auth_helpers import csrf_client

client = csrf_client(main.app)


def test_no_workflow_exposes_partial_or_descriptive():
    """La lista que la pagina pinta como 'ejecutable' no puede mentir."""
    for workflow in WORKFLOW_CATALOG:
        assert workflow["implementation_status"] == "implemented", workflow["name"]
        assert workflow.get("api_executable") is True, workflow["name"]


def test_every_catalog_entry_declares_implementation_status():
    for workflow in WORKFLOW_CATALOG:
        assert workflow.get("implementation_status") in {"implemented"}, workflow["name"]
        assert workflow.get("truth"), workflow["name"]


def test_catalog_has_no_fake_langfuse_steps():
    for workflow in WORKFLOW_CATALOG:
        assert "trace_to_langfuse" not in workflow["steps"], workflow["name"]


def test_catalog_steps_are_the_executed_steps_not_the_service_pipeline():
    """`steps` es lo que /run ejecuta; `pipeline_steps` es la etapa delegada."""
    for workflow in WORKFLOW_CATALOG:
        assert workflow["steps"], workflow["name"]
        assert all(isinstance(step, str) and step for step in workflow["steps"]), workflow["name"]
        pipeline = set(workflow.get("pipeline_steps") or [])
        if pipeline:
            assert workflow.get("pipeline_owner"), workflow["name"]


def test_retired_workflows_are_not_in_the_executable_list():
    for name in RETIRED_WORKFLOW_NAMES:
        assert find_workflow(name) is None, name
        assert name not in {w["name"] for w in WORKFLOW_CATALOG}, name


def test_every_retired_workflow_documents_reason_and_replacement():
    for entry in RETIRED_WORKFLOWS:
        assert entry["reason"], entry["name"]
        assert entry["replaced_by"], entry["name"]


def test_catalog_endpoint_lists_only_executable_workflows():
    body = client.get("/api/workflows").json()
    names = {w["name"] for w in body["workflows"]}
    assert names == {w["name"] for w in WORKFLOW_CATALOG}
    assert not names & RETIRED_WORKFLOW_NAMES
    for workflow in body["workflows"]:
        assert workflow["implementation_status"] == "implemented"
        assert workflow["api_executable"] is True
    # La parte aditiva: la pagina puede explicar la lista en vez de callarse.
    assert {entry["name"] for entry in body["retired_workflows"]} == RETIRED_WORKFLOW_NAMES


def test_retired_workflow_run_fails_explicitly_with_its_replacement():
    """Nada de 200 con un pending: 404 que explica la retirada y el sustituto."""
    for entry in RETIRED_WORKFLOWS:
        response = client.post(f"/api/workflows/{entry['name']}/run", json={"params": {}})
        assert response.status_code == 404, entry["name"]
        detail = response.json()["detail"]
        assert entry["replaced_by"] in detail, entry["name"]
        assert "queued" not in detail.lower()


def test_retired_workflow_detail_is_a_404_with_the_reason():
    response = client.get("/api/workflows/DeepResearchWorkflow")
    assert response.status_code == 404
    assert "POST /api/research/assistant" in response.json()["detail"]


def test_unknown_workflow_still_404s_plainly():
    response = client.get("/api/workflows/NoSuchWorkflow")
    assert response.status_code == 404
    assert response.json()["detail"] == "Workflow 'NoSuchWorkflow' not found"


def test_executable_workflow_without_ticker_422s_instead_of_faking_a_run():
    for name in ("GenerateThesisWorkflow", "RedTeamWorkflow", "EarningsWorkflow"):
        response = client.post(f"/api/workflows/{name}/run", json={"ticker": None, "params": {}})
        assert response.status_code == 422, name
        assert "requires a ticker" in response.json()["detail"], name


def test_daily_research_without_news_items_422s_instead_of_faking_a_cycle():
    response = client.post("/api/workflows/DailyResearchWorkflow/run", json={"params": {}})
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "news_items" in detail
    assert "daily_research" in detail


def test_run_of_an_unknown_workflow_404s():
    response = client.post("/api/workflows/NoSuchWorkflow/run", json={"params": {}})
    assert response.status_code == 404


def test_catalog_entry_without_api_execution_route_501s(monkeypatch):
    """Guard del contrato: si alguien mete una entrada no ejecutable, 501."""
    import app.workflows.catalog as catalog

    ghost = {
        "name": "GhostWorkflow",
        "implementation_status": "implemented",
        "api_executable": False,
        "truth": "Existe en el catalogo pero ningun worker consume la peticion.",
        "execution_mode": "deterministic",
        "input": "ticker",
        "steps": ["do_nothing"],
    }
    monkeypatch.setattr(catalog, "WORKFLOW_CATALOG", [*catalog.WORKFLOW_CATALOG, ghost])
    monkeypatch.setattr(
        "app.api.routes.workflows.WORKFLOW_CATALOG", catalog.WORKFLOW_CATALOG
    )

    listed = client.get("/api/workflows").json()["workflows"]
    assert "GhostWorkflow" in {w["name"] for w in listed}

    response = client.post("/api/workflows/GhostWorkflow/run", json={"ticker": "AAPL", "params": {}})
    assert response.status_code == 501
    detail = response.json()["detail"]
    assert "no execution route via the API" in detail
    assert "queued" not in detail.lower()


def test_decide_is_only_for_the_approval_workflow():
    assert client.post(
        "/api/workflows/GenerateThesisWorkflow/decide",
        json={"thread_id": "x", "decision": "approve"},
    ).status_code == 404
    assert client.post(
        "/api/workflows/DeepResearchWorkflow/decide",
        json={"thread_id": "x", "decision": "approve"},
    ).status_code == 404
    assert client.post(
        "/api/workflows/ThesisApprovalWorkflow/decide",
        json={"thread_id": "x", "decision": "maybe"},
    ).status_code == 422


def test_catalog_entry_detail_still_exposes_steps_and_truth():
    body = client.get("/api/workflows/GenerateThesisWorkflow").json()
    assert body["name"] == "GenerateThesisWorkflow"
    assert body["steps"] == ["generate_thesis"]
    assert body["pipeline_steps"]
    assert body["truth"]


def test_red_team_is_documented_as_deterministic():
    workflow = next(w for w in WORKFLOW_CATALOG if w["name"] == "RedTeamWorkflow")
    assert "DETERMINIST" in workflow["truth"].upper()