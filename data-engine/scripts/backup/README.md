# Backup y restore verificados de GerarAI

Backup y restore **verificados** de los tres pilares (Postgres, MinIO,
Qdrant), con manifiesto comun, verificacion fail-closed, drill de desastre
ejecutable y un runbook para recuperar desde cero.

- **Como recuperar**: [`RUNBOOK.md`](RUNBOOK.md) (sin contexto previo).
- **Prueba del ciclo completo**: `python -m scripts.backup.disaster_drill`.
- **Estado anterior del repo** (scripts en bash, sin verificar):
  `scripts/backup.sh`, `scripts/restore.sh`, `scripts/verify-backup-restore.sh`.
  Siguen funcionando para la VM de produccion; este arbol es el camino verificado
  y el que comprueba CI.

## Por que viven en `data-engine/scripts/` y no en `scripts/` del repo

`python -m ruff check .` se ejecuta **desde `data-engine/`** en el job `backend`
de `ci.yml`, asi que cualquier modulo fuera de ese arbol no se lintea. Como los
scripts de backup son codigo que corre en produccion, se han puesto dentro de
`data-engine/scripts/backup/` y `data-engine/scripts/restore/` para que ruff los
cubra sin tocar `ruff.toml` ni duplicar el linteo en un segundo sitio. Con esto,
`python -m ruff check .` cubre el backup igual que cubre `app/`.

Requisito practico: los scripts se ejecutan desde `data-engine/`.

## Comandos

```bash
cd data-engine

# Backup de los tres pilares -> <backup>/manifest.json
python -m scripts.backup.backup_all --out-dir backups

# Un pilar suelto (por diagnostico)
python -m scripts.backup.backup_postgres --out backups/<id> --mode docker --container cavaai-postgres
python -m scripts.backup.backup_minio   --out backups/<id> --endpoint 127.0.0.1:9000 --bucket research
python -m scripts.backup.backup_qdrant  --out backups/<id> --url http://127.0.0.1:6333

# Restore a destino limpio (DESTRUCTIVO: pide --confirm-restore)
python -m scripts.restore.restore_postgres --manifest backups/<id> --mode docker --container cavaai-postgres --confirm-restore
python -m scripts.restore.restore_minio    --manifest backups/<id> --endpoint 127.0.0.1:9000 --confirm-restore
python -m scripts.restore.restore_qdrant   --manifest backups/<id> --url http://127.0.0.1:6333 --confirm-restore

# Verificacion: 6 comprobaciones, fail-closed
python -m scripts.restore.verify_restore --manifest backups/<id> \
  --mode docker --pg-container cavaai-postgres \
  --minio-endpoint 127.0.0.1:9000 --qdrant-url http://127.0.0.1:6333 \
  --app-base-url http://127.0.0.1:8000

# Ciclo completo de desastre, aislado (nunca sobre datos reales)
python -m scripts.backup.disaster_drill
```

Requisitos: Python 3.11+ con las dependencias de `data-engine` (`minio`,
`httpx`, `psycopg`, `sqlalchemy`, `alembic`), Docker (para el modo contenedor)
y las variables de `.env` / `.env.production` del entorno donde corra.

## Decisiones (y lo que se.rejectaria en revision)

### Postgres: `pg_dump -Fc` + globals, y el head de Alembic en el manifiesto

Un dump plano (`-Fp`) no es restaurable de forma fiable: no es seleccionable,
no se puede restaurar por partes y un corte a medias lo deja inutilizable. El
formato custom va comprimido y `pg_restore --list` da el catalogo del artefacto
sin tocar el servidor.

Los globals (`pg_dumpall --globals-only`) se guardan aparte porque en un cluster
nuevo, sin el rol, el backend falla con `role does not exist` **en el primer
arranque**: un restore que "funciona" y luego rompe.

El backup **rechaza** una base por detras del head de Alembic (`--allow-schema-drift`
lo permite a proposito). Un dump anterior al head restaura bien y rompe en la
primera peticion, y el fallo aparece dias despues, lejos de la causa.

Los conteos por tabla se leen de la base viva **antes y despues** del dump. Si
no coinciden, el backup falla: es la deuda que arrastraba `scripts/backup.sh`
documentada como limitacion consciente. Con escrituras concurrentes no se puede
producir un backup consistente con conteos exactos sin parar los escritores o
exportar un snapshot consistente (`pg_dump --snapshot`); mientras tanto, el
comportamiento honesto es fallar, no fingir que el backup es bueno.

### MinIO: por objeto, con versionado activado

Un `tar` del volumen de MinIO no es un backup: solo se restaura en la misma
maquina, contra el mismo `/data` y con el mismo `.minio.sys`. Aqui se copia
objeto a objeto y direccionado por clave, mas SHA-256 por clave.

**El repo no activaba el versionado de bucket** (`app/services/document_store.py`
hace `make_bucket` y nada mas). `backup_minio.py` lo activa de forma idempotente
antes de copiar y **comprueba** que quedo activo; si no puede, falla. Sin el,
"recupera el objeto que se sobreescribio hace una hora" es imposible.

Dos transportes, ambos con version declarada en el manifiesto:

- `sdk` (por defecto): el cliente `minio`, que ya es dependencia fijada del
  data-engine (`minio>=7.2.7,<8`). No depende de que el host tenga `mc`.
  Es el que usan el drill y CI.
