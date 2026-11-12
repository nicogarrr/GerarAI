# Retirada de MinIO del compose de produccion

El compose de produccion es standalone, no un overlay del compose de
desarrollo. `scripts/deploy.sh` usa exclusivamente
`docker compose -f docker-compose.prod.yml --env-file .env.production`.
El servicio `minio`, la dependencia del backend y la declaracion del volumen
`cavaai-prod-minio` se retiran. Esto no borra el volumen existente ni modifica
Garage, el entorno de la app o sus defaults.

No combinar `docker-compose.yml` con el de produccion: el primero conserva
MinIO para desarrollo y una fusion de ambos volveria a introducirlo.

## Inventario de referencias restantes

- `docker-compose.yml`, `docs/development-setup.md`, `docs/factory/*` y los
  scripts PowerShell son de desarrollo local y conservan MinIO.
- `.github/workflows/restore-drill.yml` y
  `data-engine/scripts/backup/disaster_drill.py` crean MinIO en drills
  aislados, no en el proyecto compose de produccion. `docker/minio/Dockerfile`
  sigue siendo necesario para ese drill. Su pin se contrasta con dev.
- `scripts/backup.sh`, `scripts/restore.sh` y
  `scripts/verify-backup-restore.sh` son flujos legacy de volumen MinIO.
  Quedan bloqueados con error explicito ANTES de cualquier operacion, incluso
  con `COMPOSE_CMD`. No respaldan ni restauran Garage. Los comandos y el cron
  que los recomiendan en `docs/oracle-setup.md` y `docs/BACKUP_RESTORE.md`
  quedan obsoletos: NO usarlos como procedimiento activo.
- `scripts/deploy.sh` ya no exige `MINIO_ROOT_PASSWORD` como preflight.
- `docs/OBJECT_STORAGE_MIGRATION.md` y
  `docs/RUNBOOK_PILOTO_MINIO_GARAGE.md` conservan instrucciones historicas
  de convivencia/cutover/rollback, no instrucciones para reconstruir MinIO
  en el stack actual.
- `scripts/ops/audit-storage-diff.sh` compara endpoints existentes: no crea
  servicios. Los modulos `backup_minio`/`restore_minio` usan la API S3,
  no crean el servidor. Para Garage debe desactivarse versionado segun
  `docs/OBJECT_STORAGE_MIGRATION.md`.
- El SDK `minio`, las URIs `minio://` y las variables `MINIO_*` son interfaces
  historicas S3 y no implican un contenedor MinIO.

## Limites y seguimiento

Esta retirada no valida backups de objetos Garage. El timer PostgreSQL y
el flujo predeploy son independientes segun comprobacion de operaciones;
un pg_dump no sustituye un backup de objetos. Antes de adoptar cualquier
flujo de backup Garage se requiere verificar copia y restore por separado.

El fallback `OBJECT_STORAGE_ENDPOINT:-minio:9000` sigue intacto por alcance:
la configuracion de produccion debe fijar su endpoint real de Garage.
Exigir explicitamente `OBJECT_STORAGE_*` seria otro cambio de comportamiento,
no parte de esta retirada.
