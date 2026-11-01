import json
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Self
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# Los unicos APP_ENV que authorizes a saltarse las garantias de produccion.
# Todo lo demas (incluidos 'staging', 'preprod' y los typos) se trata como
# produccion:Settings.is_production es una denylist, no una allowlist.
_NON_PRODUCTION_ENVS = frozenset({"local", "test", "ci", "dev", "development"})

# Credenciales de desarrollo conocidas: jamas validas en produccion.
_WEAK_CREDENTIAL_PAIRS = {
    "postgres:postgres",
    "postgres:password",
    "postgres:secret",
    "postgres:example",
    "postgres:changeme",
    "postgres:change-me",
    "mongo:mongo",
    "mongo:password",
    "root:root",
    "root:password",
    "root:example",
    "admin:admin",
    "user:password",
    "cavaai:cavaai",
    "cavaai:example",
}
_WEAK_PASSWORDS = {
    "password",
    "secret",
    "example",
    "pass",
    "test",
    "root",
    "admin",
    "changeme",
    "change-me",
    "123456",
}
_WEAK_MINIO_SECRET_KEYS = {
    "portfoliosecret",
    "portfolio",
    "minioadmin",
    "minio-secret",
    "minioadmin123",
    "change-me",
    "secret",
}
_WEAK_MINIO_ACCESS_KEYS = {"minioadmin", "minio", "admin", "change-me", "portfolio"}
# Plantillas del .env.production.example que NUNCA son un secreto real. El
# arranque en produccion falla si alguna llega a un campo sensible.
_PLACEHOLDER_TOKENS = (
    "cambia-esto",
    "cambia_esto",
    "cambia esto",
    "cambiame",
    "genera-",
    "genera_",
    "generame",
    "generar-",
    "generar_",
    "tu-correo",
    "tu-email",
    "tudominio",
    "example.com",
    "changeme",
    "change-me",
    "replace-me",
    "your-secret",
    "your-password",
)


def _url_credentials(url: str) -> tuple[str | None, str | None]:
    try:
        parts = urlsplit(url)
    except ValueError:
        return None, None
    if "@" not in parts.netloc:
        return None, None
    userinfo = parts.netloc.rsplit("@", 1)[0]
    user, sep, password = userinfo.partition(":")
    return (user or None, password if sep else None)


def _assert_strong_credentials(url: str, *, label: str) -> None:
    user, password = _url_credentials(url)
    if not user or not password:
        raise ValueError(f"{label} must include a username and password in production")
    pair = f"{user}:{password}".lower()
    if pair in _WEAK_CREDENTIAL_PAIRS or password.lower() in _WEAK_PASSWORDS:
        raise ValueError(f"{label} must not use default development credentials in production")
    _assert_not_placeholder(password, label=label)


def _assert_not_placeholder(value: str, *, label: str) -> None:
    """Rechaza las plantillas copiadas del .env.production.example.

    No imprime el valor (puede ser un secreto): solo la etiqueta del campo.
    """
    normalized = value.strip().lower()
    for token in _PLACEHOLDER_TOKENS:
        if token in normalized:
            raise ValueError(
                f"{label} still contains a placeholder ({token!r}); "
                "set a real value in .env.production"
            )


#: Esfuerzo de razonamiento POR SECCION: la unica tabla. Medido el
#: 2026-10-27 con 140 llamadas reales a deepseek-v4.1-flash (OpenCode Go) a
#: Default/Low/High/Max: la calidad (juez ciego + comprobaciones
#: deterministas) no mejora por encima de low en ninguna seccion salvo un
#: margen pequeno en el analisis de cartera, y high/max tardan 1,5-2,7x mas.
#: Override por env (solo las secciones que quieras cambiar):
#: LLM_REASONING_EFFORT_BY_SECTION='{"tesis_profunda":"high"}'.
LLM_REASONING_EFFORT_DEFAULTS: dict[str, str] = {
    "chat_consulta": "low",  # dato concreto de un valor (precio, ratio, cifra)
    "chat_cartera": "high",  # analisis de la cartera completa
    "chat_general": "low",  # preguntas generales sin datos privados
    "tesis_profunda": "low",  # narrativa extensa de la tesis
    "tesis_noticias": "low",  # narrativa de noticias de la tesis
    "debate": "low",  # debate alcista/bajista y juez
    "traduccion_titular": "low",  # titulares de noticias al espanol
    "extraccion": "low",  # KPIs y extracciones estructuradas
    "segundo_orden": "low",  # hipotesis de segundo orden de una noticia
    "asts": "low",  # analisis del catalogo satelital de AST
}
#: "none" desactiva el razonamiento; "" = no enviar el parametro.
LLM_REASONING_EFFORT_VALUES = frozenset({"", "none", "low", "high", "max"})


