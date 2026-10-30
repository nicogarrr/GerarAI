"""FastAPI bootstrap for the GerarAI data engine."""

import asyncio
import logging
import math
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DataError as SQLAlchemyDataError

from app.api.router import api_router as research_api_router
from app.api.routes.health import router as health_router
from app.core.auth import get_research_principal
from app.core.config import get_settings
from app.core.database import SessionLocal, init_db
from app.core.llm_tenant_scope import bind_llm_cache_tenant
from app.core.rate_limit import AuthFailureLimitMiddleware, enforce_rate_limit
from app.core.raw_body import RawBodyMiddleware
from app.llm.factory import validate_llm_configuration
from app.llm.model_aliases import configure_model_aliases
from app.seed import apply_master_taxonomy_to_stubs, ensure_company_master
from app.services.tenant_llm_settings_service import bind_tenant_llm_settings

try:  # preload optional probe modules during process startup, not in a request
    import urllib.request  # noqa: F401

    import redis  # noqa: F401
except Exception:  # noqa: BLE001 — readiness reports the unavailable dependency
    pass


def _start_embedder_warmup(settings) -> None:
    """Precarga el embedder en un hilo: sin bloquear el arranque y fail-open."""
    import threading

    def _run() -> None:
        from app.services.hybrid_retrieval import warm_models

        ready = warm_models(
            str(getattr(settings, "rag_dense_model", "") or "sentence-transformers/all-MiniLM-L6-v2")
        )
        if not ready:
            # fastembed no pudo cargar (p. ej. HF_HUB_OFFLINE=1 sin su modelo en cache):
            # las busquedas caeran al fallback sentence-transformers, asi que se
            # precalienta ese para que la primera consulta no pague ~9 s de carga.
            try:
                from app.services.rag import RAGIndex

                RAGIndex.warm_fallback()
            except Exception as exc:  # noqa: BLE001 - el warmup jamas rompe el arranque
                import logging

                logging.getLogger(__name__).warning(
                    "fallback embedder warmup skipped (%s: %s)", type(exc).__name__, exc
                )

    threading.Thread(target=_run, name="embedder-warmup", daemon=True).start()


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    if "app_env" not in settings.model_fields_set:
        # app_env tiene default "local": sin APP_ENV explicito la API arrancaba
        # con auth firmada/rate limit/nonce en modo local (fail-open). El API
        # exige declararlo; los workers no pasan por aqui.
        raise RuntimeError(
            "APP_ENV is not set: refusing to start the API with the implicit 'local' default"
        )
    if settings.app_env.lower() != "test":
        from app.core.database import engine as _engine
        from app.core.pool_probe import install as _install_pool_probe

        _install_pool_probe(_engine)
    if settings.app_env.lower() == "test":
        # Tests use an isolated disposable schema. Runtime environments migrate
        # with Alembic before the process starts.
        init_db()
    with SessionLocal() as db:
        configure_model_aliases(db)
    validate_llm_configuration(settings)
    if settings.app_env.lower() != "production":
        ensure_company_master()
    else:
        with SessionLocal() as db:
            apply_master_taxonomy_to_stubs(db)
            db.commit()

    # Schedule the worker jobs (Dramatiq enqueues) in the background without
    # blocking startup. Flagged off in tests via WORKERS_ENABLED=false.
    scheduler = None
    if settings.workers_enabled:
        from app.workers.scheduler import build_scheduler

        scheduler = build_scheduler(background=True)
        scheduler.start()

    if settings.app_env.lower() == "production":
        _start_embedder_warmup(settings)

    if settings.app_env.lower() != "test":
        # FastAPI construye cada ruta perezosamente en la primera peticion que
        # la recorre (cientos de ms tras cada arranque). Se adelanta en un hilo
        # de fondo; en tests no, porque cada TestClient arrancaria otro hilo.
        from app.core.route_warmup import start_route_warmup

        start_route_warmup(app)

    yield

    if scheduler is not None:
        scheduler.shutdown(wait=False)
    # Los executores de sonda son de nivel de modulo: sin apagarlos, un
    # TestClient que abre y cierra muitas veces deja hilos vivos por proceso.
    # wait=False porque pueden tener sondas colgadas.
    _HEALTH_REQUIRED_EXECUTOR.shutdown(wait=False)
    _HEALTH_PROBE_EXECUTOR.shutdown(wait=False)
    _HEALTH_LLM_EXECUTOR.shutdown(wait=False)
    # Cliente Yahoo compartido de /api/market/quote y /candles (keep-alive).
    from app.api.routes.market import close_shared_yahoo_client

    close_shared_yahoo_client()


