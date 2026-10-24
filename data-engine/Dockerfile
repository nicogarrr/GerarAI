FROM python:3.12-slim

WORKDIR /app

# Salud: la capa de salud es docker-compose (healthcheck del servicio
# backend con /health/ready). Este Dockerfile no declara HEALTHCHECK propio
# para no duplicar la sonda ni enmascarar el estado real del compose.

# System deps for scipy / numpy / arch
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps first (better layer caching)
COPY requirements.txt .
# torch CPU-only primero (mismo pin que requirements.txt y Dockerfile.prod):
# sentence-transformers lo exige, y la wheel CUDA por defecto de PyPI son
# GB inservibles en una maquina CPU-only. Ver --extra-index-url en
# requirements.txt y data-engine/scripts/sync_requirements.py.
RUN pip install torch==2.14.1+cpu --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir --no-deps "pillow==13.0.0"

# Copy source (quantstats package is vendored inside data-engine/)
COPY . .

EXPOSE 8000

# Sin shell ni root: el compose de desarrollo monta el arbol de fuentes y el
# volumen duckdb_data en /app.
RUN groupadd --system cavaai && useradd --system --gid cavaai --no-create-home cavaai \
    && chown -R cavaai:cavaai /app
# /data es el punto de montaje del volumen duckdb_data en produccion. Un
# volumen nuevo se inicializa copiando contenido Y PROPIETARIO de esta ruta
# de la imagen; sin el chown quedaria root-owned y el backend (USER cavaai)
# no podria escribir analytics.duckdb.
RUN mkdir -p /data && chown cavaai:cavaai /data
USER cavaai

# `exec` para que uvicorn sea PID 1 y reciba el SIGTERM de `docker stop`;
# con `sh -c` a secas la senal se queda en sh y a los 10 s llega SIGKILL.
CMD ["sh", "-c", "python -m alembic upgrade head && exec uvicorn main:app --host 0.0.0.0 --port 8000"]