class Settings(BaseSettings):
    # extra=ignore a propósito: .env comparte claves de frontend
    # (BETTER_AUTH_*, TWELVE_DATA_*, etc.) que el backend no modela.
    # Los typos de claves backend se cubren con tests de contrato
    # (test_settings_hermeticity) en vez de forbid global.
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # EIA Open Data: optional, never exposed in payloads or source links.
    eia_api_key: str | None = None

    app_env: str = "local"
    app_name: str = "GerarAI Research Engine"
    api_prefix: str = "/api"
    # NoDecode: la plantilla (docker.env.example) y cualquier .env escriben
    # CORS_ORIGINS como lista separada por comas; pydantic-settings intentaria
    # leerlo como JSON y tumbaria el arranque. Ver _parse_cors_origins.
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000", "http://127.0.0.1:3000"]
    )

    # Research OS is private by default. Tests that intentionally exercise the
    # public dependency graph must opt out explicitly with
    # RESEARCH_AUTH_REQUIRED=false.
    # OJO: desactivarlo no solo abre la API, tambien desactiva el aislamiento
    # multitenant (ver _scope_tenant_queries/_scope_tenant_dml en
    # app/core/database.py). validate_production_security lo rechaza en
    # produccion.
    research_auth_required: bool = True
    # Obliga a que la firma HMAC cubra method+path+body_hash+nonce. Antes el
    # flag no existia en Settings (extra="ignore" lo descartaba en silencio) y
    # el getattr de app/core/auth.py devolvia False para siempre: fuera de
    # produccion la firma era solo tenant:user:timestamp, reproducible y
    # reutilizable en cualquier verbo, path y body durante la ventana de 300 s.
    research_auth_strict_binding: bool = True
    research_auth_secret: str | None = Field(default=None, repr=False, min_length=32)
    research_auth_max_age_seconds: int = Field(default=300, ge=30, le=3600)
    rate_limit_enabled: bool = True
    # Worker scheduler (APScheduler jobs that enqueue Dramatiq actors). Disabled
    # in tests via WORKERS_ENABLED=false so TestClient lifespans stay quiet.
    workers_enabled: bool = True
    rate_limit_requests_per_minute: int = Field(default=300, ge=10, le=10000)
    # Supuesto de coste del paper trading (paper_cost_service): comision fija
    # por ejecucion EN LA DIVISA DEL TRADE y spread en bps del nocional. Son
    # supuestos rotulados, no la tarifa de ningun broker; cambiarlos solo
    # afecta a ejecuciones futuras (el set queda persistido por trade).
    paper_trade_commission_flat: Decimal = Field(default=Decimal("1.00"), ge=0)
    paper_trade_spread_bps: Decimal = Field(default=Decimal("5"), ge=0)
    # Lecturas de mercado (quote/candles/movers/indices): el frontend abanica
    # una llamada por ticker y pagina (ProPicks ~20, backtest ~60) y Vercel
    # serverless no comparte la cache entre instancias -> rafagas grandes en
    # uso normal. Tier propio y alto; son lecturas baratas cacheadas.
    rate_limit_market_requests_per_minute: int = Field(default=900, ge=10, le=100000)
    rate_limit_expensive_requests_per_minute: int = Field(default=20, ge=1, le=1000)
    # Suelo del limite SOLO en local. Antes se deducía de app_env in
    # {"local","test"} dentro de app/core/rate_limit.py, así que 'dev', 'ci' y
    # 'development' se quedaban sin limite real (10000/min) mientras si
    # exigian Redis. Ahora es un valor explicito y la prediccion es una sola.
    rate_limit_local_request_floor: int = Field(default=10000, ge=0)
    financial_document_retention_days: int = Field(default=2555, ge=1)
    # Retencion de la pregunta cruda de chat (chat_telemetry_events). El
    # evento agregado (ruta/modelo/latencia) no se publica fuera del tenant.
    chat_telemetry_retention_days: int = Field(default=90, ge=1)
    # Purga automatica opt-in: apagada por defecto y, cuando se enciende,
    # nace en modo dry-run. El operador la activa en el scheduler.
    retention_job_enabled: bool = False
    retention_dry_run: bool = True
    retention_batch_limit: int = Field(default=500, ge=1, le=10000)
    # Legacy setting remains parse-compatible; consumers cap freshness at 24h.
    market_price_max_age_days: int = Field(default=1, ge=0, le=30)

    database_url: str = "sqlite:///./portfolio_research_os.db"
    # Pool SQLAlchemy SOLO para Postgres (database.py ignora estos valores con
    # sqlite). Backend: 10+10 conexiones; workers: 4+2 via compose. Juntos
    # quedan muy por debajo de max_connections=200 del Postgres de prod.
    db_pool_size: int = Field(default=10, ge=1, le=200)
    db_max_overflow: int = Field(default=10, ge=0, le=200)
    db_pool_timeout: float = Field(default=30.0, gt=0, le=300)
    db_pool_recycle: int = Field(default=3600, ge=0)
    # Defensa de red tras los commits de #1657: una transaccion abierta y
    # olvidada en un worker no puede bloquear tablas mas de 2 minutos. Solo
    # Postgres (se pasa via connect_args options); 0 lo desactiva.
    idle_in_transaction_session_timeout_ms: int = Field(default=120000, ge=0)
    thesis_graph_checkpoint_path: Path = Path("./storage/thesis_graph_checkpoints.db")
    redis_url: str = "redis://localhost:6379/0"
    qdrant_url: str = "http://localhost:6333"
    duckdb_path: Path = Path("./storage/analytics.duckdb")
    # Retrieval hibrido denso+sparse sobre Qdrant (ver app/services/rag.py y
    # app/services/hybrid_retrieval.py). Todo aditivo y apagado por defecto:
    # con los defaults el RAG se comporta exactamente como antes.
    # backend denso: "fastembed" (ONNX CPU, mismo modelo/dims/vectores que
    # sentence-transformers) o "sentence-transformers" (legacy).
    rag_embedding_backend: str = "fastembed"
    # Modelo denso por defecto: MISMO modelo y dims (384) que produccion.
    # Cambiar de modelo con mismos dims conserva la coleccion pero mezcla
    # espacios: reindexar con RAGIndex().rebuild_tenant por tenant.
    # Cambiar de dims exige coleccion nueva (rag_collection) + rebuild.
    rag_dense_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    rag_dense_dims: int = Field(default=384, ge=1, le=4096)
    # Override opt-in de coleccion (None = la historica
    # "portfolio_research_documents"). Solo para cambios de dims/modelo.
    rag_collection: str | None = None
    # Sparse sibling (BM25 estadistico via fastembed, ~10 MB, multilingue).
    # Apagado por defecto: la ingesta/busqueda densa no cambia.
    rag_hybrid_enabled: bool = False
    rag_sparse_model: str = "Qdrant/bm25"
    rag_sparse_vector_name: str = "bm25"
    # Fusion RRF (lado cliente, igual semantica que el RRF de Qdrant >= 1.10;
    # k y pesos configurables sin depender de la version del servidor. Prod ya
    # va en 1.19.2 (los pesos de servidor, >= 1.17, serian posibles; la fusion
    # sigue en cliente: mismo resultado, sin acoplar al despliegue).
    rag_rrf_k: int = Field(default=60, ge=1, le=1000)
    rag_dense_weight: float = Field(default=1.0, ge=0.0, le=100.0)
    rag_sparse_weight: float = Field(default=1.0, ge=0.0, le=100.0)
    # RAG de conocimiento profesional (app/services/knowledge_rag/). Coleccion
    # PROPIA, separada de portfolio_research_documents. Apagado por defecto:
    # sin el flag la API responde 503 y el actor rechaza el trabajo.
    knowledge_rag_enabled: bool = False
    # La coleccion por defecto va con el denso por defecto: v2 es 1024 dims
    # (e5-large); knowledge_rag_v1 era la del piloto a 384 (MiniLM).
    knowledge_rag_collection: str = "knowledge_rag_v2"
    # Directorio (montado) del que el actor puede leer ficheros. La API NUNCA
    # acepta rutas absolutas ni sube bytes: solo nombres relativos a este dir.
    knowledge_rag_inbox_dir: Path = Path("./storage/knowledge_inbox")
    knowledge_rag_max_file_mb: int = Field(default=60, ge=1, le=500)
    # Guarda de disco: el VM va justo. Ingesta rechazada si queda menos libre.
    knowledge_rag_min_free_gb: float = Field(default=3.0, ge=0.0, le=1000.0)
    # Chunks: margen bajo el truncado de ambos densos (MiniLM 256 wp, e5-large 512 wp).
    knowledge_rag_child_max_tokens: int = Field(default=200, ge=32, le=250)
    knowledge_rag_child_overlap_tokens: int = Field(default=50, ge=0, le=100)
    knowledge_rag_parent_max_tokens: int = Field(default=900, ge=200, le=4000)
    # Docling minimo: sin OCR, sin VLM, sin ASR. Tablas: "fast" (~145 MB) o
    # "accurate" (~213 MB).
    knowledge_rag_docling_ocr: bool = False
    knowledge_rag_docling_table_mode: str = "fast"
    # Reranker CPU opcional (vacio = desactivado). Ver docs/knowledge-rag.md.
    knowledge_rag_reranker_model: str = ""
    # Ventana de candidatos (denso+sparse fusionados por RRF) que llega al
    # reranker. Medida offline sobre el dataset piloto (38 casos, hit@6):
    # 40 -> 21/38; 100 -> 26/38. Por encima de 100 no entran mas aciertos
    # cross-lingual con este reranker (limite conocido: ver docs/knowledge-rag.md).
    knowledge_rag_candidates: int = Field(default=100, ge=10, le=500)
    # Traduccion de consulta ES->EN (F372): si la pregunta parece espanol se
    # busca TAMBIEN con su traduccion al ingles (la biblioteca mezcla doctrina
    # EN y ES y BM25 no cruza idiomas). Solo el modelo gratuito verificado;
    # sin clave o con el proveedor caido degrada a buscar solo con la original.
    knowledge_rag_query_translation: bool = True
    knowledge_rag_query_translation_timeout_s: float = Field(default=12.0, ge=1.0, le=120.0)
    # Modelo denso PROPIO del conocimiento (ganador v2c del piloto: e5-large
    # multilingue + reranker). NO se reusa rag_dense_model: ese queda en
    # MiniLM 384 para el vector chat legacy (portfolio_research_documents esta
    # indexada en 384 dims). Cambiar este modelo exige coleccion NUEVA:
    # knowledge_rag_v2 lleva 1024 dims.
    knowledge_rag_dense_model: str = "intfloat/multilingual-e5-large"
    knowledge_rag_dense_dims: int = Field(default=1024, ge=1, le=4096)
    minio_endpoint: str = "localhost:9002"
    minio_access_key: str = "portfolio"
    minio_secret_key: str = "portfoliosecret"
    minio_bucket: str = "research"
    # Region S3. Vacia con MinIO (el SDK la autodetecta); "garage" con Garage,
    # que la fija en s3_region de garage.toml.
    minio_region: str = ""
    document_storage_backend: str = "minio"
    # Mongo (auth Better Auth del frontend). Se valida aqui solo para poder
    # rechazar credenciales por defecto en produccion; el data-engine no
    # conecta a Mongo.
    mongodb_uri: str | None = Field(default=None, repr=False)

    finnhub_api_key: str | None = None
    # Vendor de quotes/profile del screener real ("finnhub" | "yahoo").
    # Env: SCREENER_QUOTE_VENDOR. Default Finnhub (comportamiento actual).
    screener_quote_vendor: str = "finnhub"
    # Opt in only after dedicated consumer and measured memory budget are ready.
    ibkr_dedicated_sync_enabled: bool = False
    ibkr_flex_token: str | None = None
    ibkr_flex_query_id: str | None = None
    # Tenant dueño del token Flex (cuenta propietaria). Sin él la sincronizacion
    # periodica no corre: el token es de UNA cuenta y nunca se reparte por tenants.
    ibkr_flex_tenant_id: int | None = None
    # Cuenta IBKR esperada (p. ej. U1234567): sin ella la sync no borra nada.
    ibkr_flex_account_id: str | None = None
    # Declaracion del operador: la consulta con ESTE id es de cuenta completa (sin
    # filtros, todas las secciones). Debe coincidir con IBKR_FLEX_QUERY_ID para que
    # la sync pueda cerrar posiciones; el XML por si solo no lo prueba.
    ibkr_flex_complete_query_id: str | None = None
    # A7: dias que se conservan las filas crudas de FOTO del Flex (posiciones,
    # caja, FX, NAV). Los eventos (operaciones, dividendos) no caducan nunca.
    # 0 = sin poda. Env: IBKR_RAW_ROWS_RETENTION_DAYS.
    ibkr_raw_rows_retention_days: int = 400
    # SEC fair-access: exige UA declarado con contacto; bloquea placeholders
    # tipo example.com con 403. Este valor verificado 200 desde prod (25/9).
    # OJO: este default es un fallback LOCAL no contactable (el dominio .local
    # no existe). En produccion manda SEC_USER_AGENT del .env con un contacto
    # real; la SEC puede bloquear UAs sin contacto verdadero.
    sec_user_agent: str = "GerarAI research contact@gerarai.local"
    # Directorio con snapshots EDGAR (manifest.json ticker->CIK,
    # companyfacts/CIK##########.json, submissions/CIK##########.json).
    # La SEC bloquea las IPs de datacenter; los snapshots se generan fuera
    # (PC residencial, espejo) y se despliegan con la app.
    sec_snapshot_dir: str | None = None
    # Resiliencia del cliente SEC directo (sin proxies ni cambio de IP):
    # cache en memoria de respuestas JSON, reintentos con backoff ante
    # 429/5xx/red y fallback a EDGAR full-text search (efts.sec.gov) para el
    # listado de filings cuando submissions falla. Env: SEC_CACHE_TTL_SECONDS,
    # SEC_MAX_RETRIES, SEC_EFTS_FALLBACK_ENABLED.
    sec_cache_ttl_seconds: float = Field(default=900.0, ge=0)
    sec_max_retries: int = Field(default=3, ge=0, le=8)
    sec_efts_fallback_enabled: bool = True
    # Dataset de HuggingFace que actua como mirror resiliente de la SEC
    # (companyfacts/submissions). Cuando esta configurado y la SEC rechaza
    # con 401/403 (ban de IP de datacenter), la ingesta lee el mismo JSON
    # oficial desde el mirror - solo ante esos codigos: un 404 de la SEC es
    # un fallo de dato y nunca se desvia al mirror. El mirror se sirve solo
    # si su manifest declara synced_at reciente (<= 48h): dato viejo nunca
    # se sirve como fresco. Vacio = solo SEC directo.
    sec_hf_mirror_dataset: str | None = None
    # Emision de jobs process_document para filings SEC desde el worker.
    # La SEC bloquea las IPs de datacenter (403 permanente en OCI): esos
    # jobs siempre fallan y envenenaron la cola default (5276 mensajes,
    # F359). False = no emitirlos; la metadata de filings SEC sigue
    # entrando via el mirror HF (sec_hf_mirror_dataset) sincronizado por
    # GitHub Actions. True solo donde la SEC sea alcanzable (dev local).
    sec_document_jobs_enabled: bool = False
    # Pipeline de ingesta en dos carriles (MarkItDown rapido / Docling
    # estructura / pypdf clasico; ver app/services/docling_pipeline.py).
    # Activo por defecto SI la dependencia opcional esta instalada; ausente,
    # degrada con warnings ("docling/markitdown no instalado"), nunca rompe.
    # docling_async_only=True restringe el conversor ML pesado (0.3-3 s/pag
    # en CPU) al worker Dramatiq (actor process_document_structured): en la
    # ruta sincrona de FastAPI un PDF con estructura se sirve con el carril
    # rapido y queda marcado para reproceso. Solo desactivar puntualmente en
    # scripts locales, jamas en serving de produccion.
    docling_lane_enabled: bool = True
    docling_async_only: bool = True
    markitdown_enabled: bool = True
    # Ingesta SEC paralela basada en edgartools (edgartools_ingestion_service).
    # Apagada por defecto: via nueva con dependencia de bus-factor 1 y el
    # enchufado al scheduler/Dramatiq es un follow-up cuando BUG-1 cierre.
    # Env: EDGARTOOLS_ENABLED.
    edgartools_enabled: bool = True  # via cableada como fallback de lectura 13F; EDGARTOOLS_ENABLED=false = kill switch
    # Snapshot edgartools (manifest.json con synced_at + companyfacts/ +
    # submissions/ + filings/): mismo patron que sec_snapshot_dir. En
    # produccion (OCI, IP baneada por la SEC con 403 permanente) es la UNICA
    # fuente: funciona sin red una vez construido el snapshot. Env:
    # EDGARTOOLS_SNAPSHOT_DIR.
    edgartools_snapshot_dir: str | None = None
    # Identidad para edgar.set_identity ("Nombre email@dominio"): la SEC exige
    # UA declarado con contacto. Vacio = se deriva de sec_user_agent. Env:
    # EDGARTOOLS_IDENTITY.
    edgartools_identity: str | None = None
    # Tope de peticiones/segundo a la SEC via edgartools (maximo SEC: 10).
    # Env: EDGARTOOLS_REQUESTS_PER_SECOND.
    edgartools_requests_per_second: float = Field(default=8, ge=0.1, le=10)
    # Directorio con snapshots ESEF (manifest.json issuers LEI->{ticker,...},
    # snapshots/<LEI>.json normalizados desde filings.xbrl.org). Mismo motivo
    # que SEC: los datos viajan con la app, nunca se piden en caliente.
    esef_snapshot_dir: str | None = None
    # Web Push (PWA): claves VAPID propias, gratis, sin proveedor de pago.
    # Apagado por defecto. Env: WEB_PUSH_ENABLED, VAPID_PUBLIC_KEY,
    # VAPID_PRIVATE_KEY, VAPID_SUBJECT (mailto: o https:). La clave publica la
    # lee el navegador para suscribirse; la privada firma cada envio.
    web_push_enabled: bool = False
    vapid_public_key: str | None = None
    vapid_private_key: str | None = Field(default=None, repr=False)
    vapid_subject: str | None = None
    web_push_timeout_seconds: float = Field(default=10.0, gt=0, le=60)
    # Seguimiento de errores en produccion, sin dependencias ni proveedor de
    # pago: un DSN con el protocolo de Sentry (GlitchTip autoalojado es gratis
    # y lo habla). Apagado si no hay DSN. Env: ERROR_TRACKING_DSN,
    # ERROR_TRACKING_ENVIRONMENT (por defecto APP_ENV).
    error_tracking_dsn: str | None = Field(default=None, repr=False)
    error_tracking_environment: str | None = None
    telegram_link_secret: str | None = Field(default=None, repr=False)
    telegram_enabled: bool = False
    telegram_bot_token: str | None = Field(default=None, repr=False)
    telegram_chat_id: str | None = None
    telegram_api_base_url: str = "https://api.telegram.org"
    telegram_timeout_seconds: float = Field(default=10.0, gt=0, le=60)
    # Aprobación de tesis por Telegram (human-in-the-loop mínimo viable).
    # Apagado por defecto: sin este flag no se envía nada ni se sondea nada.
    # Env: TELEGRAM_APPROVAL_ENABLED.
    telegram_approval_enabled: bool = False
    # Fichero donde el poller persiste el offset de getUpdates.
    # Env: TELEGRAM_APPROVAL_STATE_PATH.
    telegram_approval_state_path: str = "./storage/telegram_approval_offset"
    # Intervalo del poller entre pasadas getUpdates (solo scripts/poller).
    # Env: TELEGRAM_APPROVAL_POLL_INTERVAL_SECONDS.
    telegram_approval_poll_interval_seconds: int = Field(default=15, ge=5, le=300)
    # Senales insider (Form 4 EDGAR): alerta Telegram 'insider buy' apagada
    # por defecto. Env: INSIDER_ALERTS_ENABLED.
    insider_alerts_enabled: bool = False
    # Correo saliente por SMTP (canal "email" de las alertas). Vacio = sin SMTP:
    # el canal email cae al webhook ALERT_EMAIL_WEBHOOK_URL si existe y si no
    # queda "not_configured". Con Gmail hace falta una contrasena de aplicacion
    # (no la de la cuenta). La contrasena nunca se registra en logs.
    # Env: SMTP_HOST / SMTP_PORT / SMTP_USERNAME / SMTP_PASSWORD / SMTP_FROM /
    # SMTP_STARTTLS / SMTP_SSL / SMTP_TIMEOUT_SECONDS / ALERT_EMAIL_TO.
    smtp_host: str | None = None
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_username: str | None = None
    smtp_password: str | None = Field(default=None, repr=False)
    smtp_from: str | None = None
    smtp_starttls: bool = True
    smtp_ssl: bool = False
    smtp_timeout_seconds: float = Field(default=20.0, gt=0, le=120)
    # Destinatarios separados por comas.
    alert_email_to: str | None = None
    # DCA_EVALUATION_ENABLED: la evaluacion diaria de senales DCA (guarda el
    # nivel 1X-4X de watchlist + cartera). Es independiente de los avisos: con
    # DCA_ALERTS_ENABLED=false se sigue evaluando y solo se callan los avisos.
    dca_evaluation_enabled: bool = True
    # Senales DCA por niveles (1X-4X + recortes) sobre watchlist + cartera.
    # DCA_ALERT_MIN_LEVEL: nivel minimo de compra que avisa (1-4) salvo ajuste
    # por ticker. DCA_ALERT_TRIMS: avisar tambien de las zonas de recorte.
    # DCA_ALERT_CHANNELS: canales base; Telegram se anade solo si el tenant
    # tiene suscripcion "dca_levels" con chat vinculado.
    dca_alerts_enabled: bool = True
    dca_alert_min_level: int = Field(default=2, ge=1, le=4)
    dca_alert_trims: bool = False
    # Cierre mas antiguo (dias naturales) con el que aun se emite una senal DCA.
    dca_max_data_age_days: int = Field(default=14, ge=1, le=90)
    dca_alert_channels: str = "in_app,email"
    # Avisos de proximos resultados (earnings) de watchlist + cartera, estilo
    # Investing: ventanas de 7 dias, 1 dia y el propio dia sobre las fechas ya
    # refrescadas en earnings_dates. EARNINGS_ALERT_CHANNELS: canales base;
    # Telegram/push se anaden solo con la suscripcion "earnings" activa.
    earnings_alerts_enabled: bool = False
    earnings_alert_channels: str = "in_app,email"
    # Langfuse Cloud EU shadow tracing (stage 3): SOLO observabilidad.
    # Apagado por defecto; nunca es fuente de verdad de negocio (eso es
    # Postgres). Sin payloads: solo metadatos de la allowlist. Muestreo del
    # 10% en corridas OK; los fallos se trazan siempre (buffer en memoria).
    # Env: LANGFUSE_ENABLED / LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY /
    # LANGFUSE_HOST / LANGFUSE_SAMPLE_RATE.
    langfuse_enabled: bool = False
    # Generación multidioma (i18n B). Apagado: TODO se genera en español,
    # byte a byte como antes (prompts, validadores de idioma y detail= de
    # HTTPException visibles). Encendido: la cabecera firmada
    # X-GerarAI-Language (es/en) fija el idioma de generación de la petición.
    # Env: I18N_GENERATION_ENABLED.
    i18n_generation_enabled: bool = False

    # Invalidación GLOBAL de la caché de mercado (compartida entre tenants).
    # Las rutas POST /api/cache/invalidate/market-data e /invalidate/all la
    # vacían para TODOS los tenants; sin gate, cualquier identidad firmada
    # podía dejar fría la caché de los demás (re-fetch masivo a yfinance/SEC).
    # Omiso: activo fuera de producción (dev/test), apagado en producción,
    # donde la acción queda como script de ops
    # (scripts/invalidate_market_cache.py). Env: CACHE_GLOBAL_INVALIDATION_ENABLED.
    cache_global_invalidation_enabled: bool | None = None
    langfuse_public_key: str | None = Field(default=None, repr=False)
    langfuse_secret_key: str | None = Field(default=None, repr=False)
    langfuse_host: str = "https://cloud.langfuse.com"
    langfuse_sample_rate: float = Field(default=0.1, ge=0.0, le=1.0)
    fmp_api_key: str | None = None
    fred_api_key: str | None = None
    # Referencia de instrumentos: seed FinanceDatabase + normalizacion OpenFIGI.
    # Sin key por defecto (25 req/min); key gratuita opcional via env.
    # Env: OPENFIGI_API_KEY / OPENFIGI_REQUESTS_PER_MINUTE /
    # OPENFIGI_CACHE_TTL_SECONDS / OPENFIGI_BASE_URL /
    # FINANCEDATABASE_EQUITIES_BASE_URL / INSTRUMENT_SNAPSHOT_DIR.
    openfigi_api_key: str | None = Field(default=None, repr=False)
    openfigi_requests_per_minute: int = Field(default=25, ge=1, le=600)
    openfigi_cache_ttl_seconds: int = Field(default=86400, ge=60)
    openfigi_base_url: str = "https://api.openfigi.com/v3/mapping"
    financedatabase_equities_base_url: str = (
        "https://raw.githubusercontent.com/JerBouma/FinanceDatabase/main/database/equities"
    )
    instrument_snapshot_dir: str = "./data/instruments"
    # Provider Go DEDICADO a las narrativas de tesis (extensa y noticias),
    # por consumidor/endpoint/key/modelo. Disabled (defecto) = comportamiento
    # global previo intacto. Enabled exige endpoint/key/modelo propios
    # validados; config inválida = narrativa omitida (fail-closed), NUNCA el
    # bridge global presentado como Go. Envs: THESIS_GO_ENABLED,
    # THESIS_GO_BASE_URL, THESIS_GO_API_KEY, THESIS_GO_MODEL.
    thesis_go_enabled: bool = False
    #: Fail-closed: los providers Go no envian ninguna peticion sin un guard
    #: de corrida activo (app/llm/run_guard.py). Defecto False = sin cambio.
    llm_run_guard_required: bool = False
    #: Guard por job de tesis (PR3). max_posts=0 => DESACTIVADO (defecto, sin
    #: cambio). Con max_posts>0 el resto de limites/hosts/modelos son
    #: obligatorios (si falta alguno el job falla cerrado antes de la red).
    llm_run_guard_max_posts: int = 0
    llm_run_guard_max_tokens_per_request: int = 0
    llm_run_guard_max_total_output_tokens: int = 0
    llm_run_guard_allowed_hosts: str = ""
    llm_run_guard_allowed_models: str = ""
    #: Ventana del guard: se ancla en el PRIMER init del guard de ese run
    #: (marcador durable en BD), no en created_at. Un run viejo que inicializa
    #: por primera vez con el guard activo recibe ventana nueva desde ese init.
    #: Pasado el deadline, o con contador ausente tras el init, aborta.
    llm_run_guard_window_seconds: int = 7 * 24 * 3600
    thesis_go_base_url: str = "https://opencode.ai/zen/go/v1"
    thesis_go_api_key: str | None = Field(default=None, repr=False)
    thesis_go_model: str = "deepseek-v4.1-flash"
    opencode_go_api_key: str | None = Field(default=None, repr=False)
    # Decision del dueno (2026-10-25): el cerebro es OpenCode Go con el modelo
    # `deepseek-v4.1-flash`, cubierto por su suscripcion ya contratada. El
    # endpoint /zen/go/v1 es el aprobado; el bridge local queda como opcion
    # para free/legacy, no como camino obligatorio.
    opencode_go_base_url: str = "https://opencode.ai/zen/go/v1"
    # Modelo aprobado por el dueno (no es free: lo paga la suscripcion Go).
    # Overridable via OPENCODE_GO_MODEL; en produccion solo se aceptan free
    # verificados o el modelo Go aprobado (ver validate_production_llm_model).
    opencode_go_model: str = "deepseek-v4.1-flash"
    # Fallback automatico interno del adaptador. Vacio por defecto: no hay
    # fallback implicito. En produccion solo se aceptan free verificados o el
    # modelo Go aprobado. Env: OPENCODE_GO_FALLBACK_MODEL.
    opencode_go_fallback_model: str = ""
    # Escotilla explicita y auditada para produccion: permite un modelo no
    # aprobado (p. ej. un piloto). Sin ella, el arranque falla. Nunca se usa
    # para saltarse los guards de coste sin decision del dueno.
    # Env: OPENCODE_GO_ALLOW_UNVERIFIED_MODEL.
    opencode_go_allow_unverified_model: bool = False
    # OpenCode Go exige cabecera x-opencode-session en todas las llamadas
    # (sin ella: MissingSessionID). ID estable por despliegue, mejora el
    # enrutado/cacheo del proveedor. Env: OPENCODE_GO_SESSION.
    opencode_go_session: str = "cavaai-prod"
    # Nivel de razonamiento para los modelos de OpenCode Go que lo soportan.
    # DeepSeek v4.1 Flash acepta high; se envia como `reasoning_effort` en el
    # sobre OpenAI-compatible. Cadena vacia = no enviar el parametro.
    # Env: OPENCODE_GO_REASONING_EFFORT.
    opencode_go_reasoning_effort: str | None = "high"
    # Modelos a los que se aplica reasoning_effort (lista separada por comas).
    # Incluye los free de legacy para que el bridge opcional siga funcionando.
    # Env: OPENCODE_GO_REASONING_EFFORT_MODELS.
    opencode_go_reasoning_effort_models: str = (
        "deepseek-v4.1-flash,deepseek-v4.1-flash-free,space-bunny-free"
    )
    # Nivel de razonamiento SOLO para el chat interactivo (cadena
    # create_chat_llm_provider). Decision 2026-10-25: high para DeepSeek v4.1
    # Flash, alineado con compose y docs. Env:
    # OPENCODE_GO_CHAT_REASONING_EFFORT.
    opencode_go_chat_reasoning_effort: str | None = "high"

    # Effort de las narrativas de tesis. None (por defecto) = la tabla por
    # seccion (tesis_profunda / tesis_noticias). Antes era "none" porque con
    # 4000/1600 max_tokens el razonamiento agotaba el tope; ahora los topes
    # dejan sitio al razonamiento (16000 / 6000). Un valor explicito sigue
    # ganando, para no romper despliegues que ya lo fijan.
    # Env: THESIS_DEEP_NARRATIVE_REASONING_EFFORT / THESIS_NEWS_NARRATIVE_REASONING_EFFORT.
    thesis_deep_narrative_reasoning_effort: str | None = None
    thesis_news_narrative_reasoning_effort: str | None = None
    # Override de la tabla LLM_REASONING_EFFORT_DEFAULTS, JSON por seccion.
    # Env: LLM_REASONING_EFFORT_BY_SECTION='{"chat_consulta":"high"}'.
    llm_reasoning_effort_by_section: Annotated[dict[str, str], NoDecode] = Field(default_factory=dict)

    # Cascada gratuita (LLM_PROVIDER=cascade): Gemini AI Studio -> OpenRouter :free
    # -> OpenCode, solo los que tengan clave. Env: GEMINI_API_KEY / OPENROUTER_API_KEY.
    # Modelos verificados en las paginas publicas del proveedor (2026-10-14):
    # gemini-3.8-flash tiene nivel gratuito (ai.google.dev/gemini-api/docs/pricing);
    # el modelo :free de OpenRouter sale de https://openrouter.ai/api/v1/models
    # (precio 0, admite tools y response_format). El nivel gratuito de Gemini puede
    # usar los datos para mejorar el servicio: no enviar nada que no deba salir.
    groq_api_key: str | None = Field(default=None, repr=False)
    # Respaldos del chat y de los trabajos en segundo plano (Groq, luego
    # Gemini) cuando falla el primario OpenCode Go. Decision del dueno
    # (2026-10-27): TODO el LLM va por su OpenCode Go con DeepSeek V4.1 Flash;
    # los respaldos solo entran DESPUES de que Go falle (error o plazo
    #   agotado), nunca en carrera, y la respuesta lo dice de forma visible.
    #   None ("auto", por defecto) -> activo si hay clave y confirmaciones.
    #   True  -> activo; falla el arranque del proveedor si falta la clave o
    #     una confirmacion de plan gratuito.
    #   False -> apagado del todo.
    # Usa siempre `groq_chat_fallback_active` / `gemini_chat_fallback_active`.
    groq_chat_fallback_enabled: bool | None = None
    groq_free_plan_confirmed: bool = False
    groq_zdr_confirmed: bool = False
    # Respaldo del chat DESPUES de Groq (gemini-3.5-flash-lite, luego gemini-3.8-flash;
    # usa gemini_api_key de mas abajo). Fail-closed: requiere confirmar que la clave
    # es de un proyecto SIN facturacion (tier gratuito).
    gemini_chat_fallback_enabled: bool | None = None
    gemini_free_plan_confirmed: bool = False

    gemini_api_key: str | None = Field(default=None, repr=False)
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai"
    gemini_model: str = "gemini-3.8-flash"
    openrouter_api_key: str | None = Field(default=None, repr=False)
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_model: str = "google/gemma-4-31b-it:free"
    # OpenRouter :free como ultimo respaldo del chat, solo tras fallar Go (y
    # Groq): true/false fuerzan; auto (por defecto) = activo si hay clave.
    # Env: OPENROUTER_CHAT_FALLBACK_ENABLED.
    openrouter_chat_fallback_enabled: bool | None = None
    # Por miembro de la cascada: poco margen para que el siguiente tenga tiempo.
    llm_cascade_member_timeout_seconds: float = Field(default=20.0, gt=0)
    llm_cascade_member_total_timeout_seconds: float = Field(default=25.0, gt=0)
    llm_cascade_member_max_retries: int = Field(default=1, ge=0, le=3)
    # Tope TOTAL de toda la cascada (todos los miembros).
    llm_cascade_total_timeout_seconds: float = Field(default=60.0, gt=0)

    # TypeSafe Jev (capa de micro-decisiones, SystemOne API). Env: TYPESAFE_API_KEY.
    # Factura por uso ($0.042/MTok in); sin key el cliente no se construye.
    typesafe_api_key: str | None = None
    typesafe_base_url: str = "https://api.typesafe.ai"
    typesafe_model: str = "jev-latest"
    llm_enabled: bool = True
    # Clave del cifrado en reposo de las API keys LLM por tenant. En
    # produccion es obligatoria (>=32 bytes); en local/test se deriva de
    # RESEARCH_AUTH_SECRET para no exigir otro secreto al desarrollador.
    llm_settings_encryption_key: str | None = Field(default=None, repr=False)
    # Rotacion: claves ANTERIORES, separadas por comas, que solo se usan para
    # descifrar lo ya guardado. Sin esto, cambiar la clave dejaba la IA de
    # cada tenant desactivada («configuracion invalida») sin aviso.
    llm_settings_encryption_key_previous: str | None = Field(default=None, repr=False)
    # GerarAI intentionally uses one provider for every task.
    llm_provider: str = "opencode-go"
    # Llamadas largas (extraccion de documentos/principios, tesis, KPIs): el
    # bridge OpenCode con reasoning=max tarda ~26 s o mas por lote; con 30 s
    # se cortaba ~30 % de las peticiones y el bridge escribia sobre un socket
    # cerrado (BrokenPipe). 120 s por intento con 1 reintento.
    llm_timeout_seconds: float = Field(default=120.0, gt=0)
    llm_max_retries: int = Field(default=1, ge=0, le=5)
    # Tope TOTAL por llamada (reintentos incluidos): 2 intentos de 120 s mas
    # el backoff. Ojo con el pool de BD: una llamada request-scope que retenga
    # sesion durante el LLM puede agotarlo, asi que el chat interactivo NO
    # usa este tope sino chat_total_timeout_seconds (cadena corta con
    # respaldos); el resto de llamadas largas vive en workers/segundo plano.
    llm_total_timeout_seconds: float = Field(default=250.0, gt=0)
    # Presupuesto total del chat interactivo (carrera primario/respaldos en
    # ChatFallbackProvider). Fuente de verdad unica: compose y docs pasan o
    # documentan este mismo 45 s (antes config decia 20 y docs 45).
    chat_total_timeout_seconds: float = Field(default=45.0, gt=0)
    # SIN USO desde 2026-10-27: ya no hay carrera Go/respaldo. Go tiene 2/3 del
    # presupuesto del chat y el respaldo arranca solo si Go falla o lo agota.
    # Se conserva para no romper entornos que aun fijan la variable.
    chat_go_head_start_seconds: float = Field(default=2.0, gt=0)
    # Suelo de max_tokens SOLO para el primario Go del chat. Medicion 25-oct con la
    # peticion real (JSON estricto): 1800 truncaba 1-2 de 3; 2600 dio 2/2 completas
    # (muestra pequena, sintetica). Con el flag apagado no se usa.
    chat_go_min_output_tokens: int = Field(default=2600, ge=1024, le=8000)
    # ENCENDIDO por decision explicita del dueno (2026-10-25): el primario del
    # chat es la suscripcion OpenCode Go ya contratada (modelo
    # `deepseek-v4.1-flash`, endpoint /zen/go/v1), con Groq/Gemini intactos y
    # apagados. El interruptor sigue existiendo para volver a la ruta free
    # verificada (bridge opcional) sin tocar codigo. Env:
    # CHAT_GO_SUBSCRIPTION_ENABLED.
    chat_go_subscription_enabled: bool = True
    chat_go_subscription_base_url: str = "https://opencode.ai/zen/go/v1"
    # Respaldo por la capa FREE de OpenCode Zen (/zen/v1), entre Go y Gemini,
    # para los usuarios de plataforma: misma clave Go de GerarAI, modelo free
    # (deepseek), gasto 0. La cuota free no tiene API publica: el breaker de
    # cuota respeta el Retry-After del proveedor y el panel de Ajustes marca
    # sus cifras como estimadas. true/false fuerzan; auto (por defecto) =
    # activo si el primario Go esta activo y hay clave Go.
    # Env: OPENCODE_FREE_CHAT_FALLBACK_ENABLED.
    opencode_free_chat_fallback_enabled: bool | None = None
    opencode_free_base_url: str = "https://opencode.ai/zen/v1"
    opencode_free_model: str = "deepseek-v4.1-flash-free"
    # Modelos con razonamiento oculto: gastan tokens de salida pensando y con un
    # max_tokens bajo devuelven "no assistant message". Suelo de salida para ellos.
    llm_hidden_reasoning_models: str = "longcat-2.5-preview-free"
    llm_hidden_reasoning_min_tokens: int = Field(default=1024, ge=1, le=100_000)
    llm_model_overrides: Annotated[dict[str, str], NoDecode] = Field(default_factory=dict)
    llm_max_output_tokens: int = Field(default=16_000, ge=1, le=1_000_000)
    llm_daily_cap_eur: float = Field(default=1.50, ge=0)
    llm_monthly_cap_eur: float = Field(default=40.00, ge=0)
    # Second-order free-model request quota, independent of the shared EUR ledger.
    second_order_llm_calls_per_minute: int = Field(default=4, ge=0, le=100)
    second_order_llm_calls_per_day: int = Field(default=100, ge=0, le=10000)
    # ASTS catalog LLM quota, independent of the second-order and EUR ledgers.
    # Lower defaults: the catalog refreshes a few times a day at most.
    asts_llm_calls_per_minute: int = Field(default=2, ge=0, le=100)
    asts_llm_calls_per_day: int = Field(default=30, ge=0, le=10000)

    @property
    def cache_global_invalidation_allowed(self) -> bool:
        """Resuelve el gate de invalidación global de caché.

        La variable explícita manda; omisa, solo se permite fuera de
        producción.
        """
        if self.cache_global_invalidation_enabled is not None:
            return self.cache_global_invalidation_enabled
        return not self.is_production

    @property
    def is_production(self) -> bool:
        # Denylist, no allowlist: cualquier APP_ENV que no sea un entorno local
        # conocido se trata como produccion. Con una allowlist, 'staging',
        # 'stage', 'preprod', 'prod-eu' o un typo (el default es 'local')
        # degradaban en silencio TODAS las decisiones de seguridad: firma
        # ligada al request, nonce en Redis, rate limit, MinIO.
        return self.app_env.strip().lower() not in _NON_PRODUCTION_ENVS

    @property
    def is_local_environment(self) -> bool:
        """Complemento de is_production.

        Unica prediccion de "entorno local" del backend. El rate limiter la
        usaba con tres allowlists distintas y contradictorias, lo que dejaba
        'dev' y 'ci' sin limite efectivo.
        """
        return not self.is_production

    @field_validator(
        "ibkr_flex_tenant_id", "ibkr_flex_account_id", "ibkr_flex_complete_query_id",
        "smtp_host", "smtp_username", "smtp_password", "smtp_from", "alert_email_to",
        mode="before",
    )
    @classmethod
    def _blank_flex_tenant_is_none(cls, value):
        # docker-compose pasa IBKR_FLEX_TENANT_ID="" cuando no esta definido.
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("llm_reasoning_effort_by_section", mode="before")
    @classmethod
    def _parse_reasoning_effort_by_section(cls, value):
        """JSON por seccion; vacio = sin overrides. Falla al arrancar si no es valido."""
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return {}
            try:
                value = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    "LLM_REASONING_EFFORT_BY_SECTION debe ser un JSON, "
                    'p. ej. {"tesis_profunda": "high"}'
                ) from exc
        if not isinstance(value, dict):
            raise ValueError("LLM_REASONING_EFFORT_BY_SECTION debe ser un objeto JSON")
        cleaned: dict[str, str] = {}
        for section, effort in value.items():
            if section not in LLM_REASONING_EFFORT_DEFAULTS:
                raise ValueError(
                    f"Seccion de razonamiento desconocida: {section!r}. "
                    f"Validas: {', '.join(sorted(LLM_REASONING_EFFORT_DEFAULTS))}"
                )
            normalized = str(effort or "").strip().lower()
            if normalized not in LLM_REASONING_EFFORT_VALUES:
                raise ValueError(
                    f"Esfuerzo no valido para {section!r}: {effort!r}. "
                    "Usa low, high, max o none"
                )
            cleaned[section] = normalized
        return cleaned

    def reasoning_effort_for(self, section: str) -> str | None:
        """Esfuerzo de razonamiento de una seccion: override por env o la tabla.

        Devuelve None cuando no hay que enviar el parametro.
        """
        if section not in LLM_REASONING_EFFORT_DEFAULTS:
            raise KeyError(f"Seccion de razonamiento desconocida: {section}")
        value = self.llm_reasoning_effort_by_section.get(
            section, LLM_REASONING_EFFORT_DEFAULTS[section]
        )
        return value or None

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _parse_cors_origins(cls, value):
        """Acepta `a,b` (formato de las plantillas) y tambien una lista JSON."""
        if isinstance(value, str):
            text = value.strip()
            if text.startswith("["):
                return json.loads(text)
            return [origin.strip() for origin in text.split(",") if origin.strip()]
        return value

    @field_validator("llm_model_overrides", mode="before")
    @classmethod
    def _empty_overrides_is_empty_dict(cls, value):
        """Una variable vacia (LLM_MODEL_OVERRIDES=) no puede tumbar el arranque."""
        if isinstance(value, str):
            text = value.strip()
            return json.loads(text) if text else {}
        return value

    @model_validator(mode="after")
    def validate_production_security(self) -> Self:
        if not self.is_production:
            return self
        if not self.research_auth_required:
            # Desactivar la auth firmada no solo abre la API: deja la sesion
            # sin tenant_id, y con el tenant ausente los guards de
            # aislamiento (with_loader_criteria / _scope_tenant_dml) no inyectan
            # filtro alguno. Es decir, desactiva multitenant completo.
            raise ValueError(
                "RESEARCH_AUTH_REQUIRED cannot be disabled in production: it would "
                "also disable tenant isolation"
            )
        if any(origin.strip() == "*" for origin in self.cors_origins):
            raise ValueError("CORS_ORIGINS must not contain '*' (CORS is mounted with allow_credentials)")
        if not self.research_auth_secret:
            raise ValueError("RESEARCH_AUTH_SECRET is required in production")
        _assert_not_placeholder(self.research_auth_secret, label="RESEARCH_AUTH_SECRET")
        if self.document_storage_backend != "minio":
            raise ValueError("MinIO is required for production document originals")
        if self.minio_secret_key.lower() in _WEAK_MINIO_SECRET_KEYS:
            raise ValueError("MINIO_SECRET_KEY must not use a development default in production")
        if self.minio_access_key.lower() in _WEAK_MINIO_ACCESS_KEYS:
            raise ValueError("MINIO_ACCESS_KEY must not use a development default in production")
        _assert_not_placeholder(self.minio_secret_key, label="MINIO_SECRET_KEY")
        _assert_not_placeholder(self.minio_access_key, label="MINIO_ACCESS_KEY")
        # "postgresql+psycopg" (la URL real de la VM) tambien es postgres: antes
        # el sufijo del driver hacia saltarse la comprobacion de credenciales.
        database_scheme = (self.database_url.split(":", 1) or [""])[0].lower().split("+", 1)[0]
        if database_scheme in {"postgres", "postgresql"}:
            _assert_strong_credentials(self.database_url, label="DATABASE_URL")
        if self.mongodb_uri:
            _assert_strong_credentials(self.mongodb_uri, label="MONGODB_URI")
        # La SEC bloquea UAs sin contacto real (403). El default .local es solo
        # fallback local; en produccion el operador debe declarar un contacto.
        if "example.com" in self.sec_user_agent.lower() or "tu-" in self.sec_user_agent.lower():
            raise ValueError(
                "SEC_USER_AGENT still contains a placeholder; declare a real "
                "contact (e.g. 'GerarAI research ops@tudominio-real.es')"
            )
        for field_name, value in (
            ("TELEGRAM_BOT_TOKEN", self.telegram_bot_token),
            ("TELEGRAM_LINK_SECRET", self.telegram_link_secret),
            ("VAPID_PRIVATE_KEY", self.vapid_private_key),
            ("SMTP_PASSWORD", self.smtp_password),
        ):
            if value:
                _assert_not_placeholder(value, label=field_name)
        # Ultimo, para no tapar los mensajes de las demas garantias.
        if database_scheme.startswith("sqlite"):
            raise ValueError("SQLite is not allowed as DATABASE_URL in production")
        return self

    @field_validator(
        "groq_chat_fallback_enabled",
        "gemini_chat_fallback_enabled",
        "openrouter_chat_fallback_enabled",
        "opencode_free_chat_fallback_enabled",
        mode="before",
    )
    @classmethod
    def parse_fallback_flag(cls, value: object) -> object:
        """``auto`` o vacio (``${VAR:-auto}`` en compose) -> None (modo auto)."""
        if value is None:
            return None
        if isinstance(value, str) and value.strip().lower() in {"", "auto"}:
            return None
        return value

    def _primary_is_opencode_go(self) -> bool:
        requested = (self.llm_provider or "").strip().lower()
        return requested in {"auto", "opencode", "opencode_go", "opencode-go"}

    @property
    def groq_chat_fallback_active(self) -> bool:
        """Groq como respaldo SOLO cuando OpenCode Go falla (nunca en carrera).

        Decision del dueno (2026-10-27): Go es siempre el primario. ``true`` =
        respaldo activo, ``false`` = apagado del todo, ``auto`` (por defecto) =
        activo si hay clave + plan gratuito + ZDR confirmados. Entra solo
        despues de un error o del plazo agotado de Go, y la respuesta lo dice
        de forma visible («Respondido por respaldo (Groq) porque OpenCode Go
        fallo: ...»).
        """
        if self.groq_chat_fallback_enabled is not None:
            return self.groq_chat_fallback_enabled
        return bool(
            self._primary_is_opencode_go()
            and (self.groq_api_key or "").strip()
            and self.groq_free_plan_confirmed
            and self.groq_zdr_confirmed
        )

    @property
    def gemini_chat_fallback_active(self) -> bool:
        """Gemini como respaldo SOLO cuando Go falla: true/false o auto con clave + plan gratis."""
        if self.gemini_chat_fallback_enabled is not None:
            return self.gemini_chat_fallback_enabled
        return bool(
            self._primary_is_opencode_go()
            and (self.gemini_api_key or "").strip()
            and self.gemini_free_plan_confirmed
        )

    @property
    def openrouter_chat_fallback_active(self) -> bool:
        """OpenRouter :free, ultimo respaldo del chat: true/false o auto con clave."""
        if self.openrouter_chat_fallback_enabled is not None:
            return self.openrouter_chat_fallback_enabled
        return bool((self.openrouter_api_key or "").strip())

    @property
    def opencode_free_chat_fallback_active(self) -> bool:
        """OpenCode free (Zen /zen/v1) tras Go y antes de Gemini.

        ``true`` = activo, ``false`` = apagado, ``auto`` (por defecto) =
        activo cuando el primario es OpenCode Go y hay clave Go de la
        plataforma. Nunca usa la clave de un tenant: los BYOK salen antes
        por su propio camino fail-closed.
        """
        if self.opencode_free_chat_fallback_enabled is not None:
            return self.opencode_free_chat_fallback_enabled
        return bool(
            self._primary_is_opencode_go()
            and self.chat_go_subscription_enabled
            and (self.opencode_go_api_key or "").strip()
        )

    @model_validator(mode="after")
    def validate_production_llm_model(self) -> Self:
        """Falla el arranque si produccion usa un modelo no aprobado.

        Aprobados: los free verificados reales o el modelo de la suscripcion
        OpenCode Go del dueno (``deepseek-v4.1-flash``), y solo este ultimo si
        la suscripcion esta confirmada. Se revisan el modelo principal, el
        fallback, cada valor de ``LLM_MODEL_OVERRIDES`` y los miembros de la
        cascada. Un override silencioso a un modelo de pago desconocido rompe
        el arranque; la unica salida es el flag explicito
        ``OPENCODE_GO_ALLOW_UNVERIFIED_MODEL=true`` (nunca exime de las
        confirmaciones de plan gratuito de Gemini/OpenRouter).
        """
        if not self.is_production or not self.llm_enabled:
            return self
        requested = (self.llm_provider or "").strip().lower()
        if requested in {"auto", "opencode", "opencode_go"}:
            requested = "opencode-go"
        if requested not in {"opencode-go", "cascade"}:
            return self
        # Import perezoso: app.llm.__init__ importa factory -> config, y un
        # import de nivel de modulo crearia un ciclo.
        from app.llm.model_aliases import (
            GO_SUBSCRIPTION_MODELS,
            VERIFIED_FREE_MODELS,
            is_owner_approved_model,
        )

        def _approved(model: str) -> bool:
            return is_owner_approved_model(model.strip(), self)

        for key, value in self.llm_model_overrides.items():
            if not _approved(str(value or "")):
                raise ValueError(
                    "LLM_MODEL_OVERRIDES is not an owner-approved model map in "
                    f"production: {key!r} -> {value!r}. Use a verified free model "
                    f"({', '.join(sorted(VERIFIED_FREE_MODELS))}) or the Go subscription "
                    f"model ({', '.join(sorted(GO_SUBSCRIPTION_MODELS))}); set "
                    "OPENCODE_GO_ALLOW_UNVERIFIED_MODEL=true only for an audited pilot."
                )

        if requested == "cascade":
            if not any(
                (value or "").strip()
                for value in (
                    self.gemini_api_key,
                    self.openrouter_api_key,
                    self.opencode_go_api_key,
                )
            ):
                raise ValueError(
                    "LLM_PROVIDER=cascade requires at least one provider key in production"
                )
            if (self.gemini_api_key or "").strip() and not self.gemini_free_plan_confirmed:
                raise ValueError(
                    "LLM_PROVIDER=cascade requires GEMINI_FREE_PLAN_CONFIRMED=true "
                    "when GEMINI_API_KEY is set"
                )
            if (self.openrouter_api_key or "").strip() and not (
                self.openrouter_model.strip().endswith(":free")
            ):
                raise ValueError(
                    "LLM_PROVIDER=cascade requires an OpenRouter :free model in "
                    f"production, got {self.openrouter_model!r}"
                )
            if (self.opencode_go_api_key or "").strip():
                if not _approved(self.opencode_go_model):
                    raise ValueError(
                        "LLM_PROVIDER=cascade requires an owner-approved OpenCode Go "
                        f"model in production, got {self.opencode_go_model!r}"
                    )
                fallback = self.opencode_go_fallback_model.strip()
                if fallback and not _approved(fallback):
                    raise ValueError(
                        "LLM_PROVIDER=cascade requires an owner-approved "
                        f"OPENCODE_GO_FALLBACK_MODEL in production, got {fallback!r}"
                    )
            return self

        if not _approved(self.opencode_go_model):
            raise ValueError(
                "OPENCODE_GO_MODEL is not an owner-approved model in production: "
                f"{self.opencode_go_model!r}. Use a verified free model "
                f"({', '.join(sorted(VERIFIED_FREE_MODELS))}) or the Go subscription "
                f"model ({', '.join(sorted(GO_SUBSCRIPTION_MODELS))}); set "
                "OPENCODE_GO_ALLOW_UNVERIFIED_MODEL=true only for an audited pilot."
            )
        fallback = self.opencode_go_fallback_model.strip()
        if fallback and not _approved(fallback):
            raise ValueError(
                "OPENCODE_GO_FALLBACK_MODEL is not an owner-approved model in "
                f"production: {fallback!r}. Leave it empty or use an approved model."
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


# Los logs no deben contener claves de proveedores (query strings, cabeceras).
from app.core import log_redaction  # noqa: E402

log_redaction.install()
