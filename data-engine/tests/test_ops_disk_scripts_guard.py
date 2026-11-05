"""Snapshot inspection must be read-only and preserve complete sets."""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ROTATE = ROOT / "scripts/ops/rotate-predeploy-snapshots.sh"
DISK = ROOT / "scripts/ops/check-disk-space.sh"
SPEC = importlib.util.spec_from_file_location("inventory", ROOT / "scripts/ops/snapshot_inventory.py")
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_bash_valid():
    for script in (ROTATE, DISK):
        subprocess.run(["bash", "-n", str(script)], check=True)


def test_no_deletion_and_mount_readonly():
    src = ROTATE.read_text()
    assert ":/data:ro" in src and "--network none --read-only" in src
    assert "rm -f" not in src and "tail -n" not in src
    result = subprocess.run(["bash", str(ROTATE), "--confirm-rotate"], capture_output=True, text=True)
    assert result.returncode == 1 and "disabled" in result.stdout


def test_rejects_untrusted_volume_and_keep_without_docker():
    for updates in ({"DUCKDB_VOLUME": "other"}, *({"KEEP": x} for x in ("abc", "0", "-3", "1; touch /bad"))):
        r = subprocess.run(["bash", str(ROTATE), "--dry-run"], env={**os.environ, **updates}, capture_output=True)
        assert r.returncode == 2


def test_default_is_readonly_inventory():
    src = ROTATE.read_text()
    assert "${1:---dry-run}" in src and "${DUCKDB_VOLUME}:/data:ro" in src


def test_complete_sets_and_references_retained(tmp_path):
    kinds = ("critical-state", "esef-valuations", "complete-state")
    for index, sha in enumerate(("1111111", "2222222", "3333333", "4444444")):
        for kind in kinds:
            p = tmp_path / f"predeploy-{sha}-{kind}.json"
            p.write_text(json.dumps({"sha": sha}))
            os.utime(p, ns=(index + 1, index + 1))
    partial = tmp_path / "predeploy-5555555-critical-state.json"
    partial.write_text("{}")
    unknown = tmp_path / "predeploy-legacy.json"
    unknown.write_text("{}")
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    out = MODULE.inventory(tmp_path, {"1111111"}, {"predeploy-2222222-complete-state.json"})
    assert not out["deletion_supported"]
    assert not any(x["candidate_only"] for x in out["sets"].values())
    assert out["sets"]["5555555"]["retain_reasons"] == ["incomplete_set"]
    assert unknown.name in out["unknown_retained"]
    assert before == {p.name: p.read_bytes() for p in tmp_path.iterdir()}


def test_old_complete_set_is_only_a_candidate_not_deleted(tmp_path):
    for index, sha in enumerate(("1111111", "2222222", "3333333")):
        for kind in MODULE.REQUIRED:
            p = tmp_path / f"predeploy-{sha}-{kind}.json"
            p.write_text("{}")
            os.utime(p, ns=(index + 1, index + 1))
    out = MODULE.inventory(tmp_path, set(), set())
    assert out["sets"]["1111111"]["candidate_only"]
    assert len(list(tmp_path.iterdir())) == 9


def test_disk_threshold_and_invalid_argument():
    assert '"${1:-85}"' in DISK.read_text()
    for threshold, expected in (("99", 0), ("1", 1), ("abc", 2)):
        r = subprocess.run(["bash", str(DISK), threshold], capture_output=True)
        assert r.returncode == expected
