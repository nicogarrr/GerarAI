#!/usr/bin/env bash
# Despliegue idempotente del stack de produccion (Oracle VM).
#
# Preflight sin secretos:
#   1) .env.production existe y no conserva placeholders del example;
#   2) las claves obligatorias tienen valor;
#   3) `docker compose config` valida el YAML/entorno ANTES de tocar nada.
# Despues reconstruye solo lo que haga falta y espera a que los healthchecks
# esten verdes. Relanzarlo es seguro: compose converge al mismo estado.
#
# Uso: ./scripts/deploy.sh
#   ENV_FILE=.env.production   fichero de entorno (por defecto)
#   SKIP_PULL=1                no hace pull de imagenes remotas
set -euo pipefail

cd "$(dirname "$0")/.."

ENV_FILE="${ENV_FILE:-.env.production}"
COMPOSE=(docker compose -f docker-compose.prod.yml --env-file "${ENV_FILE}")

command -v docker >/dev/null 2>&1 || { echo "[deploy] ERROR: docker no esta instalado"; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "[deploy] ERROR: falta docker compose v2"; exit 1; }
[ -f "${ENV_FILE}" ] || { echo "[deploy] ERROR: no existe ${ENV_FILE}"; exit 1; }

# Placeholders conocidos. No se imprime el valor de la linea (puede ser un
# secreto): solo se informa del fallo y se aborta antes de arrancar.
if grep -qiE '^[A-Z0-9_]+=.*(cambia-esto|cambia_esto|cambia esto|genera-|genera_|generame|tu-correo|tu-email|tudominio|example\.com)' "${ENV_FILE}"; then
  echo "[deploy] ERROR: ${ENV_FILE} conserva placeholders (cambia-esto/genera/tu-...). Rellena secretos reales."
  exit 1
fi

for key in POSTGRES_PASSWORD MINIO_ROOT_PASSWORD RESEARCH_AUTH_SECRET \
           GARAGE_RPC_SECRET GARAGE_ACCESS_KEY GARAGE_SECRET_KEY BACKEND_DOMAIN; do
  grep -qE "^${key}=.+" "${ENV_FILE}" || {
    echo "[deploy] ERROR: falta ${key} con valor en ${ENV_FILE}"
    exit 1
  }
done

# Version visible en /api/health (la imagen no lleva git). Sobrescribible.
if [ -z "${APP_VERSION:-}" ] && command -v git >/dev/null 2>&1 && git rev-parse --git-dir >/dev/null 2>&1; then
  APP_VERSION="$(git rev-parse --short HEAD)"
fi
export APP_VERSION="${APP_VERSION:-unknown}"

echo "[deploy] validando compose con ${ENV_FILE}…"
"${COMPOSE[@]}" config >/dev/null

if [ "${SKIP_PULL:-0}" != "1" ]; then
  echo "[deploy] actualizando imagenes remotas…"
  "${COMPOSE[@]}" pull --ignore-buildable
fi

echo "[deploy] construyendo y levantando (idempotente)…"
"${COMPOSE[@]}" up -d --build --remove-orphans --wait --wait-timeout 600

echo "[deploy] estado:"
"${COMPOSE[@]}" ps
