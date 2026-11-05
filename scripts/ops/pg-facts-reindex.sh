#!/usr/bin/env bash
# Reclaim supervisado del bloat de financial_facts (VM de produccion).
#
# Contexto (medido 5-nov-2026): financial_facts 3,13 GB, 1,36 GB en indices,
# tras meses de reescritura completa por refresh (la causa se corto en codigo
# con el skip de refresh sin cambios y el bulk de inserts; esto recupera el
# espacio historico). NO borra ni una fila: REINDEX reconstruye indices y
# VACUUM ANALYZE devuelve tuplas muertas al reciclaje interno.
#
# LO EJECUTA UN OPERADOR (piloto/Nico), NUNCA un cron ni un agente:
#   1. backup previo: ./scripts/backup.sh  (comprobar que termino bien)
#   2. ./scripts/ops/pg-facts-reindex.sh --confirm-reindex
#
# REINDEX ... CONCURRENTLY no bloquea lecturas/escrituras (cada indice se
# reconstruye en segundo plano y se intercambia). No se usa VACUUM FULL:
# bloquearia la tabla. REINDEX CONCURRENTLY no puede ir en transaccion:
# cada sentencia va en su propio psql -c.
set -euo pipefail

case "${1:-}" in
  --confirm-reindex) ;;
  *) echo "Uso: $0 --confirm-reindex"; echo "Requiere backup previo verificado (scripts/backup.sh)."; exit 1;;
esac

if [ -z "${COMPOSE_CMD:-}" ] && [ -f .env.production ]; then
  COMPOSE="docker compose -f docker-compose.prod.yml --env-file .env.production"
else
  COMPOSE="${COMPOSE_CMD:-docker compose -f docker-compose.prod.yml}"
fi
PSQL="${COMPOSE} exec -T postgres psql -U ${POSTGRES_USER:-portfolio} -d ${POSTGRES_DB:-cavaai_research} -v ON_ERROR_STOP=1"
TABLA="${REINDEX_TABLE:-financial_facts}"

${COMPOSE} ps postgres --status running >/dev/null 2>&1 || {
  echo "[reindex] ERROR: el contenedor postgres no esta corriendo"; exit 1; }

echo "[reindex] bloat estimado ANTES (tuplas muertas y tamano):"
${PSQL} -c "SELECT relname, n_dead_tup, n_live_tup, pg_size_pretty(pg_total_relation_size(relid)) AS total FROM pg_stat_user_tables WHERE relname = '${TABLA}'"
${PSQL} -c "SELECT indexrelname, pg_size_pretty(pg_relation_size(indexrelid)) AS size FROM pg_stat_user_indexes WHERE relname = '${TABLA}' ORDER BY pg_relation_size(indexrelid) DESC"

echo "[reindex] REINDEX (CONCURRENTLY) de ${TABLA}:"
${PSQL} -c "REINDEX TABLE CONCURRENTLY ${TABLA}"

echo "[reindex] VACUUM ANALYZE de ${TABLA}:"
${PSQL} -c "VACUUM (ANALYZE) ${TABLA}"

echo "[reindex] DESPUES:"
${PSQL} -c "SELECT relname, n_dead_tup, pg_size_pretty(pg_total_relation_size(relid)) AS total FROM pg_stat_user_tables WHERE relname = '${TABLA}'"
${PSQL} -c "SELECT indexrelname, pg_size_pretty(pg_relation_size(indexrelid)) AS size FROM pg_stat_user_indexes WHERE relname = '${TABLA}' ORDER BY pg_relation_size(indexrelid) DESC"
echo "[reindex] completo. Ninguna fila tocada: solo indices reconstruidos y tuplas muertas recicladas."
