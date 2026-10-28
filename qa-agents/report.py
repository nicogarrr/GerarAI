"""Resume la salida de qa-agents/run.py en Markdown (para el summary de CI)."""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path


def main(out: Path) -> None:
    print("## Agent QA exploratoria\n")
    for pdir in sorted(d for d in out.iterdir() if d.is_dir()):
        res = json.loads((pdir / "result.json").read_text()) if (pdir / "result.json").exists() else {}
        findings = []
        if (pdir / "findings.jsonl").exists():
            findings = [json.loads(line) for line in (pdir / "findings.jsonl").read_text().splitlines() if line.strip()]
        kinds = Counter(f["kind"] for f in findings)
        print(f"### {pdir.name} — {res.get('steps', '?')} pasos, {len(findings)} hallazgos del vigilante")
        if res.get("harness_error"):
            print(f"- error del arnés: `{res['harness_error']}`")
        if kinds:
            print("- " + ", ".join(f"{k}: {v}" for k, v in kinds.most_common()))
        for f in findings[:15]:
            path = f["url"].split("://", 1)[-1].split("/", 1)[-1]
            print(f"  - `{f['kind']}` /{path}: {f['detail'][:160]}")
        final = (res.get("final") or "").strip()
        if final:
            print("\n<details><summary>Informe del agente</summary>\n\n```\n" + final[:3000] + "\n```\n</details>\n")
        print()


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "qa-agents/out"))
