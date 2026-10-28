"""scripts/coverage_by_feature.py: agrupa coverage.json por funcionalidad y nunca falla."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ENGINE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE_ROOT / "scripts"))

import coverage_by_feature as cbf  # noqa: E402


def _file(stmts: int, covered: int, branches: int = 0, covered_branches: int = 0) -> dict:
    return {"summary": {
        "num_statements": stmts, "covered_lines": covered, "missing_lines": stmts - covered,
        "num_branches": branches, "covered_branches": covered_branches,
        "missing_branches": branches - covered_branches,
        "percent_covered": 100.0 * (covered + covered_branches) / max(1, stmts + branches),
    }}


def test_classify_por_prioridad():
    assert cbf.classify("app/services/tax_report_service.py") == "impuestos (IRPF/720)"
    assert cbf.classify("app/api/routes/taxes.py") == "impuestos (IRPF/720)"
    assert cbf.classify("app/services/dca_signal_engine.py") == "DCA"
    assert cbf.classify("app/api/routes/portfolio.py") == "cartera/tearsheet"
    assert cbf.classify("app/services/tearsheet_service.py") == "cartera/tearsheet"
    assert cbf.classify("app/core/auth.py") == "auth/tenancy"
    assert cbf.classify("app/api/routes/thesis_scenarios.py") == "tesis"
    assert cbf.classify("app/workers/dramatiq_app.py") == cbf.OTHER


def test_summarize_combina_lineas_y_ramas_e_ignora_lo_que_no_es_app():
    data = {"files": {
        "app/services/tax_a.py": _file(10, 9, 4, 2),
        "app/api/routes/taxes.py": _file(10, 10),
        "alembic/versions/0001.py": _file(50, 0),
    }}
    out = cbf.summarize(data)
    taxes = out["impuestos (IRPF/720)"]
    assert (taxes["statements"], taxes["covered"]) == (20, 19)
    assert (taxes["branches"], taxes["covered_branches"]) == (4, 2)
    assert taxes["percent"] == round(100 * 21 / 24, 2)
    assert taxes["files"][0]["path"] == "app/services/tax_a.py"  # el de mas hueco primero
    assert all(not k.startswith("alembic") for f in out.values() for k in (r["path"] for r in f["files"]))


def test_main_sin_medicion_sale_0(tmp_path, capsys):
    assert cbf.main(["--input", str(tmp_path / "no.json")]) == 0
    assert "sin" in capsys.readouterr().out


def test_main_markdown_y_json(tmp_path, capsys):
    src = tmp_path / "coverage.json"
    src.write_text(json.dumps({"files": {"app/core/auth.py": _file(4, 2)}}), encoding="utf-8")
    dump = tmp_path / "out.json"
    assert cbf.main(["--input", str(src), "--markdown", "--json", str(dump)]) == 0
    md = capsys.readouterr().out
    assert "| auth/tenancy | 50.0% |" in md
    assert json.loads(dump.read_text(encoding="utf-8"))["auth/tenancy"]["statements"] == 4
