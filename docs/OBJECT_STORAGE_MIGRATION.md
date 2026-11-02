# Migracion de almacenamiento de objetos: MinIO -> Garage

MinIO esta archivado (abril 2026). Decision: [[cavaai-minio-garage]] (compilar MinIO ahora, migrar a Garage despues). Esto es la segunda parte. Coste: 0 EUR (Garage es AGPL, imagen `dxflrs/garage:v2.4.1`, publicada para arm64).

## Que cambia y que no

- Las URIs en BD (`minio://research/tenant-N/...`) **no se reescriben**: `minio://` es solo el nombre historico del esquema. Mismo bucket (`research`), mismas claves.
- La app usa el SDK `minio` (S3 estandar) solo para `bucket_exists`, `make_bucket` y `put_object` (`document_store.py`). Garage lo soporta; se fija `MINIO_REGION=garage` para no depender de GetBucketLocation.
- **Garage no tiene versionado de objetos.** El backup por objeto (`backup_minio.py`) activa el versionado por defecto y fallaria: con Garage usar `--no-enable-versioning` (en `backup_all.py`: `--minio-no-versioning`) y no usar `--include-versions`. El manifiesto deja constancia ("no gestionado"). La proteccion contra sobrescritura pasa a ser la inmutabilidad por clave de la app + el backup diario.
- Garage no soporta ACLs de objeto; la app no las usa.

## Fases (cada una reversible)

1. **Puente (este PR).** Deploy normal: arranca `cavaai-garage` junto a `cavaai-minio`. El backend sigue en MinIO. Requiere en `.env.production`: `GARAGE_RPC_SECRET` (`openssl rand -hex 32`), `GARAGE_ACCESS_KEY` (`GK` + `openssl rand -hex 12`), `GARAGE_SECRET_KEY` (`openssl rand -hex 32`). Garage crea solo el bucket `research` y la clave (`--single-node --default-bucket`).
   Comprobar: `docker exec cavaai-garage /garage status` y `docker exec cavaai-garage /garage bucket list`.
2. **Copia verificada** (desde el contenedor backend, que ya llega a ambos por la red de compose):
   ```
   docker compose -p cavaai -f docker-compose.prod.yml exec \
     -e "SRC_ACCESS_KEY=$MINIO_ROOT_USER" -e "SRC_SECRET_KEY=$MINIO_ROOT_PASSWORD" \
     -e "DST_ACCESS_KEY=$GARAGE_ACCESS_KEY" -e "DST_SECRET_KEY=$GARAGE_SECRET_KEY" backend \
     python -m scripts.storage.migrate_minio_to_garage \
       --src-endpoint minio:9000 --dst-endpoint garage:3900 --dst-region garage \
       --bucket research --report /tmp/migracion.json
   ```
   Primero con `--dry-run`. Solo lee MinIO. Relee cada objeto de Garage y compara sha256. Idempotente. Codigo de salida != 0 si algo falta, difiere o no se puede leer, tambien con `--dry-run`.
   Las `$MINIO_*`/`$GARAGE_*` se interpolan en la shell del host antes del `exec`: tienen que estar exportadas desde `.env.production`, y el informe de `/tmp` hay que copiarlo al host o se pierde con el contenedor. El paso a paso exacto (preflight, `-p cavaai`, informes persistentes) esta en [RUNBOOK_PILOTO_MINIO_GARAGE.md](RUNBOOK_PILOTO_MINIO_GARAGE.md).