_app_env = get_settings().app_env.strip().lower()
_EXPOSE_SCHEMA = _app_env in {"local", "test", "ci", "dev", "development"}

# /docs, /redoc y /openapi.json se montan SIN firma porque cuelgan de app, no
# del research router. Publicar el esquema completo de las 188 rutas firmadas es
# un plano gratis para quien intente reutilizar una firma capturada. Solo se
# exponen en entornos locales; data-engine/scripts/export_openapi.py sigue
# generando el JSON via app.openapi() sin necesidad de HTTP.
app = FastAPI(
    title="GerarAI Research Engine",
    version="0.9.0",
    lifespan=lifespan,
    docs_url="/docs" if _EXPOSE_SCHEMA else None,
    redoc_url="/redoc" if _EXPOSE_SCHEMA else None,
    openapi_url="/openapi.json" if _EXPOSE_SCHEMA else None,
)

app.add_middleware(
    RawBodyMiddleware,
    # Sin cabecera de firma el request no puede pasar la auth: tope de 1MB
    # en vez de bufferizar 10-16MB antes de rechazarlo.
    max_unsigned_body_bytes=1024 * 1024,
    max_body_bytes_by_prefix={
        # La ruta de subida valida contra MAX_DOCUMENT_BYTES (15MB); el
        # middleware le deja pasar hasta 16MB para que sea ella quien
        # responda con su error de validacion, no un 413 generico.
        "/api/knowledge/documents/upload": 16 * 1024 * 1024,
        # Misma regla para la ingesta de fuentes: la ruta valida el fichero
        # decodificado contra MAX_DOCUMENT_BYTES (15MB) y el middleware deja
        # margen de ~1MB para el overhead multipart (boundaries + headers).
        "/api/sources/documents/ingest-file": 16 * 1024 * 1024,
    },
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-CavaAI-Tenant", "X-CavaAI-User", "X-CavaAI-Timestamp", "X-CavaAI-Nonce", "X-CavaAI-Method", "X-CavaAI-Path", "X-CavaAI-Body-Hash", "X-CavaAI-Signature"],
)
# #E5: latencia por endpoint. ASGI puro (no BaseHTTPMiddleware, que paga una
# tarea extra por request), etiqueta por PLANTILLA de ruta y agrega por ventana
# en un hilo daemon. Se autodesactiva con APP_ENV=test para no escribir en la BD
# de la sesion de tests. El coste que se anade a cada request se mide y se expone
# en `overhead_*`.
app.add_middleware(AuthFailureLimitMiddleware)
if get_settings().app_env.lower() != "test":
    from app.core.pool_probe import SlowRequestMiddleware

    app.add_middleware(SlowRequestMiddleware)

