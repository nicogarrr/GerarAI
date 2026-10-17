import json
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


class Settings(BaseSettings):
    # extra=ignore a propósito: .env comparte claves de frontend
    # (BETTER_AUTH_*, TWELVE_DATA_*, etc.) que el backend no modela.
    # Los typos de claves backend se cubren con tests de contrato
    # (test_settings_hermeticity) en vez de forbid global.
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "local"
    app_name: str = "CavaAI Research Engine"
    api_prefix: str = "/api"
    cors_origins: list[str] = Field(
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
    market_price_max_age_days: int = Field(default=3, ge=0, le=30)

    database_url: str = "sqlite:///./portfolio_research_os.db"
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
    knowledge_rag_child_overlap_tokens: int = Field(default=30, ge=0, le=100)
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
    # SEC fair-access: exige UA declarado con contacto; bloquea placeholders
    # tipo example.com con 403. Este valor verificado 200 desde prod (25/9).
    # OJO: este default es un fallback LOCAL no contactable (el dominio .local
    # no existe). En produccion manda SEC_USER_AGENT del .env con un contacto
    # real; la SEC puede bloquear UAs sin contacto verdadero.
    sec_user_agent: str = "CavaAI research contact@cavaai.local"
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
    edgartools_enabled: bool = False
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
    # Langfuse Cloud EU shadow tracing (stage 3): SOLO observabilidad.
    # Apagado por defecto; nunca es fuente de verdad de negocio (eso es
    # Postgres). Sin payloads: solo metadatos de la allowlist. Muestreo del
    # 10% en corridas OK; los fallos se trazan siempre (buffer en memoria).
    # Env: LANGFUSE_ENABLED / LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY /
    # LANGFUSE_HOST / LANGFUSE_SAMPLE_RATE.
    langfuse_enabled: bool = False
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
    opencode_go_api_key: str | None = Field(default=None, repr=False)
    opencode_go_base_url: str = "https://opencode.ai/zen/v1"
    # Default cheap-but-good model. Overridable WITHOUT code change via env
    # OPENCODE_GO_MODEL (e.g. OPENCODE_GO_MODEL=qwen3.7-plus). Ver también
    # default_model_from_env() en app/llm/model_aliases.py.
    opencode_go_model: str = "deepseek-v4.1-flash-free"
    # Fallback automatico: si el modelo resuelto falla (cualquier error de
    # capa LLM tras sus reintentos internos), la llamada se reintenta UNA
    # vez con este modelo antes de propagar el error. Cadena vacia = sin
    # fallback. Env: OPENCODE_GO_FALLBACK_MODEL.
    # 2026-10-16: TODOS los free de Zen (space-bunny incluido) devuelven 403
    # FreeTierError por API directa; prod usa el puente local
    # (data-engine/bridge/opencode_bridge.py -> serve opencode enjaulado),
    # con deepseek-v4.1-flash-free principal y space-bunny-free de respaldo
    # (verificado con generacion real en la VM ese mismo dia).
    opencode_go_fallback_model: str = ""
    # OpenCode Go exige cabecera x-opencode-session en todas las llamadas
    # (sin ella: MissingSessionID). ID estable por despliegue, mejora el
    # enrutado/cacheo del proveedor. Env: OPENCODE_GO_SESSION.
    opencode_go_session: str = "cavaai-prod"
    # Nivel de razonamiento para los modelos de OpenCode Go que lo soportan.
    # space-bunny-free acepta effort low|medium|high|xhigh|max (catalogo
    # models.dev, verificado 2026-09-30); se envia como `reasoning_effort`
    # en el sobre OpenAI-compatible de Zen. Cadena vacia = no enviar el
    # parametro. Env: OPENCODE_GO_REASONING_EFFORT.
    opencode_go_reasoning_effort: str | None = "max"
    # Modelos a los que se aplica reasoning_effort (lista separada por
    # comas). El fallback muse-spark-1.3-contributor-free SI es modelo de
    # razonamiento, pero su catalogo llega solo hasta xhigh (sin max):
    # la lista por defecto lo excluye para que el respaldo nunca reciba
    # un nivel que rechazaria. Env: OPENCODE_GO_REASONING_EFFORT_MODELS.
    opencode_go_reasoning_effort_models: str = "space-bunny-free,deepseek-v4.1-flash-free"

    # Cascada gratuita (LLM_PROVIDER=cascade): Gemini AI Studio -> OpenRouter :free
    # -> OpenCode, solo los que tengan clave. Env: GEMINI_API_KEY / OPENROUTER_API_KEY.
    # Modelos verificados en las paginas publicas del proveedor (2026-10-14):
    # gemini-3.8-flash tiene nivel gratuito (ai.google.dev/gemini-api/docs/pricing);
    # el modelo :free de OpenRouter sale de https://openrouter.ai/api/v1/models
    # (precio 0, admite tools y response_format). El nivel gratuito de Gemini puede
    # usar los datos para mejorar el servicio: no enviar nada que no deba salir.
    groq_api_key: str | None = Field(default=None, repr=False)
    groq_chat_fallback_enabled: bool = False
    groq_free_plan_confirmed: bool = False
    groq_zdr_confirmed: bool = False
    # Respaldo del chat DESPUES de Groq (gemini-3.5-flash-lite, luego gemini-3.8-flash;
    # usa gemini_api_key de mas abajo). Fail-closed: requiere confirmar que la clave
    # es de un proyecto SIN facturacion (tier gratuito).
    gemini_chat_fallback_enabled: bool = False
    gemini_free_plan_confirmed: bool = False

    gemini_api_key: str | None = Field(default=None, repr=False)
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai"
    gemini_model: str = "gemini-3.8-flash"
    openrouter_api_key: str | None = Field(default=None, repr=False)
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_model: str = "google/gemma-4-31b-it:free"
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
    typesafe_fallback: str = Field(default="instructor", pattern="^(instructor|off)$")
    llm_enabled: bool = True
    # CavaAI intentionally uses one provider for every task.
    llm_provider: str = "opencode-go"
    llm_timeout_seconds: float = Field(default=30.0, gt=0)
    llm_max_retries: int = Field(default=2, ge=0, le=5)
    # Tope TOTAL por llamada (reintentos incluidos). Sin tope, 3 intentos de 30 s
    # retenian la sesion de BD del llamador ~90 s y agotaban el pool (15).
    llm_total_timeout_seconds: float = Field(default=45.0, gt=0)
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
    # Entry-price explanation LLM quota, independent of the other LLM ledgers.
    entry_price_llm_calls_per_minute: int = Field(default=2, ge=0, le=100)
    entry_price_llm_calls_per_day: int = Field(default=20, ge=0, le=10000)

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
        "ibkr_flex_tenant_id", "ibkr_flex_account_id", "ibkr_flex_complete_query_id", mode="before"
    )
    @classmethod
    def _blank_flex_tenant_is_none(cls, value):
        # docker-compose pasa IBKR_FLEX_TENANT_ID="" cuando no esta definido.
        if isinstance(value, str) and not value.strip():
            return None
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
        if self.document_storage_backend != "minio":
            raise ValueError("MinIO is required for production document originals")
        if self.minio_secret_key.lower() in _WEAK_MINIO_SECRET_KEYS:
            raise ValueError("MINIO_SECRET_KEY must not use a development default in production")
        if self.minio_access_key.lower() in _WEAK_MINIO_ACCESS_KEYS:
            raise ValueError("MINIO_ACCESS_KEY must not use a development default in production")
        database_scheme = (self.database_url.split(":", 1) or [""])[0].lower()
        if database_scheme in {"postgres", "postgresql"}:
            _assert_strong_credentials(self.database_url, label="DATABASE_URL")
        if self.mongodb_uri:
            _assert_strong_credentials(self.mongodb_uri, label="MONGODB_URI")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