- `mc`: `mc mirror` para la copia fuera de maquina cuando `mc` ya esta
  configurado (`--transport mc --mc-alias ...`). Se mantiene porque es como se
  saca el backup del host, pero **no** es el camino por defecto: `mc` no esta en
  la imagen de MinIO (lo dicen los propios healthchecks del compose) y exigirlo
  en el host rompe en una maquina que no lo tenga.

### Qdrant: snapshot por API, no copia del volumen

`POST /collections/{c}/snapshots` + descarga del `.snapshot`. Es lo unico que
restaura en otra maquina: `POST /collections/{c}/snapshots/upload` crea o
reemplaza la coleccion sin tocar volumenes. Copiar `/qdrant/storage` solo
funciona en la misma maquina y con el mismo path.

Misma fuente de verdad que la aplicacion: URL e (futura) API key salen de los
mismos settings que usa `app/services/rag.py`.

El `checksum` que devuelve Qdrant **si** es el SHA-256 del `.snapshot` y se
comprueba contra el fichero descargado: una verificacion de integridad que no
depende de nuestro propio calculo.

### Verificacion fail-closed, en dos fases

`verify_restore.py` ejecuta seis comprobaciones y ninguna puede quedar
"omitida". Mismo principio que el gate de RAG de `ci.yml` ("RAG activation tests
skipped -> exit 1"). Si falta `--app-base-url`, `d_aplicacion` FALLA con el
motivo; no se salta.

Las fases existen porque **arrancar la app muta la base restaurada** fuera de
produccion: `main.py` llama a `ensure_company_master()` si `APP_ENV !=
production` (en el drill, `companies` pasa de 12 a 35 al arrancar). Comparar
los conteos con la app ya en marcha daria un falso positivo de "restore
incompleto", o peor, taparia una perdida real de filas. Por eso `--phase data`
va antes del arranque y `--phase app` despues.

### El drill

`disaster_drill.py` (Python, no shell, para que devuelva codigos de salida de
forma fiable y funcione igual en Windows, Linux y en el runner de CI) levanta
Postgres, MinIO y Qdrant con **contenedores, volumenes, puertos y directorio
temporal propios**, siembra datos deterministas (12 companies, 7 objetos, 25
puntos de dimension 8), hace el backup, **destruye contenedores y volumenes**,
restaura a destino limpio, verifica las seis comprobaciones y devuelve 0 solo si
todas pasan.

Es no destructivo por construccion: los nombres son `cavaai-drill<id>-*` y el
drill **aborta** si un contenedor con ese nombre ya existe. No menciona ningun
volumen de produccion (`cavaai-prod-*`, `cavaai-postgres-data`, ...), y un test
lo comprueba.

Usa modo `docker` para Postgres, igual que produccion (`docker compose exec
postgres`): asi el `pg_dump` es el del contenedor 17.x y no depende de que el
host tenga un cliente instalado y compatible.

## Lo que este arbol NO cubre (a proposito)

- **DuckDB y los ficheros locales** (`/data/analytics.duckdb`, `data-esef-snapshots`):
  los cubre `scripts/backup.sh`. No son los tres pilares del enunciado y su
  restauracion no se ha verificado aqui.
- **MongoDB**: vive en MongoDB Atlas y lo respalda el proveedor. Si algún día
  vuelve a ser local, necesita su propio pilar.
- **La copia fuera de maquina** de Postgres y Qdrant: el manifiesto y los
  artefactos se pueden copiar tal cual (checksums incluidos), pero subir y
  descargar desde R2 lo hace `scripts/backup.sh` con `rclone`. Conviven: este
  arbol produce el backup verificable, el otro lo replica.
- **Retencion**: la gestion de `backups/` la tiene `scripts/backup.sh`.
  Aqui no hay limpieza automatica a proposito: borrar backups es una decision
  destructiva que no debe depender de un script que nadie ha leido.

## Verificacion en CI

`.github/workflows/restore-drill.yml` levanta Postgres 17, MinIO y Qdrant como
services, siembra datos deterministas, ejecuta backup -> restore a destino
limpio -> las seis comprobaciones, y **falla si alguna se omite o si la
desviacion de conteos no es 0**. Es el mismo drill, en un entorno efimero, en
cada push.

Ademas, `tests/test_backup_contracts.py` fija los contratos sin tocar servicios:
el manifiesto y sus campos obligatorios, el fail-closed de cada comprobacion, el
orden del runbook, que el runbook menciona cada paso, que el workflow declara
los tres pilares y que las herramientas estan fijadas por version y coinciden con
los pins de los compose.

## A/B de carga Postgres con topes de memoria (`pg_load_ab.py`)

Apoyo al A/B de Postgres del piloto: misma carga determinista contra la copia
restaurada con cada tope (896m, 4g, 6g, 8g), con verificacion de restore tras
cada cambio y sin backup concurrente. Un tope que rompe el restore o mata
Postgres por OOM queda registrado en el informe (es el dato buscado), no
tumba el instrumento.

    python -m scripts.backup.pg_load_ab --caps 896m,4g,6g,8g --out load_ab.json

Modo externo (copia restaurada de la VM, tope aplicado por el piloto):

    python -m scripts.backup.pg_load_ab --external --database-url postgresql://... \
        --cap-label 4g [--backup-dir DIR --minio-endpoint ... --qdrant-url ...]

No cambies `--seed` entre topes: romperia la comparabilidad.
