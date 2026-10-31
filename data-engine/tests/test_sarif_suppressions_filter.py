"""Contrato del filtro SARIF de supresiones (scripts/filter_sarif_suppressions.py).

Cubre los casos que decidio el piloto: solo se elimina un result con al menos
una supresion inSource accepted (o sin status); se conservan suppressions
ausente, array vacio, kind external y status rejected/underReview.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "filter_sarif_suppressions.py"


def _result(rule: str, suppressions: list[dict] | None = None) -> dict:
    result = {
        "ruleId": rule,
        "message": {"text": rule},
        "locations": [
            {
                "physicalLocation": {
                    "artifactLocation": {"uri": "a.py"},
                    "region": {"startLine": 1},
                }
            }
        ],
    }
    if suppressions is not None:
        result["suppressions"] = suppressions
    return result


def _sarif(results: list[dict]) -> dict:
    return {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [{"tool": {"driver": {"name": "semgrep", "rules": []}}, "results": results}],
    }


CASES = [
    # (id del caso, suppressions, se_elimina)
    ("sin-suppressions", None, False),
    ("suppressions-vacio", [], False),
    ("insource-sin-status", [{"kind": "inSource"}], True),
    ("insource-accepted", [{"kind": "inSource", "status": "accepted"}], True),
    ("insource-rejected", [{"kind": "inSource", "status": "rejected"}], False),
    ("insource-underReview", [{"kind": "inSource", "status": "underReview"}], False),
    ("external-accepted", [{"kind": "external", "status": "accepted"}], False),
    (
        "mixta-rejected-y-accepted",
        [{"kind": "inSource", "status": "rejected"}, {"kind": "inSource", "status": "accepted"}],
        True,
    ),
]


def test_cada_caso_se_filtra_como_toca(tmp_path: Path) -> None:
    sarif = _sarif([_result(rule, sup) for rule, sup, _ in CASES])
    src = tmp_path / "in.sarif"
    src.write_text(json.dumps(sarif), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), str(src)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    out = json.loads(src.read_text(encoding="utf-8"))
    kept_rules = {r["ruleId"] for r in out["runs"][0]["results"]}
    expected_kept = {rule for rule, _, dropped in CASES if not dropped}
    expected_dropped = {rule for rule, _, dropped in CASES if dropped}
    assert kept_rules == expected_kept, f"kept={kept_rules} expected={expected_kept}"
    assert str(len(expected_dropped)) in proc.stdout


def test_idempotente(tmp_path: Path) -> None:
    sarif = _sarif([_result(rule, sup) for rule, sup, _ in CASES])
    src = tmp_path / "in.sarif"
    src.write_text(json.dumps(sarif), encoding="utf-8")
    for _ in range(2):
        subprocess.run([sys.executable, str(SCRIPT), str(src)], check=True, capture_output=True)
    once = json.loads(src.read_text(encoding="utf-8"))
    kept_rules = {r["ruleId"] for r in once["runs"][0]["results"]}
    assert kept_rules == {rule for rule, _, dropped in CASES if not dropped}
