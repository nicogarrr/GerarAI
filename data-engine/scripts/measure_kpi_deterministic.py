"""Read-only dry-run on a pilot JSON(.gz) export, no DB/provider/network.

Run from data-engine: python -m scripts.measure_kpi_deterministic EXPORT
Counts document+registry-key opportunities, not facts or arbitrary claims.
"""
from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path
from types import SimpleNamespace

from app.services.kpi_deterministic import VERSION, extract


def measure(payload):
    counts = {"documents": 0, "registry_opportunities": 0, "covered_opportunities": 0,
              "documents_with_candidates": 0, "candidates": 0, "chunks_scanned": 0,
              "documents_truncated_at_500_chunks": 0}
    for document in payload["documents"]:
        registry = [SimpleNamespace(**row) for row in document["kpi_registry"]]
        chunks = [SimpleNamespace(**row) for row in document["chunks"][:500]]
        observations = extract(chunks, registry, source_type=document["source_type"],
                               cik=document.get("metadata_relevant", {}).get("cik"))
        active = {row.metric_key for row in registry if row.active}
        covered = active & {row["metric_key"] for row in observations}
        counts["documents"] += 1
        counts["registry_opportunities"] += len(active)
        counts["covered_opportunities"] += len(covered)
        counts["documents_with_candidates"] += bool(observations)
        counts["candidates"] += len(observations)
        counts["chunks_scanned"] += len(chunks)
        counts["documents_truncated_at_500_chunks"] += len(document["chunks"]) > 500
    counts["coverage_percent"] = round(100 * counts["covered_opportunities"] / max(1, counts["registry_opportunities"]), 4)
    return {"parser_version": VERSION, "sample_as_of": payload.get("as_of_utc"),
            "sample_method": payload.get("sample_method"), **counts}


if __name__ == "__main__":
    path = Path(sys.argv[1])
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt") as handle:
        print(json.dumps(measure(json.load(handle)), indent=2))
