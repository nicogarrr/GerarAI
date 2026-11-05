"""Read-only inventory of complete snapshot sets. Never deletes snapshot files."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

PATTERN = re.compile(r"^predeploy-([0-9a-f]{7,40})-(critical-state|esef-valuations|complete-state)\.json$")
REQUIRED = frozenset({"critical-state", "esef-valuations", "complete-state"})


def inventory(root: Path, protected: set[str], referenced: set[str]) -> dict:
    groups: dict[str, dict] = {}
    unknown = []
    for path in sorted(root.glob("predeploy-*.json")):
        match = PATTERN.fullmatch(path.name)
        if not match or path.is_symlink() or not path.is_file():
            unknown.append(path.name)
            continue
        sha, kind = match.groups()
        raw = path.read_bytes()
        # Invalid JSON is evidence to retain, never a deletion candidate.
        try:
            json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            unknown.append(path.name)
            continue
        group = groups.setdefault(sha, {"files": {}, "mtime": 0})
        group["files"][kind] = {"name": path.name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
        group["mtime"] = max(group["mtime"], path.stat().st_mtime_ns)
    complete = sorted((sha for sha, g in groups.items() if set(g["files"]) == REQUIRED), key=lambda sha: groups[sha]["mtime"], reverse=True)
    # Retain the newest two COMPLETE sets, plus all explicitly protected sets.
    retained = set(complete[:2]) | protected
    for sha, group in groups.items():
        names = {x["name"] for x in group["files"].values()}
        reasons = []
        if set(group["files"]) != REQUIRED:
            reasons.append("incomplete_set")
        if sha in retained:
            reasons.append("protected_complete_set")
        if names & referenced:
            reasons.append("referenced")
        group["retain_reasons"] = reasons
        group["candidate_only"] = not reasons
    return {"mode": "inventory_only", "deletion_supported": False, "sets": groups, "unknown_retained": unknown, "protected": sorted(retained), "references": sorted(referenced)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--protected-manifest", type=Path)
    args = parser.parse_args()
    protected: set[str] = set()
    references: set[str] = set()
    if args.protected_manifest:
        data = json.loads(args.protected_manifest.read_text())
        protected = set(data["verified_backup_shas"])
        references = set(data["referenced_snapshot_names"])
        if not all(re.fullmatch(r"[0-9a-f]{7,40}", x) for x in protected):
            parser.error("invalid protected SHA")
    print(json.dumps(inventory(args.root, protected, references), indent=2))


if __name__ == "__main__":
    main()
