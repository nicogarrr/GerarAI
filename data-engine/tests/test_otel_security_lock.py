"""The resolved trace-context parser includes the CVE-2026-126360 fix."""

import tomllib
from pathlib import Path


def test_otel_api_lock_includes_traceparent_redos_fix():
    lock = tomllib.loads((Path(__file__).resolve().parents[1] / 'uv.lock').read_text())
    package = next(p for p in lock['package'] if p['name'] == 'opentelemetry-api')
    assert tuple(map(int, package['version'].split('.'))) >= (1, 45, 2)
