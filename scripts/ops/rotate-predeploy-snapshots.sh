#!/usr/bin/env bash
# Compatibility entry point, now inventory-only. No file deletion is supported.
# Whole SHA sets are inventoried; current and previous complete sets are retained.
# A separate approved deletion plan must verify external references and backups.
set -euo pipefail
KEEP="${KEEP:-30}"
case "${KEEP}" in ''|*[!0-9]*) echo 'KEEP must be a positive integer'; exit 2;; esac
if [ "${KEEP}" -lt 1 ]; then echo 'KEEP must be at least 1'; exit 2; fi
DUCKDB_VOLUME="${DUCKDB_VOLUME:-cavaai-prod-duckdb}"
if [ "${DUCKDB_VOLUME}" != cavaai-prod-duckdb ]; then
  echo 'Only cavaai-prod-duckdb may be inventoried'; exit 2
fi
case "${1:---dry-run}" in
  --dry-run) ;;
  --confirm-rotate) echo 'Deletion is disabled. Use --dry-run to produce evidence.'; exit 1;;
  *) echo 'Usage: rotate-predeploy-snapshots.sh --dry-run (no deletion)'; exit 1;;
esac
HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
docker volume inspect "${DUCKDB_VOLUME}" >/dev/null
# Read-only mount: not even an implementation bug can mutate tenant data.
docker run --rm --network none --read-only --cpus=.25 --memory=128m \
  -v "${DUCKDB_VOLUME}:/data:ro" \
  -v "${HERE}/snapshot_inventory.py:/inventory.py:ro" \
  --entrypoint python python:3.12-slim /inventory.py --root /data
