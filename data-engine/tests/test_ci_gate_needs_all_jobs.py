"""El job `gate` de CI («CI gate (single required check)») depende de TODOS los jobs.

Revisión GerarAI, hallazgo A1: el gate es el check que la protección de main debe exigir.
Su `needs:` se mantiene a mano y el propio workflow avisa de que un job olvidado ahí
deja el gate en verde con ese job en rojo. Este guard lo convierte en un fallo de CI.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

CI = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci.yml"


def _jobs() -> dict[str, Any]:
    data = yaml.safe_load(CI.read_text(encoding="utf-8"))
    return data["jobs"]


def test_gate_existe_y_corre_siempre():
    gate = _jobs()["gate"]
    assert gate["name"] == "CI gate (single required check)"
    assert "always()" in str(gate.get("if", ""))


def test_gate_depende_de_todos_los_jobs():
    jobs = _jobs()
    needs = jobs["gate"].get("needs") or []
    needs = [needs] if isinstance(needs, str) else list(needs)
    faltan = sorted(set(jobs) - {"gate"} - set(needs))
    assert faltan == [], f"jobs de ci.yml que el gate no vigila (añádelos a gate.needs): {faltan}"


def test_lint_backend_con_pyright_forma_parte_del_gate():
    jobs = _jobs()
    pasos = " ".join(str(s.get("run", "")) for s in jobs["backend-lint"]["steps"])
    assert "pyright" in pasos and "ruff check" in pasos
    assert "backend-lint" in jobs["gate"]["needs"]
