"""Guard install stages, not screenshot output: apt stalls must be identifiable."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def steps():
    workflow = yaml.safe_load((ROOT / ".github/workflows/visual-regression.yml").read_text())
    return workflow["jobs"]["shots"]["steps"]


def test_system_dependencies_have_their_own_bounded_budget_even_on_cache_hit():
    stage = next(s for s in steps() if s.get("run") == "npx playwright install-deps chromium")
    assert stage["timeout-minutes"] == 15
    assert "if" not in stage
    assert "continue-on-error" not in stage


def test_download_is_bounded_and_skipped_only_for_exact_browser_cache_hit():
    stage = next(s for s in steps() if s.get("run") == "npx playwright install chromium")
    assert stage["if"] == "steps.pw-cache.outputs.cache-hit != 'true'"
    assert stage["timeout-minutes"] == 8
    assert "continue-on-error" not in stage


def test_browser_cache_matches_installed_playwright_version():
    all_steps = steps()
    cache = next(s for s in all_steps if s.get("id") == "pw-cache")
    assert cache["uses"].startswith("actions/cache@")
    assert cache["with"]["path"] == "~/.cache/ms-playwright"
    assert cache["with"]["key"] == "playwright-${{ runner.os }}-${{ steps.pw.outputs.version }}"
    assert "restore-keys" not in cache["with"]
    assert any(s.get("id") == "pw" and "@playwright/test/package.json" in s["run"] for s in all_steps)


def test_install_order_keeps_failures_before_screenshots():
    commands = [s.get("run", "") for s in steps()]
    system = commands.index("npx playwright install-deps chromium")
    download = commands.index("npx playwright install chromium")
    shots = commands.index("npx playwright test visual-public --reporter=line")
    assert system < download < shots
    assert not any("install --with-deps" in command for command in commands)


def test_screenshots_are_not_silently_allowed_to_fail():
    stage = next(s for s in steps() if s.get("run") == "npx playwright test visual-public --reporter=line")
    assert "if" not in stage
    assert "continue-on-error" not in stage
