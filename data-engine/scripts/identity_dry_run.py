"""Print an offline identity review plan. There is deliberately no apply flag."""
import argparse
import json
from pathlib import Path

from app.services.identity_dry_run import build_plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    args = parser.parse_args()
    rows = json.loads(args.manifest.read_text(encoding="utf-8"))
    snapshot = json.loads(args.snapshot.read_text(encoding="utf-8"))
    print(json.dumps(build_plan(rows, snapshot), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
