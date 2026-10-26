# Backup and Restore Runbook

Create a PostgreSQL backup:

```powershell
.\scripts\backup.ps1
```

Include consistent snapshots of MongoDB, Qdrant and MinIO volumes (the script briefly stops those storage services):

```powershell
.\scripts\backup.ps1 -IncludeStorageVolumes
```

Restore only during a maintenance window. The restore command requires an explicit destructive-operation switch and accepts only a backup path inside the workspace:

```powershell
.\scripts\restore.ps1 -BackupPath .\backups\YYYYMMDD-HHMMSS -ConfirmRestore
```

After restore, run `docker compose run --rm backend alembic upgrade head`, verify `/health/ready`, compare tenant/document/position counts with the backup manifest, open one stored document, and execute a read-only company snapshot. Production backups should be copied to encrypted storage outside the Docker host and tested with a quarterly restore drill.

## Produccion personal (Linux / Oracle VM)

En la VM de produccion los equivalentes en bash son `scripts/backup.sh` y
`scripts/restore.sh` (mismo contrato: Postgres `pg_dump -Fc`, snapshots de
Qdrant, tar de MinIO y DuckDB, manifest por backup; restore exige
`--confirm-restore`). Ambos usan
`docker compose -f docker-compose.prod.yml --env-file .env.production` (o
`COMPOSE_CMD` externo).

- `backup.sh --stop-storage` para backend, TODOS los workers (worker,
  worker-thesis, worker-kpis, worker-alerts, worker-gdelt, worker-knowledge),
  el scheduler y MinIO; sin eso el tar puede capturar un original a medias.
- Antes de subir a R2 o purgar retencion, `backup.sh` recalcula los checksums
  del manifest y aborta si no cuadran. `restore.sh` verifica esos mismos
  checksums antes del primer `dropdb`: un artefacto corrupto no llega a tocar
  los datos.
- `backup.sh` sube a Cloudflare R2 si se define `RCLONE_REMOTE`. Guia completa
  en `docs/oracle-setup.md`.

## Retencion

- Local (`backups/`): `backup.sh` conserva los ultimos
  `${BACKUP_RETENTION_COUNT:-8}` backups y borra los mas antiguos solo tras
  una ejecucion correcta (con `set -e`, un fallo no purga nada).
- R2: la retencion la impone el lifecycle del bucket (regla de expiracion en
  el dashboard de Cloudflare, p. ej. 30 dias); `rclone copy` nunca borra.

## MongoDB Atlas (sesiones de Better Auth)

Estado oficial: Atlas **no ofrece backups en clusteres Free/M0**; hay que usar
`mongodump` (https://www.mongodb.com/docs/atlas/backup-restore-cluster/ y
https://www.mongodb.com/docs/atlas/reference/free-shared-limitations). El tier
real del cluster de produccion se verifica leyendo el host de `MONGODB_URI`
(sin imprimir credenciales) y en la consola de Atlas; hasta entonces el tier
M0 es lo que declara la documentacion del repo, no un dato verificado.

Coste 0 EUR, solo lectura sobre Atlas:

- `scripts/mongo-backup.sh`: `mongodump --archive --gzip` cifrado con `age`
  (clave publica en la VM, `AGE_RECIPIENT`; la privada la guarda solo el propietario).
  No deja fichero en claro. Opcional: copia a R2 con `RCLONE_REMOTE`.
  Retencion local: `BACKUP_RETENTION_COUNT` (8 por defecto).
- `scripts/mongo-restore-drill.sh`: prueba de restauracion en un `mongod`
  efimero en `127.0.0.1:27099`. Nunca restaura sobre Atlas ni produccion.
- Sin `RCLONE_REMOTE` el backup queda en la misma VM: no protege de perder la
  VM. En R2, `rclone copy` nunca borra; la expiracion la impone el lifecycle
  del bucket.
- Probar el primer backup a mano antes de programar el cron.
- Programacion: cron semanal (domingo 04:30 UTC), despues del backup del
  stack de las 04:17. Ejemplo:
  `30 4 * * 0 cd ~/GerarAI && ./scripts/mongo-backup.sh`.
- M0 no tiene backups gestionados: si el cron no corre, no hay segunda copia.
  Verifica el primer domingo que aparece un `backups/mongo-*.age` nuevo.
