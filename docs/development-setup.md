# Guía de Configuración del Entorno de Desarrollo de GerarAI

Fulfills: VAL-DOC-005 (document-development-setup)

Esta guía detalla los pasos requeridos para configurar un entorno de desarrollo local completo para GerarAI, tanto para el frontend (Next.js) como para el backend (FastAPI + SQLAlchemy).

---

## 1. Requisitos Previos de Software

| Herramienta | Versión Mínima | Finalidad |
|---|---|---|
| **Python** | 3.12+ (CPython) | Backend data-engine |
| **uv** | 0.4+ | Gestor ultrarrápido de paquetes y entornos Python |
| **Node.js** | 20.x o 22.x LTS | Servidor y cliente Next.js 16 |
| **npm / pnpm** | 10.x / 9.x | Gestor de paquetes frontend |
| **Docker & Compose** | 24+ / Compose v2 | Servicios de infraestructura local (Postgres, Redis, Qdrant) |
| **Git** | 2.40+ | Control de versiones |

---

## 2. Puesta en Marcha Rápida (Primer Arranque)

### Paso 1: Clonar el Repositorio
```bash
git clone https://github.com/nicogarrr/GerarAI.git
cd GerarAI
```

### Paso 2: Levantar Infraestructura de Soporte (Docker)
Para desarrollo local se proveen los contenedores necesarios en background:
```bash
docker compose up -d postgres redis qdrant minio
```

### Paso 3: Configurar el Backend (data-engine)
```bash
cd data-engine

# Sincronizar dependencias exactas congeladas con uv
uv sync --frozen --extra test --extra dev --no-install-project

# Configurar variables de entorno local
cp .env.example .env

# Ejecutar migraciones de base de datos
uv run alembic upgrade head

# Iniciar servidor de desarrollo FastAPI
uv run uvicorn main:app --reload --port 8000
```

### Paso 4: Configurar el Frontend (Next.js)
En una nueva terminal desde la raíz del proyecto:
```bash
# Instalar dependencias de Node.js
npm install

# Iniciar servidor de desarrollo Next.js
npm run dev
```
La aplicación web estará disponible en `http://localhost:3000` y la documentación de la API en `http://localhost:8000/docs`.

---

## 3. Flujos de Trabajo Habituales de Desarrollo

### Ejecución de Quality Gates del Backend
Antes de abrir una Pull Request o commitear cambios:
```bash
cd data-engine

# 1. Verificación de estilo y linting
uv run ruff check .

# 2. Análisis estático de tipos (0 errores requeridos)
uv run pyright

# 3. Exportación aditiva de OpenAPI
uv run python scripts/export_openapi.py

# 4. Suite completa de tests unitarios e integración
APP_ENV=test uv run pytest -q -p no:warnings
```

### Ejecución de Quality Gates del Frontend
Desde la raíz del proyecto:
```bash
# 1. Linting con ESLint
npm run lint

# 2. Comprobación de tipos con TypeScript
npm run typecheck

# 3. Tests unitarios con Jest
npm test
```

---

## 4. Resolución de Incidencias Frecuentes en el Entorno Local

1. **Error `ConnectionRefusedError: [Errno 111]` al conectar a Postgres**:
   - Asegúrate de que el contenedor de PostgreSQL está levantado: `docker compose ps`.
   - Comprueba que la variable `DATABASE_URL` en `data-engine/.env` apunta a `localhost:5432` en lugar del nombre de host del contenedor.
2. **Error `HMAC signature missing or invalid` en peticiones frontend**:
   - Comprueba que la clave `RESEARCH_AUTH_SECRET` en `.env.local` (frontend) coincide exactamente con la de `data-engine/.env` (backend).
3. **Fallo en tests con `EPERM` en Windows**:
   - Ejecuta los comandos con permisos adecuados o en una sesión de terminal elevada si el antivirus bloquea la creación de temporales en `.pytest_cache`.
