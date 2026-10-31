# Runbook de Despliegue en Producción de GerarAI

Fulfills: VAL-DOC-003 (document-deployment-runbook)

Este documento detalla el procedimiento operativo estándar para el despliegue, configuración, migración de base de datos, verificación de salud y rollback del backend de GerarAI en entornos de producción (Oracle Cloud Ampere A1 Always Free, 4 OCPU / 24 GB RAM).

---

## 1. Requisitos Previos y Topología

- **Infraestructura**:
  - VM ARM64 con Docker Engine 24+ y Docker Compose v2.
  - Red aislada Docker con persistencia en volúmenes locales montados.
  - Frontend servido en Vercel Edge con variables de entorno de conexión.
  - MongoDB Atlas (M0 Free Tier) exclusivo para auth y sesiones de usuario.
- **Fichero Compose**: `docker-compose.prod.yml`
- **Fichero de Entorno**: `.env.production` (con permisos `chmod 600`).

---

## 2. Configuración de Variables de Entorno (`.env.production`)

El archivo `.env.production` debe situarse en la raíz del proyecto con los siguientes parámetros requeridos:

```bash
# Entorno y Seguridad
APP_ENV=production
RESEARCH_AUTH_REQUIRED=true
RESEARCH_AUTH_SECRET=tu_secreto_hmac_64_chars_hex_aqui

# Base de Datos Relacional (PostgreSQL)
POSTGRES_USER=portfolio
POSTGRES_PASSWORD=tu_password_segura_postgres
POSTGRES_DB=cavaai_research
DATABASE_URL=postgresql+psycopg://portfolio:tu_password_segura_postgres@postgres:5432/cavaai_research

# Caché y Colas (Redis 7)
REDIS_PASSWORD=tu_password_segura_redis
REDIS_URL=redis://:tu_password_segura_redis@redis:6379/0

# Base de Datos Vectorial (Qdrant)
QDRANT_URL=http://qdrant:6333
VECTOR_STORE=qdrant

# Almacenamiento de Objetos (MinIO / Garage)
MINIO_ROOT_USER=minioadmin
MINIO_ROOT_PASSWORD=tu_password_segura_minio
MINIO_ENDPOINT=minio:9000
MINIO_BUCKET=research

# Identificación Regulatoria SEC EDGAR
SEC_USER_AGENT="GerarAI/1.0 (contacto: admin@gerarai.com)"

# Scheduler y Workers
WORKERS_ENABLED=true
APS_SCHEDULER_ENABLED=true
```

---

## 3. Procedimiento de Despliegue Paso a Paso

### Paso 1: Obtener la Última Versión del Código
```bash
git fetch origin main
git checkout main
git pull --ff-only origin main
```

### Paso 2: Crear Copia de Seguridad Preventiva (Snapshot)
Antes de aplicar cualquier cambio o migración, ejecutar:
```bash
./scripts/backup.sh
```
El backup se guarda en `backups/<AAAAMMDD-HHMMSS>/` (PostgreSQL con `pg_dump -Fc`, snapshots de Qdrant, MinIO, DuckDB y un `manifest.txt`). Opciones, retención y restauración: [BACKUP_RESTORE.md](BACKUP_RESTORE.md).

### Paso 3: Aplicar Migraciones de Base de Datos (Alembic)
Las migraciones se ejecutan mediante un contenedor temporal antes de reiniciar los servicios:
```bash
docker compose -f docker-compose.prod.yml --env-file .env.production run --rm \
  backend uv run alembic upgrade head
```

### Paso 4: Construir y Levantar Contenedores
```bash
docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build --remove-orphans
```

---

## 4. Verificación de Salud Post-Despliegue

Ejecutar las siguientes comprobaciones para garantizar que todos los subsistemas responden correctamente:

### 1. Comprobar Sonda de Liveness y Base de Datos
```bash
curl -f -s http://localhost:8000/api/health | jq .
```
**Respuesta esperada:**
```json
{
  "status": "healthy",
  "database": "connected",
  "scheduler": { "enabled": true, "running": true }
}
```

### 2. Comprobar Conectores y Fuentes de Datos
```bash
curl -f -s -H "X-CavaAI-Tenant: sys-monitor" http://localhost:8000/api/health/data-sources | jq .
```
Debe indicar `"all_healthy": true` con circuitos `"CLOSED"`.

### 3. Comprobar Estadísticas de Caché Redis
```bash
curl -f -s http://localhost:8000/api/cache/stats | jq .
```

### 4. Inspección de Logs en Vivo
```bash
docker compose -f docker-compose.prod.yml logs -f --tail=50 backend
```

---

## 5. Procedimiento de Rollback (Reversión)

Si se detectan errores críticos, degradación severa de latencia o fallos en tests de humo tras el despliegue:

### 1. Revertir Migración de Base de Datos
```bash
docker compose -f docker-compose.prod.yml --env-file .env.production run --rm \
  backend uv run alembic downgrade -1
```

### 2. Restaurar Backup de Base de Datos (En Caso de Corrupción)
```bash
gunzip -c storage/backups/pg_dump_ULTIMO.sql.gz | docker exec -i gerarai-postgres psql -U portfolio -d cavaai_research
```

### 3. Volver a la Imagen / Commit Anterior
```bash
git checkout HEAD~1
docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build
```

### 4. Confirmar Estabilización
Verificar que `/api/health` vuelve a reportar `"status": "healthy"`.