private_dependencies = [
    Depends(get_research_principal),
    Depends(enforce_rate_limit),
    Depends(bind_llm_cache_tenant),
    Depends(bind_tenant_llm_settings),
]


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Cierre de red para excepciones no capturadas.

    Sin esto, cualquier error que se escape de un handler devolvía el
    ``{"detail": "Internal Server Error"}`` pelado de FastAPI, sin id de
    correlación: era imposible casar un reporte de usuario con el log.
    """
    from app.core.errors import safe_detail

    detail = safe_detail(exc, 500)
    # nosemgrep: gerarai-broad-except-pass -- el seguimiento de errores nunca cambia la respuesta 500
    try:
        from app.core.error_reporting import report_exception

        report_exception(
            exc, ref=detail.rsplit("ref: ", 1)[-1].rstrip(")"),
            method=request.method, path=request.url.path,
        )
    except Exception:  # noqa: BLE001
        pass
    return JSONResponse(
        status_code=500,
        content={"detail": detail},
    )



async def db_value_out_of_range_handler(request: Request, exc: Exception) -> JSONResponse:
    """Entero o valor que la BD no puede representar (p. ej. ``offset=2**63``).

    Sin esto llegaba al handler genérico y devolvía 500: SQLite lanza
    OverflowError al enlazar el parámetro y Postgres DataError («bigint out of
    range»). Es entrada inválida del cliente, así que 422. Un OverflowError que
    no viene de la BD se trata como cualquier excepción no controlada (500).
    """
    from app.core.errors import MSG_VALUE_OUT_OF_RANGE, is_db_value_out_of_range

    if is_db_value_out_of_range(exc):
        return JSONResponse(status_code=422, content={"detail": MSG_VALUE_OUT_OF_RANGE})
    return await unhandled_exception_handler(request, exc)


def _finite_json(value):
    """NaN/±Infinity -> texto, recursivo: JSON estricto no los admite."""
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, dict):
        return {key: _finite_json(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_finite_json(item) for item in value]
    return value


async def request_validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """422 de validación que siempre se puede serializar.

    El cuerpo JSON admite ``NaN``/``Infinity`` (``json.loads`` los acepta) y el
    422 por defecto de FastAPI devuelve el ``input`` rechazado: al serializarlo
    con ``allow_nan=False`` reventaba con ValueError y la petición acababa en
    500. Mismo contenido que el 422 por defecto, con esos valores como texto.
    """
    return JSONResponse(status_code=422, content={"detail": _finite_json(jsonable_encoder(exc.errors()))})


app.add_exception_handler(RequestValidationError, request_validation_error_handler)
app.add_exception_handler(OverflowError, db_value_out_of_range_handler)
app.add_exception_handler(SQLAlchemyDataError, db_value_out_of_range_handler)


async def upstream_network_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Proveedor externo caído o inaccesible (Yahoo, FRED, SEC, Finnhub...).

    Varios handlers solo capturaban RuntimeError y la excepción de red del
    cliente HTTP (httpx, requests, curl_cffi de yfinance) llegaba al handler
    genérico: 500 «Internal server error», como si fallara el motor. Es un
    fallo del proveedor: 502 con id de correlación y sin el texto crudo (que
    puede llevar la URL con la api key; safe_detail lo redacta en el log).
    """
    from app.core.errors import safe_detail

    return JSONResponse(status_code=502, content={"detail": safe_detail(exc, 502)})


def _upstream_network_errors() -> list[type[Exception]]:
    import httpx
    import requests

    errors: list[type[Exception]] = [httpx.HTTPError, requests.RequestException]
    try:
        from curl_cffi.requests.exceptions import RequestException as CurlRequestException
    except ImportError:  # pragma: no cover - curl_cffi llega con yfinance
        pass
    else:
        errors.append(CurlRequestException)
    return errors


for _upstream_error in _upstream_network_errors():
    app.add_exception_handler(_upstream_error, upstream_network_error_handler)


async def job_queue_unavailable_handler(request: Request, exc: Exception) -> JSONResponse:
    """Redis (cola de trabajos) caído al encolar: 503 explícito, no 500 genérico.

    Los endpoints «-async»/«refresh» encolan con Dramatiq; con Redis caído el
    ``.send()`` lanzaba ``redis.exceptions.ConnectionError`` y la petición
    acababa en un 500 «Internal server error» sin causa. No se ha encolado
    nada, así que es un 503 reintentable y queda en el log con ruta y causa.
    """
    logging.getLogger("gerarai.job_queue").warning(
        "job_queue_unavailable path=%s cause=%s", request.url.path, type(exc).__name__
    )
    return JSONResponse(
        status_code=503,
        content={"detail": "Background job queue unavailable; nothing was queued. Try again shortly."},
        headers={"Retry-After": "30"},
    )


try:
    import redis.exceptions as _redis_exceptions
except ImportError:  # pragma: no cover - redis llega con dramatiq
    pass
else:
    for _queue_error in (_redis_exceptions.ConnectionError, _redis_exceptions.TimeoutError):
        app.add_exception_handler(_queue_error, job_queue_unavailable_handler)

