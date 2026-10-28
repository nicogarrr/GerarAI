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


def load_harness():
    import importlib.util
    spec = importlib.util.spec_from_file_location('harness_security', DATA_ENGINE_ROOT / 'scripts' / 'eval_cerebro_harness.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_untrusted_endpoint_rejected_before_catalogue(monkeypatch):
    import pytest
    h = load_harness()
    monkeypatch.setattr(h, '_get_json', lambda *args: pytest.fail('network must not run'))
    with pytest.raises(SystemExit, match='allowlist'):
        h.verify_free_model('https://untrusted.invalid/paid/v1', h.DEFAULT_MODEL)


def test_redirects_rejected():
    import pytest
    h = load_harness()
    with pytest.raises(SystemExit, match='redirección'):
        h.NoRedirects().redirect_request(None, None, 302, '', {}, 'https://untrusted.invalid/')


def test_external_provider_disabled_before_app_or_network(monkeypatch):
    import pytest
    h = load_harness()
    monkeypatch.setattr(h, '_get_json', lambda *args: pytest.fail('network must not run'))
    with pytest.raises(SystemExit, match='deshabilitado'):
        h.build_zen_provider(h.DEFAULT_BASE_URL, h.DEFAULT_MODEL)


def test_cli_overrides_production_environment(monkeypatch, tmp_path):
    h = load_harness()
    for key, value in [('APP_ENV', 'production'), ('WORKERS_ENABLED', 'true'), ('RESEARCH_AUTH_REQUIRED', 'true')]:
        monkeypatch.setenv(key, value)
    async def fake(args):
        import os
        assert os.environ['APP_ENV'] == 'test'
        assert os.environ['WORKERS_ENABLED'] == 'false'
        assert os.environ['RESEARCH_AUTH_REQUIRED'] == 'false'
        return {'summary': {'failed': 0}}
    monkeypatch.setattr(h, 'run_suite', fake)
    monkeypatch.setattr(sys, 'argv', ['eval_cerebro_harness.py'])
    assert h.main() == 0
