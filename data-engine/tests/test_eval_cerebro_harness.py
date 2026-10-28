"""El arnés del Cerebro en modo stub (sin red ni claves) pasa la suite entera.

Modo stub = el LLM esta caido: la red de seguridad determinista debe responder
las 18 preguntas verificables sin inventar cifras, sin filtrar al tenant 2 y
con los degradados honestos. Corre el script real por subproceso para probar
el mismo punto de entrada que usa Nico.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

DATA_ENGINE_ROOT = Path(__file__).resolve().parents[1]


def test_cerebro_harness_stub_suite_passes(tmp_path):
    report = tmp_path / "report.json"
    proc = subprocess.run(
        [
            sys.executable,
            str(DATA_ENGINE_ROOT / "scripts" / "eval_cerebro_harness.py"),
            "--provider", "stub",
            "--report", str(report),
        ],
        cwd=DATA_ENGINE_ROOT,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert proc.returncode == 0, f"arnés en rojo:\n{proc.stdout}\n{proc.stderr}"
    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["summary"]["failed"] == 0
    assert data["summary"]["total"] == 18
    assert data["actual_list_price_eur"] == 0.0