# /api/health es público (sin firma): lo montamos fuera del research API
# para que orquestación/monitoreo pueda consultarlo sin identidad.
app.include_router(health_router, prefix="/api")

from app.api.routes.telegram_link import relay_router  # noqa: E402

app.include_router(relay_router)

# Feed ICS publico (token en la URL, sin identidad firmada): fuera de
# private_dependencies, con limite por IP. Las rutas /api/calendar/feed
# GET/POST/DELETE siguen autenticadas dentro de research_api_router.
from app.api.routes.calendar import public_router as calendar_public_router  # noqa: E402
from app.core.rate_limit import enforce_public_ip_rate_limit  # noqa: E402

app.include_router(
    calendar_public_router,
    prefix="/api/calendar",
    tags=["calendar"],
    dependencies=[Depends(enforce_public_ip_rate_limit)],
)

app.include_router(
    research_api_router,
    prefix="/api",
    dependencies=private_dependencies,
)


@app.get("/")
async def root():
    return {"status": "ok", "service": "GerarAI Research Engine"}


@app.get("/health")
@app.get("/health/live")
async def health_live():
    """Liveness — process is up. Does not check dependencies."""
    return {"status": "ok"}


HEALTH_READY_TIMEOUT_SECONDS = 1.0
# Dos executors y no uno. La BD es la unica dependencia hard-required: si
# comparte pool con Redis/Qdrant/MinIO, tres sondas opcionales que se quedan
# colgadas (aceptan la conexion y nunca responden) consumian los 4 hilos y la
# sonda de BD ya nofindaba ninguno -> checks["database"] != "ok" -> 503
# permanente con la base de datos perfectamente sana, y sin reaper que lo
# desbloquee. asyncio.wait_for cancela la espera, no el hilo.
_HEALTH_REQUIRED_EXECUTOR = ThreadPoolExecutor(
    max_workers=2, thread_name_prefix="gerarai-health-required"
)
# Un executor dedicado evita que ``asyncio.run``/el cierre de un test espere a
# los hilos de sondas que vencieron su timeout. Las sondas conservan su propio
# timeout de red y los hilos remanentes terminan solos al concluir.
_HEALTH_PROBE_EXECUTOR = ThreadPoolExecutor(
    max_workers=4, thread_name_prefix="gerarai-health-probe"
)
# La sonda LLM es barata (config + bridge local) pero hard-required: un pool
# propio evita que sondas opcionales colgadas la dejen sin hilo y conviertan
# un backend sano en 503.
_HEALTH_LLM_EXECUTOR = ThreadPoolExecutor(
    max_workers=1, thread_name_prefix="gerarai-health-llm"
)


def _probe_database(_settings) -> str:
    """Comprueba la BD sin convertir errores de infraestructura en 500."""
    from sqlalchemy import text

    from app.core.database import SessionLocal

    with SessionLocal() as db:
        # statement_timeout acota la sonda a nivel de servidor. Sin el, un
        # lock de Postgres puede dejar el hilo bloqueado indefinidamente y
        #Slottear el executor dedicado para siempre. En SQLite no aplica.
        if db.bind is not None and db.bind.dialect.name == "postgresql":
            db.execute(text("SET LOCAL statement_timeout = '1s'"))
        db.execute(text("SELECT 1"))
    return "ok"


def _probe_redis(settings) -> str:
    """Redis es opcional en SQLite local, pero su estado se reporta siempre."""
    import redis

    from app.core.redis_retry import no_retry

    client = redis.from_url(
        settings.redis_url,
        socket_connect_timeout=HEALTH_READY_TIMEOUT_SECONDS,
        socket_timeout=HEALTH_READY_TIMEOUT_SECONDS,
        retry=no_retry(),
    )
    client.ping()
    return "ok"


def _probe_qdrant(settings) -> str:
    """Qdrant liveness; un 4xx/5xx nunca se considera una respuesta sana.

    Unificado con docker-compose (GET /healthz vía bash /dev/tcp).
    /readyz exigía colecciones/shards listos y marcaba degraded en
    arranques fríos aunque Qdrant ya aceptaba tráfico.
    """
    import urllib.request

    with urllib.request.urlopen(
        f"{settings.qdrant_url.rstrip('/')}/healthz",
        timeout=HEALTH_READY_TIMEOUT_SECONDS,
    ) as resp:
        return "ok" if resp.status < 500 else f"error:status_{resp.status}"