3. **Corte (con parada total de productores).** Todo servicio que monta `MINIO_*` puede escribir en storage: `backend`, `worker`, `worker-thesis`, `worker-kpis`, `worker-alerts`, `worker-gdelt` y el `scheduler` que los encola. Se para tambien `worker-knowledge`, que estaba omitido en la lista original, y los seis workers de colas de datos (`worker-official-closes`, `worker-prices`, `worker-externa`, `worker-finnhub`, `worker-yahoo`, `worker-dca-manual`): todos heredan `MINIO_*` del ancla `x-app-env` y se detienen por criterio conservador. No se afirma que no escriban en el storage (un actor puede llegar transitivamente, p. ej. `process_document` -> ingesta -> storage): la garantia es la parada total, no el analisis estatico. Parar solo algunos deja bytes nuevos solo en MinIO con la base apuntando a Garage, asi que el corte se hace en ventana de mantenimiento:
   1. `docker compose -p cavaai -f docker-compose.prod.yml stop backend worker worker-thesis worker-kpis worker-knowledge worker-alerts worker-gdelt scheduler worker-official-closes worker-prices worker-externa worker-finnhub worker-yahoo worker-dca-manual` (la app no responde hasta el paso 5; Postgres, Redis, MinIO y Garage siguen arriba).
   2. Confirmar que no queda ningun productor: `docker compose -p cavaai -f docker-compose.prod.yml ps` no debe mostrar ningun productor; siguen arriba los servicios de datos y caddy, que no escribe en storage. Lanzar el paso 2 (copia del delta) con `docker compose run --rm --no-deps backend ...` en vez de `exec`.
   3. `--verify-only` debe dar `ok: true` y codigo de salida 0. Si no, no continuar: arrancar los servicios sin tocar el `.env` (siguen en MinIO).
   4. En `.env.production` descomentar `OBJECT_STORAGE_ENDPOINT/ACCESS_KEY/SECRET_KEY/REGION` y recargar las variables exportadas de la shell: editar el fichero no actualiza el entorno ya exportado.
   5. `docker compose -p cavaai -f docker-compose.prod.yml up -d --no-deps backend worker worker-thesis worker-kpis worker-knowledge worker-alerts worker-gdelt scheduler worker-official-closes worker-prices worker-externa worker-finnhub worker-yahoo worker-dca-manual` (la misma lista de la parada del paso 1: los seis workers de colas de datos tampoco vuelven solos). Verificar `/health/ready` (sonda `minio` = ok) y subir/leer un documento con la cuenta de pruebas.
4. **Rollback.** Tras el corte los productores escriben en Garage, asi que el orden es:
   1. Parada total de productores (la misma lista de la fase 3), antes de tocar nada mas, y mantenerlos parados hasta el final.
   2. Copia inversa verificada: lo escrito en Garage desde el corte se devuelve a MinIO con el mismo script y origen/destino invertidos (`--src-endpoint garage:3900 --src-region garage`, `--dst-endpoint minio:9000 --dst-region ""`, porque la region por defecto del script es `garage`), exigiendo `--verify-only` con 0 errores.
   3. Comentar de nuevo las 4 variables `OBJECT_STORAGE_*` en `.env.production`, hacer `unset OBJECT_STORAGE_ENDPOINT OBJECT_STORAGE_ACCESS_KEY OBJECT_STORAGE_SECRET_KEY OBJECT_STORAGE_REGION` **antes** de recargar la shell (`set -a; . ./.env.production; set +a` no borra variables ya exportadas: sin el `unset`, compose seguiria interpolando los valores de Garage) y confirmar con el preflight del runbook que el endpoint efectivo de todos los servicios es `minio:9000`. Solo entonces recrear los servicios: vuelven a MinIO, que desde el corte no recibia escrituras y ya tiene lo posterior via la copia inversa.
   No se borra nada en Garage: queda para diagnosticar. El paso a paso esta en el runbook del piloto.
5. **Cierre (otro PR, tras >= 7 dias estables + backup verificado desde Garage):** retirar `minio` y `docker/minio`, ajustar `backup_*`/`verify_restore` y los tests de contrato. No se borra el volumen `cavaai-prod-minio` en el mismo paso.

## Riesgos conocidos

- `scripts/backup/_kit.py`, `restore_minio.py` y `verify_restore.py` siguen declarando imagen/version de MinIO en el manifiesto; hasta la fase 5 el backup funciona contra Garage con `--no-enable-versioning`, pero el campo `server_release` seguira diciendo MinIO.
- Un fallo de arranque de Garage no bloquea el backend (no esta en su `depends_on`).
- Garage bucket por defecto solo en el primer arranque con volumenes vacios; si ya existe, la clave y el bucket se conservan.
