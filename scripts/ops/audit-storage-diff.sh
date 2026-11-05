#!/usr/bin/env bash
# Auditoria READ-ONLY del almacen de objetos: diff Garage (vivo) vs MinIO
# (archivado) durante la migracion MinIO -> Garage.
#
# Contexto (piloto, 5-nov-2026): el backend vivo es document_storage_backend=
# minio (el SDK) con endpoint garage:3900, region garage, bucket research -
# el almacen activo ES Garage (7.960 objetos / 4,39 GB) y MinIO (5.261 /
# 2,88 GB) esta archivado. Este script lista AMBOS buckets y responde:
#   * que objetos de MinIO NO estan en Garage (huecos de la migracion);
#   * que objetos hay de mas en Garage (escrituras nuevas desde el corte);
#   * claves presentes en ambos con tamano distinto (copia corrupta).
# SOLO LECTURA: lista objetos; no escribe, mueve ni borra nada.
#
# Uso (en la VM, raiz del repo): ./scripts/ops/audit-storage-diff.sh
# Overrides: ARCHIVE_ENDPOINT / ARCHIVE_ACCESS_KEY / ARCHIVE_SECRET_KEY /
#            ARCHIVE_BUCKET (defecto: cavaai-minio:9000, MINIO_ROOT_* de
#            .env.production, research). El lado vivo sale de la config del
#   propio backend (Settings), sin duplicar credenciales aqui.
set -euo pipefail

ENV_FILE="${ENV_FILE:-.env.production}"
[ -f "${ENV_FILE}" ] || { echo "No existe ${ENV_FILE}"; exit 1; }
set -a; . "./${ENV_FILE}"; set +a

COMPOSE="${COMPOSE_CMD:-docker compose -f docker-compose.prod.yml --env-file ${ENV_FILE}}"
OUT="${OUT:-/tmp/storage-diff-$(date +%Y%m%d-%H%M%S).txt}"

${COMPOSE} exec -T \
  -e ARCHIVE_ENDPOINT="${ARCHIVE_ENDPOINT:-cavaai-minio:9000}" \
  -e ARCHIVE_ACCESS_KEY="${ARCHIVE_ACCESS_KEY:-${MINIO_ROOT_USER:-}}" \
  -e ARCHIVE_SECRET_KEY="${ARCHIVE_SECRET_KEY:-${MINIO_ROOT_PASSWORD:-}}" \
  -e ARCHIVE_BUCKET="${ARCHIVE_BUCKET:-research}" \
  backend python3 - <<'PYEOF' | tee "${OUT}"
import os
from minio import Minio
from app.core.config import get_settings

def listing(client, bucket):
    out = {}
    for o in client.list_objects(bucket, recursive=True):
        out[o.object_name] = o.size or 0
    return out

s = get_settings()
live_endpoint = s.minio_endpoint.replace("http://", "").replace("https://", "")
live = Minio(
    live_endpoint,
    access_key=s.minio_access_key,
    secret_key=s.minio_secret_key,
    secure=s.minio_endpoint.startswith("https://"),
    region=s.minio_region or None,
)
archive = Minio(
    os.environ["ARCHIVE_ENDPOINT"],
    access_key=os.environ["ARCHIVE_ACCESS_KEY"],
    secret_key=os.environ["ARCHIVE_SECRET_KEY"],
    secure=False,
)

live_objects = listing(live, s.minio_bucket)
archive_objects = listing(archive, os.environ["ARCHIVE_BUCKET"])

solo_vivo = sorted(set(live_objects) - set(archive_objects))
solo_archivo = sorted(set(archive_objects) - set(live_objects))
distinto = sorted(
    k for k in set(live_objects) & set(archive_objects)
    if live_objects[k] != archive_objects[k]
)

print(f"vivo (garage, {s.minio_endpoint} bucket {s.minio_bucket}): "
      f"{len(live_objects)} objetos, {sum(live_objects.values())} bytes")
print(f"archivo (minio, {os.environ['ARCHIVE_ENDPOINT']} bucket {os.environ['ARCHIVE_BUCKET']}): "
      f"{len(archive_objects)} objetos, {sum(archive_objects.values())} bytes")
print()
print(f"== HUECOS DE MIGRACION (en MinIO, NO en Garage): {len(solo_archivo)}")
for k in solo_archivo:
    print(f"  {k}\t{archive_objects[k]}")
print(f"== NUEVOS EN GARAGE (posteriores al corte): {len(solo_vivo)}")
for k in solo_vivo:
    print(f"  {k}\t{live_objects[k]}")
print(f"== TAMANO DISTINTO EN AMBOS (posible copia corrupta): {len(distinto)}")
for k in distinto:
    print(f"  {k}\tgarage={live_objects[k]}\tminio={archive_objects[k]}")
PYEOF

echo "[audit] diff completo en ${OUT} (solo lectura: no se escribio ni borro nada)"
