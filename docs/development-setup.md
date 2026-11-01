# Guía de Configuración del Entorno de Desarrollo de GerarAI

Fulfills: VAL-DOC-005 (document-development-setup)

Esta guía detalla los pasos requeridos para configurar un entorno de desarrollo local completo para GerarAI, tanto para el frontend (Next.js) como para el backend (FastAPI + SQLAlchemy).

---

## 1. Requisitos Previos de Software

| Herramienta | Versión | Finalidad |
|---|---|---|
| **Python** | 3.12 (`requires-python = ">=3.12,<3.13"`) | Backend `data-engine` |
| **uv** | reciente | Instala las dependencias congeladas del backend (`uv.lock`) |
| **Node.js** | 22 | Frontend Next.js 16 |
| **npm** | el que trae Node 22 | Dependencias del frontend (`package-lock.json`) |
| **Docker y Compose** | Compose v2 | Infraestructura local (MongoDB, PostgreSQL, Redis, Qdrant, MinIO) |
| **Git** | reciente | Control de versiones |

---

## 2. Puesta en Marcha Rápida (Primer Arranque)

### Paso 1: Clonar el Repositorio
```bash
git clone https://github.com/nicogarrr/GerarAI.git
cd GerarAI
```

### Paso 2: Variables de entorno
Hay una sola plantilla para desarrollo local, `docker.env.example`. El frontend lee `.env` en la raíz y el backend lee `.env` en su carpeta de trabajo (`data-engine/`), así que se copia en los dos sitios:
```bash
cp docker.env.example .env
cp docker.env.example data-engine/.env
```
Sustituye los valores de ejemplo de `BETTER_AUTH_SECRET` y `RESEARCH_AUTH_SECRET` (32+ caracteres cada uno, `openssl rand -base64 32`). `RESEARCH_AUTH_SECRET` debe ser idéntico en los dos ficheros. Por defecto el backend usa SQLite local (`DATABASE_URL=sqlite:///./portfolio_research_os.db`); para usar el PostgreSQL de Docker cambia `DATABASE_URL` en `data-engine/.env`.

### Paso 3: Levantar Infraestructura de Soporte (Docker)
```bash
docker compose up -d mongodb postgres redis qdrant minio
```
MongoDB es obligatorio: guarda los usuarios y sesiones de Better Auth.

### Paso 4: Configurar el Backend (data-engine)
```bash
cd data-engine

# Dependencias exactas congeladas en data-engine/.venv
uv sync --frozen --extra test --extra dev --no-install-project
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# Migraciones y taxonomía pública de empresas (no crea carteras ni datos de usuario)
python -m alembic upgrade head
python -m app.seed

# Servidor de desarrollo FastAPI
python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

### Paso 5: Configurar el Frontend (Next.js)
En una nueva terminal desde la raíz del proyecto:
```bash
npm ci
npm run dev
```
La aplicación web estará disponible en `http://localhost:3000` y la documentación de la API en `http://localhost:8000/docs`.

En Windows, `arrancar_gerarai.bat` hace los pasos 3 a 5 de una vez.

---

## 3. Flujos de Trabajo Habituales de Desarrollo

### Quality gates del backend
Antes de abrir una Pull Request:
```bash
cd data-engine

# Con el venv activado (paso 4)
ruff check .                                   # lint
pyright                                        # tipos (0 errores requeridos)
python scripts/export_openapi.py               # contrato OpenAPI (el diff debe quedar vacío; ver README)
APP_ENV=test python -m pytest -q -m "not services"   # tests sin servicios externos
```

### Quality gates del frontend
Desde la raíz del proyecto:
```bash
npm run lint          # ESLint
npm run typecheck     # TypeScript (tsc --noEmit)
npm run test:unit     # Vitest + Testing Library
npm run test:guards   # guardas de scripts/*.test.*
npm run build         # build de producción de Next.js
```
Más detalle de los tests del frontend en [FRONTEND_TESTS.md](FRONTEND_TESTS.md).

---

## 4. Resolución de Incidencias Frecuentes en el Entorno Local

1. **Error `ConnectionRefusedError: [Errno 111]` al conectar a Postgres**:
   - Asegúrate de que el contenedor de PostgreSQL está levantado: `docker compose ps`.
   - Si usas PostgreSQL, comprueba que `DATABASE_URL` en `data-engine/.env` apunta a `localhost:5432` y no al nombre del contenedor (`postgres`).
2. **Error `HMAC signature missing or invalid` en peticiones frontend**:
   - Comprueba que la clave `RESEARCH_AUTH_SECRET` en `.env` de la raíz (frontend) coincide exactamente con la de `data-engine/.env` (backend).
3. **Fallo en tests con `EPERM` en Windows**:
   - Ejecuta los comandos con permisos adecuados o en una sesión de terminal elevada si el antivirus bloquea la creación de temporales en `.pytest_cache`.
