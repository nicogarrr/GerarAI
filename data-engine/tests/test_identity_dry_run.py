"""The identity handoff is an offline plan, never an account mutation."""
from copy import deepcopy

import pytest

from app.services.identity_dry_run import build_plan


def evidence():
    return {"url": "https://exchange.example/security", "kind": "primary", "checked_at": "2026-11-11",
            "quote": "QA fixture, not a real listing"}


def row():
    return {"ticker": "TEST.AS", "name": "Test NV", "isin": "NL0015002MS2", "mic": "XAMS",
            "quote_unit": "EUR", "evidence": {k: evidence() for k in ("ticker", "name", "isin", "mic", "quote_unit")}}


def test_missing_company_is_only_a_proposed_normal_add():
    result = build_plan([row()], {"companies": []})
    assert result["mode"] == "offline_read_only"
    assert result["writes_performed"] == 0
    assert result["items"][0]["status"] == "evidence_complete_for_review"
    assert result["items"][0]["next_step"] == "normal_watchlist_add_by_pilot_after_review"


@pytest.mark.parametrize("field,value", [("isin", "MX01GC2M0"), ("mic", "PARIS"), ("quote_unit", "GEL/USD"), ("name", ""), ("ticker", "")])
def test_invalid_identity_is_blocked(field, value):
    item = row()
    item[field] = value
    assert build_plan([item], {})["items"][0]["status"] == "blocked"


@pytest.mark.parametrize("field", ["ticker", "name", "isin", "mic", "quote_unit"])
def test_missing_primary_source_blocks(field):
    item = row()
    item["evidence"].pop(field)
    assert build_plan([item], {})["items"][0]["status"] == "blocked"


def test_secondary_evidence_does_not_upgrade_identity():
    item = row()
    item["evidence"]["isin"]["kind"] = "secondary"
    assert build_plan([item], {})["items"][0]["status"] == "blocked"


def test_conflicting_existing_isin_is_never_overwritten():
    result = build_plan([row()], {"companies": [{"ticker": "TEST.AS", "isin": "GB00BJDQQ870"}]})
    assert result["items"][0]["status"] == "blocked"
    assert "existing_isin_conflict" in result["items"][0]["gaps"]


def test_existing_identity_without_facts_proposes_refresh_only():
    result = build_plan([row()], {"companies": [{"ticker": "TEST.AS", "isin": "NL0015002MS2", "facts_by_source": []}]})
    assert result["items"][0]["next_step"] == "existing_company_refresh_by_pilot_after_review"


def test_inputs_are_not_modified():
    rows, snapshot = [row()], {"companies": []}
    before = deepcopy((rows, snapshot))
    build_plan(rows, snapshot)
    assert (rows, snapshot) == before


def test_duplicate_ticker_blocks_both_rows():
    assert all(item["status"] == "blocked" for item in build_plan([row(), row()], {})["items"])


def test_cli_is_offline_and_preserves_inputs(tmp_path):
    import json
    import os
    import subprocess
    import sys
    from pathlib import Path

    manifest, snapshot = tmp_path / "manifest.json", tmp_path / "snapshot.json"
    manifest.write_text(json.dumps([row()]))
    snapshot.write_text(json.dumps({"companies": []}))
    before = (manifest.read_bytes(), snapshot.read_bytes())
    script = Path(__file__).parents[1] / "scripts" / "identity_dry_run.py"
    env = {**os.environ, "PYTHONPATH": str(script.parents[1])}
    result = subprocess.run([sys.executable, str(script), "--manifest", str(manifest), "--snapshot", str(snapshot)],
                            capture_output=True, text=True, env=env, check=True)
    assert json.loads(result.stdout)["network_requests"] == 0
    assert before == (manifest.read_bytes(), snapshot.read_bytes())
    refused = subprocess.run([sys.executable, str(script), "--apply"], capture_output=True, env=env)
    assert refused.returncode != 0
