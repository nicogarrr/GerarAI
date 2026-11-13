#!/usr/bin/env bash
# Single-database data backup. Cluster roles/ACLs are intentionally not exported.
# Never rotate earlier dumps until this dump restores with zero SQL errors.
set -euo pipefail
DIR="${BACKUP_DIR:-$HOME/backups}"
SOURCE="${PG_SOURCE_CONTAINER:-cavaai-postgres}"
IMAGE="${PG_VERIFY_IMAGE:-postgres:17}"
KEEP="${BACKUP_KEEP:-2}"
[[ "$KEEP" =~ ^[1-9][0-9]*$ ]] || exit 2
mkdir -p "$DIR"
LOG="$DIR/pg-daily.log"
log() { printf '%s %s\n' "$(date -Is)" "$*" >> "$LOG"; }
exec 9>"${LOCKFILE:-/tmp/cavaai-pgbackup.lock}"
flock -n 9 || { log 'SKIP another backup is running'; exit 4; }
TS="$(date -u +%Y%m%dT%H%M%S)-$$"
OUT="$DIR/pg-daily-$TS.sql.gz"
TMP="pgverify-$TS"
started=0
cleanup() {
  local rc=$?
  trap - EXIT
  rm -f "$OUT.part"
  if (( started )); then
    if ! docker rm -fv "$TMP" >> "$DIR/pg-cleanup.log" 2>&1; then
      log "FAIL temporary restore cleanup: $TMP"
      rc=1
    fi
  fi
  if (( rc )); then log "FAIL backup/restore: $OUT (earlier backups retained)"; fi
  exit "$rc"
}
trap cleanup EXIT
FREE_MB="$(df -Pm "$DIR" | awk 'END {print $4}')"
DB_MB="$(docker exec "$SOURCE" sh -c 'psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "select pg_database_size(current_database())/1048576"')"
[[ "$FREE_MB" =~ ^[0-9]+$ && "$DB_MB" =~ ^[0-9]+$ ]] || exit 1
(( DB_MB > 0 && FREE_MB >= DB_MB * 2 + 2048 )) || { log 'VERIFY_DEFERRED insufficient free space; no rotation'; exit 3; }
# -O/-x creates a portable data/schema dump without missing-role ownership errors.
if ! docker exec "$SOURCE" sh -c 'pg_dump --no-owner --no-privileges -U "$POSTGRES_USER" -d "$POSTGRES_DB"' | gzip -6 > "$OUT.part"; then
  log 'FAIL pg_dump'; exit 1
fi
[[ -s "$OUT.part" ]] && gzip -t "$OUT.part"
mv "$OUT.part" "$OUT"
SRC_TABLES="$(docker exec "$SOURCE" sh -c 'psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "select count(*) from information_schema.tables where table_schema='"'"'public'"'"'"')"
[[ "$SRC_TABLES" =~ ^[0-9]+$ ]] && (( SRC_TABLES > 0 ))
# Reserve cleanup before creating: even a failed create can leave a container.
started=1
docker run -d --name "$TMP" --network none --cpus=.5 --memory=2g -e POSTGRES_PASSWORD=verify -e POSTGRES_DB=verify "$IMAGE" >> "$DIR/pg-verify-container.log"
# The entrypoint's temporary initialization server accepts Unix sockets only.
# Waiting on TCP avoids racing its intentional shutdown before the final server.
ready=0
for _ in $(seq 1 30); do
  if docker exec "$TMP" pg_isready -h 127.0.0.1 -U postgres -d verify >> "$DIR/pg-verify-container.log" 2>&1; then ready=1; break; fi
  sleep 2
done
(( ready )) || { log 'FAIL temporary Postgres not ready'; exit 1; }
# Both gzip and psql must succeed. A late SQL error must not count as success.
if ! gzip -dc "$OUT" | docker exec -i "$TMP" psql -X -q -U postgres -d verify -v ON_ERROR_STOP=1 --single-transaction > "$DIR/pg-verify.out" 2> "$DIR/pg-verify.err"; then
  log 'FAIL strict restoration'; exit 1
fi
DST_TABLES="$(docker exec "$TMP" psql -X -U postgres -d verify -v ON_ERROR_STOP=1 -Atc "select count(*) from information_schema.tables where table_schema='public'")"
[[ "$DST_TABLES" == "$SRC_TABLES" ]] || { log "FAIL table inventory: $SRC_TABLES != $DST_TABLES"; exit 1; }
# Cleanup is part of success, before the verified marker and rotation.
docker rm -fv "$TMP" >> "$DIR/pg-cleanup.log" 2>&1
started=0
sha256sum "$OUT" > "$OUT.sha256"
printf 'strict_restore=ok\npublic_tables=%s\n' "$DST_TABLES" > "$OUT.verified"
log "OK $OUT strict restoration verified ($DST_TABLES public tables)"
# Rotate only this script's explicitly verified dumps, not unverified or predeploy backups.
mapfile -t verified < <(find "$DIR" -maxdepth 1 -type f -name 'pg-daily-*.sql.gz.verified' -printf '%f\n' | sort -r)
for ((i=KEEP; i<${#verified[@]}; i++)); do
  old="$DIR/${verified[i]%.verified}"
  rm -f -- "$old" "$old.sha256" "$old.verified"
done