def _probe_minio(settings) -> str:
    """MinIO: cualquier respuesta HTTP <500 prueba que el endpoint está vivo."""
    import urllib.error
    import urllib.request

    endpoint = settings.minio_endpoint
    if not endpoint.startswith("http"):
        endpoint = f"http://{endpoint}"
    try:
        with urllib.request.urlopen(
            endpoint, timeout=HEALTH_READY_TIMEOUT_SECONDS
        ) as resp:
            return "ok" if resp.status < 500 else f"error:status_{resp.status}"
    except urllib.error.HTTPError as exc:
        return "ok" if exc.code < 500 else f"error:status_{exc.code}"


def _probe_llm(settings) -> str:
    """Comprueba la configuracion LLM sin generar ni llamar a proveedores remotos.

    Un proveedor deshabilitado o una config incoherente (sin clave, modelo no
    aprobado, URL invalida) devuelve ``error:<motivo>``. Si la URL apunta al
    bridge local, se sondea su ``/health`` con timeout corto; el endpoint Go
    oficial nunca se contacta desde readiness.
    """
    from app.llm.readiness import bridge_health_url, llm_configuration_issue

    issue = llm_configuration_issue(settings)
    if issue:
        return f"error:{issue}"
    health_url = bridge_health_url(getattr(settings, "opencode_go_base_url", ""))
    if not health_url:
        return "ok"
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(health_url, timeout=HEALTH_READY_TIMEOUT_SECONDS) as resp:
            return "ok" if resp.status < 500 else f"error:status_{resp.status}"
    except urllib.error.HTTPError as exc:
        return "ok" if exc.code < 500 else f"error:status_{exc.code}"
    except Exception as exc:  # noqa: BLE001 — readiness reports the failure class
        return f"error:{type(exc).__name__}"


async def _run_health_probe(
    name: str, probe, settings, executor=None
) -> tuple[str, str]:
    """Ejecuta una sonda en un hilo y la corta al deadline compartido."""
    try:
        loop = asyncio.get_running_loop()
        future = loop.run_in_executor(
            executor or _HEALTH_PROBE_EXECUTOR, probe, settings
        )
        result = await asyncio.wait_for(
            future,
            timeout=HEALTH_READY_TIMEOUT_SECONDS,
        )
        return name, str(result)
    except TimeoutError:
        return name, "error:TimeoutError"
    except Exception as exc:  # noqa: BLE001 — reportar y continuar
        return name, f"error:{type(exc).__name__}"


@app.get("/health/ready")
async def health_ready():
    """Readiness concurrente: la BD es la única dependencia hard-required local.

    Redis, Qdrant y MinIO se sondean simultáneamente, con un timeout de un
    segundo. Una dependencia caída se informa en la respuesta, pero no mantiene
    bloqueada la ruta ni convierte un backend SQLite sano en 503.
    """
    settings = get_settings()
    # La BD va a un executor propio: es la unica que puede tirar el 503, y no
    # puede quedarse sin hilo por culpa de las opcionales.
    results = await asyncio.gather(
        _run_health_probe(
            "database", _probe_database, settings, _HEALTH_REQUIRED_EXECUTOR
        ),
        *(
            _run_health_probe(name, probe, settings)
            for name, probe in (
                ("redis", _probe_redis),
                ("qdrant", _probe_qdrant),
                ("minio", _probe_minio),
            )
        ),
        _run_health_probe("llm", _probe_llm, settings, _HEALTH_LLM_EXECUTOR),
    )
    checks = dict(results)

    # La BD y una configuración LLM sana son hard-required: sin cerebro no hay
    # producto. Redis, Qdrant y MinIO se reportan sin convertir una caída
    # opcional en un 503 ni alargar la ruta.
    ready = checks.get("database") == "ok" and checks.get("llm") == "ok"

    from fastapi.responses import JSONResponse

    return JSONResponse(
        status_code=200 if ready else 503,
        content={
            "status": "ready" if ready else "degraded",
            "checks": checks,
        },
    )
