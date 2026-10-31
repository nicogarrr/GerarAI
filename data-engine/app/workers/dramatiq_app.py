from __future__ import annotations

import hashlib
import logging
import re
import threading
import time
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
from urllib.parse import urlparse

import dramatiq

from app.core.config import get_settings
from app.core.errors import redact_secrets
from app.workers.bounded_broker import (
    DEDUP_ENQUEUE_TTL_SECONDS,
    BoundedRedisBroker,
    DedupEnqueueMiddleware,
    QueueCapacityError,
    max_pending,
)
from app.workers.task_trace import TaskTraceMiddleware
from app.workers.tenant_llm_middleware import TenantLLMSettingsMiddleware

logger = logging.getLogger(__name__)

settings = get_settings()
broker = BoundedRedisBroker(url=settings.redis_url)
broker.add_middleware(DedupEnqueueMiddleware())
broker.add_middleware(TaskTraceMiddleware())
broker.add_middleware(TenantLLMSettingsMiddleware())
dramatiq.set_broker(broker)


def _failure(actor: str, exc: Exception, **context: Any) -> dict[str, Any]:
    return {
        "status": "error",
        "actor": actor,
        "error": {
            "type": type(exc).__name__,
            "message": str(exc),
            "context": context,
        },
    }


def _is_transient(exc: Exception) -> bool:
    """True when the failure is worth retrying via Dramatiq.

    Transient: connection/timeout problems against Postgres, Redis or
    upstream HTTP APIs, and retryable HTTP statuses (429, 5xx).
    Permanent: validation, not-found, bad payloads — retrying those would
    just burn the retry budget and delay the failure signal.
    """
    import httpx
    import redis.exceptions as redis_exc
    from sqlalchemy import exc as sa_exc

    from app.llm.errors import ProviderHTTPError, ProviderTransportError

    # Errores de la cadena LLM: el transporte (timeout, corte) siempre es
    # transitorio — los proveedores gratuitos tienen ventanas de saturacion —
    # y el HTTP solo cuando es 429/5xx (un 4xx de auth o cuota no mejora
    # reintentando). Sin esto, un solo timeout dejaba la extraccion de
    # principios «fallida» para siempre con max_retries=2 sin usar.
    if isinstance(exc, ProviderTransportError):
        return True
    if isinstance(exc, ProviderHTTPError):
        return exc.status_code == 429 or exc.status_code >= 500

    transient_types = (
        ConnectionError,
        TimeoutError,
        sa_exc.OperationalError,
        sa_exc.TimeoutError,
        redis_exc.RedisError,
        httpx.TimeoutException,
        httpx.TransportError,
    )
    if isinstance(exc, transient_types):
        return True
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    if not isinstance(status, int):
        # Los connectors envuelven el error de httpx en un RuntimeError con el
        # status dentro del mensaje ("SEC EDGAR request failed (503 ...)",
        # "SEC fetch failed: <httpx error>"), asi que la comprobacion por
        # atributo nunca veía el 429 ni el 5xx y clasificaba como permanente
        # justo lo que Dramatiq deberia reintentar. max_retries quedaba muerto
        # para los unicos fallos para los que existe.
        status = _status_from_message(str(exc))
    if status == 403 and _is_sec_failure(exc):
        # F359: 403 de la SEC evidencia bloqueo de IP (OCI): permanente, sin
        # reintento - reintentar enveneno la cola default (5276 mensajes).
        return False
    if status == 429 and _is_sec_failure(exc):
        # F359: 429 de la SEC es rate limit y PUEDE ser temporal (Retry-After;
        # el backoff del actor ya espacia los reintentos). Se reintenta de
        # forma acotada hasta que salta el circuit breaker por origen.
        # Degradacion documentada: con la IP de OCI bloqueada, la ingesta SEC
        # pasa a fallo permanente tras la racha en vez de reintentar en bucle
        # eterno, y se auto-recupera tras el cooldown si la SEC levanta el
        # bloqueo.
        return _sec_rate_limit_allows_retry()
    return status is not None and (status == 429 or status >= 500)


# Circuit breaker por origen para el 429 de la SEC (F359): una racha de
# _SEC_429_STREAK_LIMIT 429s dentro de _SEC_429_WINDOW_S abre el breaker
# durante _SEC_429_COOLDOWN_S; abierto, los 429 SEC clasifican permanentes.
_SEC_429_WINDOW_S = 600.0
_SEC_429_STREAK_LIMIT = 5
_SEC_429_COOLDOWN_S = 3600.0
# Estado del breaker en Redis (no en memoria del proceso): el contador es
# atomico (INCR) y lo comparten TODOS los procesos que clasifican fallos SEC
# (worker, worker-thesis, worker-kpis, backend), asi que "por origen" es un
# freno global y no por proceso. Carrera benigna documentada: dos hilos pueden
# cruzar el umbral a la vez; ambos hacen SET de la misma clave de apertura
# (idempotente) y como mucho pasa un reintento extra, acotado por max_retries.
_SEC_BREAKER_STREAK_KEY = "sec_breaker:429_streak"
_SEC_BREAKER_OPEN_KEY = "sec_breaker:open"


def _sec_rate_limit_allows_retry(client=None) -> bool:
    """429 SEC acotado: reintenta salvo breaker abierto o racha que lo abre.

    Si Redis no responde se fail-open (transitorio): el broker de dramatiq es
    el propio Redis, asi que con Redis caido no se estan consumiendo mensajes
    de todas formas, y el reintento queda acotado por max_retries del actor.
    """
    try:
        r = client if client is not None else _redis_client()
        if r is None:
            return True
        if r.get(_SEC_BREAKER_OPEN_KEY):
            return False
        streak = r.incr(_SEC_BREAKER_STREAK_KEY)
        if streak == 1:
            r.expire(_SEC_BREAKER_STREAK_KEY, int(_SEC_429_WINDOW_S))
        if streak >= _SEC_429_STREAK_LIMIT:
            r.set(_SEC_BREAKER_OPEN_KEY, "1", ex=int(_SEC_429_COOLDOWN_S))
            r.delete(_SEC_BREAKER_STREAK_KEY)
            return False
        return True
    except Exception:
        return True


_STATUS_IN_TEXT = re.compile(r"\b(4\d\d|5\d\d)\b")
_FOR_URL = re.compile(r"for url '(https?://[^']+)'")


def _is_sec_failure(exc: BaseException) -> bool:
    """True si el fallo se atribuye estructuralmente a un host real de sec.gov.

    Atribucion, en orden: (1) errores httpx: host de la request real
    (exc.request.url o exc.response.request.url), sin parsear texto;
    (2) cadena __cause__/__context__ (los connectors envuelven con
    `raise RuntimeError(...) from e`); (3) fallback: el formato propio de
    httpx "for url '<url>'" dentro del mensaje. Un error de otro proveedor
    que solo mencione una URL de la SEC en texto libre NO alimenta el
    breaker, y un lookalike (sec.gov.evil.com, notsec.gov) tampoco.
    """
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        request = getattr(current, "request", None)
        if request is None:
            response = getattr(current, "response", None)
            request = getattr(response, "request", None) if response is not None else None
        if request is not None:
            try:
                host = request.url.host or ""
            except Exception:
                host = ""
            return host == "sec.gov" or host.endswith(".sec.gov")
        match = _FOR_URL.search(str(current))
        if match:
            host = urlparse(match.group(1)).hostname or ""
            return host == "sec.gov" or host.endswith(".sec.gov")
        current = current.__cause__ or current.__context__
    return False


def _status_from_message(text: str) -> int | None:
    """Extrae un status HTTP del texto de una excepcion envuelta.

    Cubre las tres formas en que los connectors dejan el codigo: entre
    parentesis ("request failed (503 Service Unavailable)"), detras de
    "status" ("status 502") y entrecomillado como lo formatea httpx
    ("Client error '429 Too Many Requests'"). No acepta cualquier numero:
    un anio, un id o un importe no son un codigo de estado.
    """
    patterns = (
        # "(503 Service Unavailable)" y "(500)" al final de la cadena
        r"\((\d{3})(?:\s|\)|$)",
        r"status(?:_code)?[= ]\s*(\d{3})\b",
        # httpx formatea "Client error '429 Too Many Requests' for url"
        r"['\"](\d{3})\s+[A-Z]",
        r"\bHTTP/[\d.]+\s+(\d{3})\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            candidate = int(match.group(1))
            if 400 <= candidate <= 599:
                return candidate
    return None


# Suelo de espera cuando GDELT no da ventana (0 o ausente): sin el, un
# Retry(delay=0) eludiria el min_backoff del actor y el lote podria buclear
# contra el 429. La regla es NUNCA reintentar antes de la ventana real.
GDELT_RETRY_FLOOR_SECONDS = 60.0


def _raise_gdelt_retry(exc: Exception) -> None:
    """Reencola el lote GDELT ni un segundo ANTES de la ventana del servidor.

    La ventana real NO se trunca: si GDELT pide 3600s, el lote espera 3600s
    en la cola de diferidos (truncar a un cap reintentaria antes de tiempo y
    quemaria cuota contra la ventana aun cerrada). El suelo de 60s solo
    aplica cuando la ventana viene a 0 o ausente (un Retry(delay=0) elude el
    min_backoff del actor y buclearia contra el 429). Sin este freno el
    barrido seguia empresa a empresa contra una ventana cerrada, quemando
    la cuota por IP.
    """
    retry_after = float(getattr(exc, "retry_after", 0.0) or 0.0)
    delay_seconds = retry_after if retry_after > 0 else GDELT_RETRY_FLOOR_SECONDS
    delay_ms = int(delay_seconds * 1000)
    raise dramatiq.Retry(
        f"GDELT cerro la ventana (429): lote reencolado tras {delay_ms // 1000}s",
        delay=delay_ms,
    ) from exc


def _handle_actor_error(actor: str, exc: Exception, **context: Any) -> dict[str, Any]:
    """Re-raise transient errors so Dramatiq retries; record permanent ones.

    Every actor declares max_retries/backoff, but those knobs were dead while
    all exceptions were swallowed into the failure payload. Permanent errors
    keep the previous behavior: a structured result the scheduler can log.
    """
    if _is_transient(exc):
        raise exc
    return _failure(actor, exc, **context)


def _batch_status(processed: int, errors: list[dict]) -> str:
    if errors and processed:
        return "partial"
    if errors:
        return "error"
    return "ok"


def _coalesce_on_success(job: str, window_seconds, key_parts: tuple[str, ...] = ()):
    """Suprime re-encolados periodicos redundantes del backlog de ingesta.

    La cadencia del scheduler re-encola cada job aunque el anterior siga en
    cola (p.ej. 125 refresh_rss_feeds = 31 h de cadencia de 15 min): ejecutar
    uno deja obsoletos los demas. Semaforo por clave con DOS estados en la
    misma key de Redis:

    - CLAIM al inicio (SET NX EX ventana, atomico): si otro hilo/proceso ya
      lo tiene, la ejecucion devuelve skipped sin trabajar. Dos copias
      encoladas del mismo job no entran a la vez aunque no haya marca de
      exito previa.
    - MARCA FRESCA: el propio claim, cuya ventana cuenta desde el INICIO de
      la corrida, nunca desde el fin. Todas las ventanas son menores que la
      cadencia de su scheduler (tracked 25 < 30 min, universo 5 < 6 h, rss/
      insider 12 < 15, backfill 4 < 5, ir/macro 50 < 60), asi una corrida
      normal NUNCA descarta el siguiente tick: el claim expira antes de que
      llegue. Si se extendiera al terminar, un barrido universo de 3 h con
      marca de 5 h se saltaria el tick de las 6 h y la cadencia pasaria a
      12 h (hallazgo del auditor).

    Manejo de fallo: si el job devuelve error/partial o lanza, el claim se
    LIBERA (solo si seguimos siendo el dueno del token), asi un reintento o
    el siguiente tick del scheduler vuelven a correr el trabajo. Redis
    caido es fail-open (ejecuta siempre). Limite operativo declarado: si un
    job dura mas que su ventana, el claim expira y una copia encolada puede
    entrar en paralelo; las ventanas estan por encima de las duraciones
    medidas.
    window_seconds puede ser callable(**kwargs_del_actor) -> int.
    """
    import functools
    import inspect
    import uuid

    def decorator(fn):
        sig = inspect.signature(fn)

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            bound = sig.bind_partial(*args, **kwargs)
            values = bound.arguments
            parts = tuple(str(values.get(part)) for part in key_parts)
            window = int(window_seconds(**values) if callable(window_seconds) else window_seconds)
            key = "coalesce:" + ":".join((job, *parts))
            token = uuid.uuid4().hex
            try:
                client = _redis_client()
                claimed = True
                if client is not None:
                    claimed = bool(client.set(key, token, nx=True, ex=max(window, 1)))
            except Exception:  # noqa: BLE001 - sonda best-effort, fail-open
                client, claimed = None, True
            if client is not None and not claimed:
                return {
                    "status": "skipped",
                    "actor": job,
                    "reason": "fresh_or_running",
                    "window_seconds": window,
                }

            def _release() -> None:
                if client is None:
                    return
                # nosemgrep: gerarai-broad-except-pass -- lock/cola Redis best-effort con caducidad por TTL o fallback local documentado
                try:
                    # Compare-and-delete atomico (Lua): un GET+DELETE a mano
                    # dejaba una ventana en la que, si el claim expiraba y
                    # otro dueno reclamaba, el viejo borraba el claim nuevo.
                    client.eval(
                        "if redis.call('get', KEYS[1]) == ARGV[1] then"
                        " return redis.call('del', KEYS[1])"
                        " else return 0 end",
                        1,
                        key,
                        token,
                    )
                except Exception:  # noqa: BLE001 - expira por TTL solo
                    pass

            try:
                result = fn(*args, **kwargs)
            except BaseException:
                _release()  # el reintento de dramatiq debe poder reclamar
                raise
            # Exito: el claim queda como marca fresca con su TTL original
            # (anclado al INICIO) - extenderlo aqui descuadraria la cadencia.
            # Fallo: liberar para que el reintento o el siguiente tick corran.
            if client is not None and not (isinstance(result, dict) and result.get("status") == "ok"):
                _release()
            return result

        return wrapper

    return decorator


# Ventana de la marca "analisis ya encolado" del carril de alertas. El
# dispatch corre cada 15 min y el actor es idempotente (lease + gate de
# estado en BD), asi que la marca solo frena DUPLICADOS EN COLA, nunca el
# trabajo: al consumirse el mensaje la fila sale de "pending" y el
# re-encolado deja de verla. Si el mensaje muere sin consumirse (reintentos
# agotados), la marca expira y un ciclo posterior reintenta. 6 h absorbe un
# backlog largo sin congelar la recuperacion.
ANALYSIS_ENQUEUE_MARK_TTL_SECONDS = 6 * 60 * 60


def _analysis_enqueue_mark_key(tenant_id: int | None, alert_id: int) -> str:
    return f"analysis_enqueued:{tenant_id}:{alert_id}"


def _claim_analysis_enqueue(tenant_id: int | None, alert_id: int) -> bool:
    """Marca atomica "ya hay un analyze_tracked_news_alert en cola".

    True = este ciclo debe enviar el mensaje; False = ya hay uno en vuelo.
    Fail-open: sin Redis (o Redis roto) se envia igual, porque un duplicado
    lo absorben el lease del actor y su gate de estado, y perder el analisis
    seria peor.
    """
    try:
        client = _redis_client()
        if client is None:
            return True
        return bool(
            client.set(
                _analysis_enqueue_mark_key(tenant_id, alert_id),
                "1",
                nx=True,
                ex=ANALYSIS_ENQUEUE_MARK_TTL_SECONDS,
            )
        )
    except Exception:  # noqa: BLE001 - sonda best-effort, fail-open
        return True


def _clear_analysis_enqueue_mark(tenant_id: int | None, alert_id: int) -> None:
    """Libera la marca si el send fallo tras reclamarla (broker caido): sin
    esto la alerta esperaria el TTL entero pese a no tener mensaje en cola."""
    # nosemgrep: gerarai-broad-except-pass -- lock/cola Redis best-effort con caducidad por TTL o fallback local documentado
    try:
        client = _redis_client()
        if client is not None:
            client.delete(_analysis_enqueue_mark_key(tenant_id, alert_id))
    except Exception:  # noqa: BLE001 - expira por TTL solo
        pass


def _run(coroutine):
    """Ejecuta la corrutina del actor, venga de donde venga el loop.

    Delega en el puente compartido en vez de abrir su propio executor por
    llamada: asi los actores y los servicios sync comparten el mismo pool.
    """
    from app.services.async_bridge import run_from_any_context

    return run_from_any_context(coroutine)


def _session(tenant_id: int | None, user_id: str | None):
    from app.core.database import SessionLocal
    from app.models import Tenant

    if tenant_id is None or not user_id:
        raise ValueError("tenant_id and user_id are required for background jobs")
    db = SessionLocal()
    tenant = db.get(Tenant, tenant_id)
    if tenant is None or tenant.status != "active":
        db.close()
        raise ValueError(f"Active tenant {tenant_id} was not found")
    db.info["tenant_id"] = tenant.id
    db.info["user_id"] = user_id
    # i18n B: los jobs heredan el idioma guardado del tenant (generacion LLM).
    from app.core.i18n import SUPPORTED_LANGUAGES

    _lang = (tenant.metadata_ or {}).get("language")
    if _lang in SUPPORTED_LANGUAGES:
        db.info["language"] = _lang
    # El SELECT del tenant abre una transaccion (autocommit=False); sin este
    # commit cada actor arrancaba "idle in transaction" y la mantenia abierta
    # durante toda la unidad de trabajo, bloqueando escritores (p. ej. el
    # UPDATE de market_prices). db.info ya esta poblado y expire_on_commit=False
    # (database.py) mantiene los atributos del tenant utilizables tras el commit.
    db.commit()
    return db


KPI_QUEUE_NAME = "kpis"
# Carril de alertas aislado (patron thesis/kpis): la evaluacion de reglas
# cada 5 min y las entregas no compiten con la ingesta larga (GDELT ~3 h)
# en la cola default.
ALERT_QUEUE_NAME = "alerts"
# Carril GDELT aislado: news/macro_news consumen GDELT DOC 2.0, cuyo tier
# gratuito limita POR IP (~1 req / 5 s) y devuelve 429 bajo paralelismo. El
# pacing del cliente es un threading.Lock in-process, asi que el carril lo
# consume exactamente UN proceso (--processes 1): con dos procesos cada uno
# paceria por su cuenta y la tasa combinada romperia el limite. El resto de
# la ingesta (rss, insider, ir, sec-mirror, backfill) no pisa GDELT y se
# queda en default con mas hilos.
GDELT_QUEUE_NAME = "gdelt"
# Carril de computo rapido de cara al usuario (patron thesis/kpis/alerts):
# el run diario del embudo ProPicks y los calculos cortos se hambreaban en la
# cola default detras de la ingesta masiva (29-oct: default con >10k mensajes,
# ProPicks sin actualizar desde 28-oct 03:38 UTC por starvation, no por el
# filtro). Cola dedicada "computed" con worker propio de poca CPU (hay un
# spotdl en el mismo host). Los mensajes legacy ya en default los drena el
# worker default: queue_name solo enruta mensajes NUEVOS, el actor se
# resuelve por nombre al consumir.
COMPUTED_QUEUE_NAME = "computed"
KPI_DEFERRED_KEY = "kpi_deferred"
KPI_DEFER_MAX_ATTEMPTS = 5


def _redis_client():
    """Cliente redis corto para sondas de cola; None si no hay URL configurada."""
    import redis as _redis

    from app.core.redis_retry import no_retry

    url = _lease_redis_url()
    if not url:
        return None
    return _redis.from_url(url, socket_connect_timeout=2, socket_timeout=2, retry=no_retry())


def kpi_queue_depth(client=None) -> int | None:
    """Ready + running + delayed KPI work; None means Redis unavailable."""
    try:
        client = client if client is not None else _redis_client()
        if client is None:
            return None
        base = f"{broker.namespace}:{KPI_QUEUE_NAME}"
        return int(client.hlen(f"{base}.msgs")) + int(client.hlen(f"{base}.DQ.msgs"))
    except Exception:  # noqa: BLE001 - defer rather than bypass the admission gate
        return None


def kpi_queue_max_pending() -> int:
    return max_pending()


def kpi_defer_lease_seconds() -> int:
    """Lease de un diferido re-encolado: expirado, el backfill puede reintentarlo."""
    import os

    try:
        return max(60, int(os.getenv("KPI_DEFER_LEASE_SECONDS", "900")))
    except ValueError:
        return 900


def kpi_queue_has_capacity(client=None) -> bool:
    """True si la cola kpis admite mas trabajo sin degradar la cadencia LLM."""
    depth = kpi_queue_depth(client)
    return depth is not None and depth < kpi_queue_max_pending()


def tenant_contexts() -> list[tuple[int, str]]:
    """Return explicit tenant/user pairs for scheduler fan-out."""
    from sqlalchemy import select

    from app.core.database import SessionLocal
    from app.models import Tenant

    with SessionLocal() as db:
        tenants = db.scalars(
            select(Tenant)
            .where(Tenant.status == "active")
            .execution_options(include_all_tenants=True)
            .order_by(Tenant.id)
        ).all()
        contexts: list[tuple[int, str]] = []
        for tenant in tenants:
            user_id = str((tenant.metadata_ or {}).get("created_by") or "").strip()
            if user_id:
                contexts.append((tenant.id, user_id))
        return contexts


def _companies(db, ticker: str | None = None):
    from sqlalchemy import select

    from app.models import Company

    statement = select(Company)
    if ticker:
        statement = statement.where(Company.ticker == ticker.upper())
    return list(db.scalars(statement.order_by(Company.ticker)).all())


def _price_tracked_companies(db):
    """Carril rapido de PRECIOS: cartera + watchlist + tickers con reglas
    de alerta activas del tenant.

    Las reglas se evaluan cada hora contra market_prices local; si su
    precio solo llegara con el barrido de universo (6 h), dispararian
    tarde o mostrarian un valor antiguo como fresco. Su SLA sigue siendo
    1 h, asi que entran en el tracked de precios. Solo precios: el carril
    tracked de news (_tracked_companies) no cambia.
    """
    from sqlalchemy import select

    from app.core.tenancy import tenant_filters
    from app.models import AlertRule, Company

    tracked = {company.id: company for company in _tracked_companies(db)}
    alert_company_ids = [
        row[0]
        for row in db.execute(
            select(AlertRule.company_id)
            .where(
                AlertRule.active.is_(True),
                *tenant_filters(db, AlertRule),
            )
            .distinct()
        ).all()
    ]
    missing = [company_id for company_id in alert_company_ids if company_id not in tracked]
    if missing:
        for company in db.scalars(select(Company).where(Company.id.in_(missing))).all():
            tracked[company.id] = company
    return sorted(tracked.values(), key=lambda company: company.ticker)


def _tracked_companies(db):
    """Carril rápido de noticias: cartera + watchlist/seguidas del tenant.

    Decisión (2026-09-25): sus empresas cada 30 min; el universo
    completo sigue en background con el job scope="all".
    """
    from sqlalchemy import select

    from app.core.tenancy import tenant_filters
    from app.models import Company, Position, WatchItem

    tickers: set[str] = set()
    for (symbol,) in db.execute(select(WatchItem.symbol).where(*tenant_filters(db, WatchItem))).all():
        if symbol:
            tickers.add(str(symbol).upper())
            tickers.add(str(symbol).upper().split(".")[0])
    company_ids = [
        row[0]
        for row in db.execute(
            select(Position.company_id).where(*tenant_filters(db, Position)).distinct()
        ).all()
        if row[0] is not None
    ]
    from sqlalchemy import or_

    statement = select(Company).where(
        or_(
            Company.ticker.in_(tickers) if tickers else Company.id.is_(None),
            Company.id.in_(company_ids) if company_ids else Company.id.is_(None),
        )
    )
    return list(db.scalars(statement.order_by(Company.ticker)).all())


def _rollback(db) -> None:
    try:
        db.rollback()
    except Exception:
        pass


def _message_id(message) -> str | None:
    return str(message.message_id) if getattr(message, "message_id", None) else None


# ---------------------------------------------------------------------------
# Idempotencia de emits + lease TTL de jobs
# ---------------------------------------------------------------------------

_local_leases: dict[str, tuple[str, float]] = {}
_local_leases_lock = threading.Lock()


def _emit_fingerprint(*parts: Any) -> str:
    """Fingerprint estable de un emit (regla + transacción/documento).

    Re-emitir el mismo fingerprint dentro de una ejecución se omite: los
    workers nunca encolan duplicados aunque el upstream repita filas.
    """
    raw = "|".join(str(part) for part in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def acquire_job_lease(
    job_name: str,
    *,
    ttl_seconds: int = 3600,
    redis_url: str | None = None,
) -> str | None:
    """Lease distribuido con TTL para jobs (una sola ejecución en vuelo).

    Devuelve el token del lease o None si otro worker lo tiene (el actor
    debe responder ``status=skipped, reason=lease_held``). Redis ``SET NX
    EX``; sin Redis, fallback local en proceso (documentado: solo frena
    solapes dentro de este proceso).
    """
    token = uuid.uuid4().hex
    if redis_url:
        # nosemgrep: gerarai-broad-except-pass -- lock/cola Redis best-effort con caducidad por TTL o fallback local documentado
        try:
            import redis as redis_sync

            from app.core.redis_retry import no_retry

            client = redis_sync.Redis.from_url(redis_url, socket_connect_timeout=0.25, retry=no_retry())
            try:
                acquired = client.set(
                    f"cavaai:job-lease:{job_name}", token, nx=True, ex=max(int(ttl_seconds), 1)
                )
            finally:
                client.close()
            return token if acquired else None
        except Exception:  # noqa: BLE001 — fallback local documentado
            pass
    now = time.time()
    # Los actores de dramatiq corren en hilos: comprobar y escribir sin cerrojo
    # dejaba entrar a dos hilos a la vez en el mismo lease.
    with _local_leases_lock:
        held = _local_leases.get(job_name)
        if held is not None and held[1] > now:
            return None
        _local_leases[job_name] = (token, now + max(int(ttl_seconds), 1))
    return token


# Compare-and-del atomico: un GET+DEL separados dejaba una ventana en la
# que, si el TTL vencia entre ambas operaciones y otro worker adquiria el
# lease, el DEL borraba el lease AJENO recien adquirido.
_RELEASE_LEASE_LUA = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
end
return 0
"""


def release_job_lease(job_name: str, token: str, *, redis_url: str | None = None) -> None:
    """Libera el lease solo si sigue siendo nuestro (best-effort).

    Redis: compare-and-del atomico via Lua (sin ventana GET/DEL). Fallback
    local: exclusion solo dentro de este proceso - con Redis caido dos
    procesos pueden solapar el mismo job (riesgo operativo aceptado y
    documentado: monitorizar la disponibilidad de Redis).
    """
    if redis_url:
        # nosemgrep: gerarai-broad-except-pass -- lock/cola Redis best-effort con caducidad por TTL o fallback local documentado
        try:
            import redis as redis_sync

            from app.core.redis_retry import no_retry

            client = redis_sync.Redis.from_url(redis_url, socket_connect_timeout=0.25, retry=no_retry())
            try:
                client.eval(_RELEASE_LEASE_LUA, 1, f"cavaai:job-lease:{job_name}", token)
                return
            finally:
                client.close()
        except Exception:  # noqa: BLE001 — best-effort
            pass
    with _local_leases_lock:
        held = _local_leases.get(job_name)
        if held is not None and held[0] == token:
            _local_leases.pop(job_name, None)


def _lease_redis_url() -> str | None:
    try:
        return get_settings().redis_url
    except Exception:  # noqa: BLE001 — sin settings hay fallback local
        return None


def reset_local_leases() -> None:
    """Test helper: clear the in-process job leases."""
    _local_leases.clear()


@dramatiq.actor(max_retries=2, min_backoff=15_000, queue_name=KPI_QUEUE_NAME)
def extract_document_kpis(
    document_id: int,
    *,
    tenant_id: int | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    """Idempotently extract approval candidates from one persisted document."""
    from app.models import Document
    from app.services.kpi_extraction_service import KPIExtractionService

    db = _session(tenant_id, user_id)
    try:
        document = db.get(Document, document_id)
        if document is None:
            raise ValueError(f"Document {document_id} was not found")
        candidates = _run(KPIExtractionService().extract_document(db, document))
        meta = dict(document.metadata_ or {})
        if meta.pop(KPI_DEFERRED_KEY, None) is not None:
            document.metadata_ = meta
            db.commit()
        return {
            "status": "ok",
            "document_id": document_id,
            "candidate_ids": [candidate.id for candidate in candidates],
            "candidates": len(candidates),
        }
    except Exception as exc:
        _rollback(db)
        return _handle_actor_error("extract_document_kpis", exc, document_id=document_id)
    finally:
        db.close()


def enqueue_document_kpis(db, document) -> dict[str, Any]:
    """Persist recovery state before sending, including ambiguous timeouts.

    A Redis outage/full queue never loses the ingested document's KPI work.
    Admission is atomic in BoundedRedisBroker, not a read-then-send probe.
    """
    meta = dict(document.metadata_ or {})
    deferred = {"attempts": 0, "queued_at": int(time.time())}
    document.metadata_ = {**meta, KPI_DEFERRED_KEY: deferred}
    db.commit()
    try:
        message = extract_document_kpis.send(
            document.id,
            tenant_id=int(db.info["tenant_id"]),
            user_id=str(db.info["user_id"]),
        )
    except QueueCapacityError:
        document.metadata_ = {**meta, KPI_DEFERRED_KEY: {"attempts": 0}}
        db.commit()
        return {"status": "deferred_backpressure"}
    except Exception as exc:  # noqa: BLE001 - timeout may have accepted the send
        return {"status": "queue_unavailable", "error": type(exc).__name__}
    return {"status": "queued", "message_id": str(message.message_id)}


@dramatiq.actor(max_retries=1, min_backoff=30_000)
@_coalesce_on_success("backfill_document_kpis", 4 * 60)
def backfill_document_kpis() -> dict[str, Any]:
    """Re-encola extracciones KPI diferidas por backpressure, mas antiguas primero.

    La ingesta marca document.metadata_["kpi_deferred"] cuando frena la
    fuente; aqui se recuperan hasta el tope de la cola. Cada re-encolado
    incrementa el contador y se para en KPI_DEFER_MAX_ATTEMPTS para que un
    documento que falla siempre no reintente eternamente (queda visible con
    el flag puesto). La extraccion es idempotente por documento.
    """
    import time

    from sqlalchemy import Integer, cast, func, or_, select

    from app.models import Document

    client = _redis_client()
    depth = kpi_queue_depth(client)
    if depth is None:
        return {"actor": "backfill_document_kpis", "status": "skipped", "reason": "queue_unavailable"}
    capacity = kpi_queue_max_pending() - depth
    if capacity <= 0:
        return {"actor": "backfill_document_kpis", "status": "skipped", "reason": "queue_full"}
    queued = 0
    exhausted = 0
    for tenant_id, user_id in tenant_contexts():
        if queued >= capacity:
            break
        db = _session(tenant_id, user_id)
        try:
            now = int(time.time())
            attempts_expr = cast(Document.metadata_[(KPI_DEFERRED_KEY, "attempts")].as_string(), Integer)
            queued_raw = Document.metadata_[(KPI_DEFERRED_KEY, "queued_at")]
            queued_expr = cast(queued_raw.as_string(), Integer)
            # Regla anti-duplicado definitiva (auditor, bounce 3): un doc YA
            # encolado solo se reencola cuando la cola esta VACIA (depth == 0):
            # si hay mensajes en vuelo no se puede distinguir "perdido" de
            # "esperando", y reenviar pagaria llamadas LLM duplicadas aunque
            # el lease haya expirado (un backlog largo retiene mensajes mas
            # que el lease). Los nunca enviados (queued_at NULL) siempre son
            # elegibles.
            # OJO: queued_raw.is_(None) NO es portable - en sqlite SQLAlchemy
            # envuelve la extraccion en JSON_QUOTE y 'null' (texto) no es NULL.
            # .as_string() (JSON_EXTRACT / ->>) devuelve NULL real en ambos.
            never_sent = queued_raw.as_string().is_(None)
            if depth == 0:
                lease_filter = or_(
                    never_sent,
                    func.coalesce(queued_expr, 0) < now - kpi_defer_lease_seconds(),
                )
            else:
                lease_filter = never_sent
            pending = db.scalars(
                select(Document)
                .where(
                    # Existencia del flag: .as_string().isnot(None) - el
                    # predicado crudo .isnot(None) en sqlite pasa por
                    # JSON_QUOTE y devuelve 'null' TEXTO para docs sin flag
                    # (IS NOT NULL = True), lo que seleccionaria documentos
                    # ordinarios: backfill les marcaria kpi_deferred y les
                    # enviaria extraccion PAGADA nunca diferida, comiendose
                    # el LIMIT por delante de los genuinos (auditor, bounce 6).
                    Document.metadata_[KPI_DEFERRED_KEY].as_string().isnot(None),
                    # Agotados filtrados ANTES del LIMIT: si no, un bloque de
                    # docs antiguos agotados llenaria el LIMIT en cada corrida
                    # y ningun diferido elegible se reencolaria jamas.
                    func.coalesce(attempts_expr, 0) < KPI_DEFER_MAX_ATTEMPTS,
                    lease_filter,
                )
                .order_by(Document.created_at)
                .limit(capacity - queued)
            ).all()
            for document in pending:
                if queued >= capacity:
                    break
                meta = dict(document.metadata_ or {})
                deferred = dict(meta.get(KPI_DEFERRED_KEY) or {})
                attempts = int(deferred.get("attempts") or 0)
                if attempts >= KPI_DEFER_MAX_ATTEMPTS:
                    exhausted += 1
                    continue
                deferred["attempts"] = attempts + 1
                deferred["queued_at"] = now
                meta[KPI_DEFERRED_KEY] = deferred
                document.metadata_ = meta
                # Reserva persistida ANTES de enviar (auditor, bounce 4): un
                # commit unico al final del lote revertia las reservas ya
                # enviadas si un send posterior fallaba, y la pasada
                # siguiente las duplicaba. Commit por doc; si el send falla
                # se limpia queued_at (nada entro en Redis) y se reintenta
                # como nunca enviado con el attempts ya consumido.
                db.commit()
                try:
                    extract_document_kpis.send(document.id, tenant_id=tenant_id, user_id=user_id)
                except QueueCapacityError:
                    deferred["attempts"] = attempts
                    deferred.pop("queued_at", None)
                    document.metadata_ = {**meta, KPI_DEFERRED_KEY: deferred}
                    db.commit()
                    return {
                        "actor": "backfill_document_kpis",
                        "status": "ok",
                        "queued": queued,
                        "exhausted": exhausted,
                        "capacity": capacity,
                    }
                except Exception:  # noqa: BLE001 - un send roto no frena el lote
                    # Resultado INCIERTO (auditor, bounce 5): un error de red
                    # o timeout no prueba que el mensaje no entrase en Redis
                    # (pudo aceptarse y perderse la respuesta). La reserva se
                    # MANTIENE siempre; la reconciliacion la cubre la regla
                    # depth==0 + lease expirado: si no entro de verdad, la
                    # cola vaciara y se reencolara seguro; si entro, depth>0
                    # lo protege de duplicados.
                    continue
                queued += 1
        finally:
            db.close()
    return {
        "actor": "backfill_document_kpis",
        "status": "ok",
        "queued": queued,
        "exhausted": exhausted,
        "capacity": capacity,
    }


RECOMPUTE_METRICS_CHUNK = 60


@dramatiq.actor(max_retries=1, min_backoff=30_000, queue_name=KPI_QUEUE_NAME)
def recompute_fundamental_metrics(
    tenant_id: int | None = None,
    user_id: str | None = None,
    ticker: str | None = None,
    start_from: str | None = None,
    limit: int = RECOMPUTE_METRICS_CHUNK,
) -> dict[str, Any]:
    """Recalcula CalculatedMetric en bulk para empresas con financial_facts.

    Los ratios derivados (roe, margenes, roic, wacc...) solo se calculaban
    on-demand al abrir una empresa: la cobertura del universo era ~cero y los
    screeners fundamentales no podian filtrar. Este actor barre las empresas
    con hechos por chunks (cursor por ticker) y se auto-encola hasta agotar
    el universo; cada calculate_all es idempotente (upsert por empresa/
    metrica/periodo) y nunca inventa inputs: sin hechos coherentes la
    metrica queda "unavailable", como siempre. Un empresa que falla no frena
    el barrido: se anota y se sigue.
    """
    actor_name = "recompute_fundamental_metrics"
    from sqlalchemy import select

    from app.models import Company, FinancialFact
    from app.services.metric_calculation_service import MetricCalculationService

    try:
        db = _session(tenant_id, user_id)
    except Exception as exc:  # noqa: BLE001
        return _handle_actor_error(actor_name, exc, tenant_id=tenant_id, ticker=ticker)
    try:
        with_facts = (
            select(FinancialFact.company_id)
            .where(FinancialFact.tenant_id == db.info.get("tenant_id"))
            .distinct()
            .scalar_subquery()
        )
        statement = select(Company).where(Company.id.in_(with_facts))
        if ticker:
            statement = statement.where(Company.ticker == ticker.upper())
        if start_from:
            statement = statement.where(Company.ticker > start_from.upper())
        companies = list(db.scalars(statement.order_by(Company.ticker).limit(limit)).all())
        service = MetricCalculationService()
        processed = 0
        status_counts: dict[str, int] = {}
        errors: list[dict] = []
        from app.services.derived_market_cap_service import (
            refresh_derived_market_cap,
        )

        derived_cap: dict[str, int] = {}
        for company in companies:
            try:
                # Respaldo de market_cap (precio x acciones) ANTES del calculo:
                # sin el, el WACC sale unavailable y el DCF no arranca (QA:
                # 6/6 candidatas N/D; watchlist europeas sin cap).
                # ttl=None: el barrido no reescribe filas identicas;
                # escribe solo cuando el valor cambia (ver servicio).
                cap = refresh_derived_market_cap(db, company, ttl=None)
                derived_cap[cap["status"]] = derived_cap.get(cap["status"], 0) + 1
                results = service.calculate_all(db, company, persist=True)
                processed += 1
                for result in results:
                    key = result.status or "unknown"
                    status_counts[key] = status_counts.get(key, 0) + 1
            except Exception as exc:  # noqa: BLE001 - una empresa no frena el barrido
                _rollback(db)
                errors.append(
                    {
                        "ticker": company.ticker,
                        "type": type(exc).__name__,
                        "message": str(exc)[:200],
                    }
                )
        next_cursor = None
        if not ticker and len(companies) == limit:
            # Queda universo por barrer: el chunk siguiente arranca tras el
            # ultimo ticker visto. Sin coalesce a proposito: cada chunk es
            # trabajo distinto y no debe suprimir al siguiente.
            next_cursor = companies[-1].ticker
            recompute_fundamental_metrics.send(tenant_id, user_id, start_from=next_cursor, limit=limit)
        return {
            "status": _batch_status(processed, errors),
            "actor": actor_name,
            "companies_processed": processed,
            "metric_statuses": status_counts,
            "next_start_from": next_cursor,
            "errors": errors,
        }
    except Exception as exc:  # noqa: BLE001
        return _handle_actor_error(actor_name, exc, tenant_id=tenant_id, ticker=ticker)
    finally:
        db.close()


@dramatiq.actor(max_retries=2, min_backoff=15_000)
def extract_knowledge_principles(
    processing_job_id: int,
    *,
    tenant_id: int | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    """Extract, deduplicate and consolidate one knowledge document in bounded batches."""
    from app.models import KnowledgeDocument, ProcessingJob
    from app.services.knowledge_library_service import KnowledgeLibraryService

    db = _session(tenant_id, user_id)
    job = db.get(ProcessingJob, processing_job_id)
    try:
        if job is None:
            raise ValueError(f"Processing job {processing_job_id} was not found")
        document = db.get(KnowledgeDocument, job.entity_id)
        if document is None:
            raise ValueError(f"Knowledge document {job.entity_id} was not found")
        job.status = "running"
        job.started_at = datetime.now(UTC)
        db.commit()

        def update_progress(current: int, total: int) -> None:
            job.progress_current = current
            job.progress_total = total
            db.commit()

        result = _run(
            KnowledgeLibraryService().extract_principle_batches(
                db,
                document,
                progress=update_progress,
            )
        )
        principle_ids = [principle.id for principle in result.pop("principles")]
        # Un corte por presupuesto no es un exito completo: "partial".
        job.status = "partial" if result.get("budget_stopped") else "completed"
        job.result = {**result, "principle_ids": principle_ids}
        job.completed_at = datetime.now(UTC)
        db.commit()
        return {"status": "ok", "processing_job_id": job.id, **job.result}
    except Exception as exc:
        _rollback(db)
        if job is not None:
            from app.services.knowledge_library_service import extraction_error_message

            job.status = "failed"
            job.error = extraction_error_message(exc)
            job.completed_at = datetime.now(UTC)
            db.commit()
        return _handle_actor_error(
            "extract_knowledge_principles",
            exc,
            processing_job_id=processing_job_id,
        )
    finally:
        db.close()


@dramatiq.actor(max_retries=1, queue_name=ALERT_QUEUE_NAME)
def evaluate_alert_rules(
    tenant_id: int | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    from app.services.alert_rule_service import AlertRuleService

    db = _session(tenant_id, user_id)
    try:
        results = AlertRuleService().evaluate_all(db)
        return {
            "status": "ok",
            "actor": "evaluate_alert_rules",
            "evaluated": len(results),
            "triggered": sum(result.get("status") == "triggered" for result in results),
            "results": results,
        }
    except Exception as exc:
        _rollback(db)
        return _handle_actor_error("evaluate_alert_rules", exc, tenant_id=tenant_id)
    finally:
        db.close()


@dramatiq.actor(max_retries=1, min_backoff=30_000)
def refresh_asts_catalog() -> dict[str, Any]:
    """One global network fetch, explicit tenant-scoped persisted copies."""
    from app.services.asts_catalog_service import (
        MIN_FETCH_INTERVAL,
        latest_download_at,
        persist_catalog,
        record_download_attempt,
    )
    from app.services.connectors.celestrak_ast import fetch_catalog
    from app.services.connectors.celestrak_ast_supgp import fetch_supgp

    contexts = tenant_contexts()
    if not contexts:
        return {"actor": "refresh_asts_catalog", "status": "skipped", "reason": "no_tenants"}
    # Lease first, then check the persisted last attempt while holding it.
    # This avoids a second worker racing between the timestamp read and the
    # outbound HTTP request. The 2h TTL is a fallback; the durable timestamp
    # remains authoritative across restarts and failed network attempts.
    lease = acquire_job_lease("celestrak_ast_2h", ttl_seconds=7200, redis_url=_lease_redis_url())
    if lease is None:
        return {"actor": "refresh_asts_catalog", "status": "skipped", "reason": "celestrak_2h_minimum"}
    fetched_at = datetime.now(UTC)
    attempts_recorded = False
    try:
        recent = []
        for tenant_id, user_id in contexts:
            db = _session(tenant_id, user_id)
            try:
                last = latest_download_at(db)
                if last is not None:
                    recent.append(last.replace(tzinfo=UTC) if last.tzinfo is None else last)
            finally:
                db.close()
        if recent and fetched_at - max(recent) < MIN_FETCH_INTERVAL:
            return {"actor": "refresh_asts_catalog", "status": "skipped", "reason": "celestrak_2h_minimum"}
        # All context writes must succeed before the first network call.
        for tenant_id, user_id in contexts:
            db = _session(tenant_id, user_id)
            try:
                record_download_attempt(db, fetched_at)
            finally:
                db.close()
        attempts_recorded = True
    finally:
        # If validation failed or the actor skipped, release the lease. Once
        # outbound I/O starts, keep the full 2h TTL as an extra rate guard.
        if not attempts_recorded:
            release_job_lease("celestrak_ast_2h", lease, redis_url=_lease_redis_url())
    catalog = None
    gp_error = None
    try:
        catalog = _run(fetch_catalog(fetched_at=fetched_at))
    except Exception as exc:
        gp_error = type(exc).__name__
    # Each source is attempted independently; one failed endpoint does not
    # relabel the other source or renew the failed source's freshness.
    supgp = None
    supgp_error = None
    try:
        supgp = _run(fetch_supgp(catalog, fetched_at=fetched_at))
    except Exception as exc:
        supgp_error = type(exc).__name__
    if catalog is None and supgp is None:
        return {
            "actor": "refresh_asts_catalog",
            "status": "error",
            "gp_error": gp_error,
            "supgp_error": supgp_error,
        }
    errors = []
    for tenant_id, user_id in contexts:
        db = _session(tenant_id, user_id)
        try:
            persist_catalog(db, catalog or [], fetched_at, supgp=supgp)
        except Exception as exc:
            _rollback(db)
            errors.append({"tenant_id": tenant_id, "type": type(exc).__name__})
        finally:
            db.close()
    return {
        "actor": "refresh_asts_catalog",
        "status": "partial" if errors or gp_error or supgp_error else "ok",
        "gp_error": gp_error,
        "count": len(catalog) if catalog is not None else 0,
        "supgp_count": len(supgp) if supgp is not None else 0,
        "supgp_error": supgp_error,
        "tenant_count": len(contexts),
        "errors": errors,
    }


@dramatiq.actor(max_retries=1, min_backoff=30_000, dedup_enqueue_ttl=DEDUP_ENQUEUE_TTL_SECONDS)
def refresh_bottlenecks(tenant_id: int | None = None, user_id: str | None = None) -> dict[str, Any]:
    """Reconcile all local evidence, including historical letters, without AI."""
    from app.services.bottleneck_service import refresh_signals

    db = _session(tenant_id, user_id)
    try:
        count = refresh_signals(db)
        db.commit()
        return {"actor": "refresh_bottlenecks", "status": "ok", "themes": count}
    except Exception as exc:
        _rollback(db)
        return _handle_actor_error("refresh_bottlenecks", exc)
    finally:
        db.close()


@dramatiq.actor(max_retries=1, min_backoff=30_000, time_limit=600_000)
def ingest_sec_bottleneck_filings(tenant_id: int | None = None, user_id: str | None = None) -> dict[str, Any]:
    """Pasajes de escasez de filings SEC (EFTS full-text, gratis) como documentos.

    Solo lee de la SEC y escribe Document/DocumentChunk; la deteccion la hace
    el refresh horario existente sobre lo persistido. Fail-closed por tema.
    """
    from app.services.sec_bottleneck_filings import ingest_all

    db = _session(tenant_id, user_id)
    try:
        result = _run(ingest_all(db, db.info["tenant_id"]))
        return {"actor": "ingest_sec_bottleneck_filings", "status": "ok", **result}
    except Exception as exc:
        _rollback(db)
        return _handle_actor_error("ingest_sec_bottleneck_filings", exc)
    finally:
        db.close()


@dramatiq.actor(max_retries=1, min_backoff=30_000, time_limit=300_000)
def ingest_uk_pdmr_filings(tenant_id: int | None = None, user_id: str | None = None) -> dict[str, Any]:
    """Movimientos PDMR del Reino Unido (tracefour, gratis, CC BY 4.0): 1 GET por corrida."""
    from app.services.uk_pdmr_ingestion import ingest_uk_pdmr

    db = _session(tenant_id, user_id)
    try:
        result = _run(ingest_uk_pdmr(db, db.info["tenant_id"]))
        return {"actor": "ingest_uk_pdmr_filings", "status": "ok", **result}
    except Exception as exc:
        _rollback(db)
        return _handle_actor_error("ingest_uk_pdmr_filings", exc)
    finally:
        db.close()


@dramatiq.actor(max_retries=1, min_backoff=30_000, time_limit=300_000)
def ingest_ca_insider_yahoo(tenant_id: int | None = None, user_id: str | None = None) -> dict[str, Any]:
    """Insiders de Canada via Yahoo quoteSummary (FUENTE NO OFICIAL; SEDI es la verdad)."""
    from app.services.ca_insider_ingestion import ingest_ca_insiders

    db = _session(tenant_id, user_id)
    try:
        result = _run(ingest_ca_insiders(db, db.info["tenant_id"]))
        return {"actor": "ingest_ca_insider_yahoo", "status": "ok", **result}
    except Exception as exc:
        _rollback(db)
        return _handle_actor_error("ingest_ca_insider_yahoo", exc)
    finally:
        db.close()


DISCOVERY_DEADLINE_SECONDS = 480  # margen de 2 min bajo el time_limit de 10 min


@dramatiq.actor(max_retries=1, min_backoff=30_000, time_limit=600_000)
def discover_bottlenecks(tenant_id: int | None = None, user_id: str | None = None) -> dict[str, Any]:
    """Candidatos INFERIDOS por tema de cuello de botella (solo proveedor gratuito, sin dinero)."""
    from app.services.bottleneck_discovery_service import discover
    from app.services.ticker_news_lane import Deadline

    db = _session(tenant_id, user_id)
    try:
        deadline = Deadline(DISCOVERY_DEADLINE_SECONDS)
        # Derive contexts from current stored evidence, not a possibly empty
        # signal table waiting for the hourly reconciliation.
        from app.services.bottleneck_service import refresh_signals

        refresh_signals(db)
        db.commit()
        outcome = _run(discover(db, deadline=deadline))
        status = "partial" if deadline.truncated and outcome.get("status") == "ok" else outcome["status"]
        return {"actor": "discover_bottlenecks", **outcome, "status": status}
    except Exception as exc:
        _rollback(db)
        return _handle_actor_error("discover_bottlenecks", exc, tenant_id=tenant_id)
    finally:
        db.close()


@dramatiq.actor(max_retries=1, min_backoff=30_000)
def refresh_macro_context() -> dict[str, Any]:
    """Fetch public FRED CSV once globally, then persist an honest snapshot."""
    from app.core.database import SessionLocal
    from app.services.market_observation_service import refresh_fred
    from app.services.market_snapshot_service import build_snapshot

    with SessionLocal() as db:
        try:
            outcome = _run(refresh_fred(db))
            snapshot = build_snapshot(db, datetime.now(UTC).date())
            return {
                "actor": "refresh_macro_context",
                "status": "partial" if outcome["errors"] else "ok",
                "ingestion": outcome,
                "snapshot_id": snapshot.id,
                "coverage": snapshot.coverage,
            }
        except Exception as exc:
            _rollback(db)
            return _handle_actor_error("refresh_macro_context", exc)


@dramatiq.actor(max_retries=2, min_backoff=60_000)
def sync_ibkr_flex() -> dict[str, Any]:
    """Sincroniza la cartera real desde IBKR Flex Web Service (solo lectura).

    El token es de UNA cuenta: se aplica solo al tenant IBKR_FLEX_TENANT_ID,
    nunca por fan-out. Sin token, query id o tenant no hace nada. La descarga
    ocurre sin sesion de DB abierta (pool 5+10) y los errores no llevan el token.
    """
    from app.core.config import get_settings
    from app.services.connectors.ibkr import IBKRFlexClient
    from app.services.ibkr_import_service import IBKRImportError, IBKRImportService, IBKRPnlNotReadyError

    client = IBKRFlexClient()
    tenant_id = get_settings().ibkr_flex_tenant_id
    # Once the owner has configured/unlinked a tenant connector, never silently
    # revive server-global credentials after disconnect or duplicate its sync.
    if tenant_id is not None:
        from sqlalchemy import select

        from app.core.database import SessionLocal
        from app.models import IBKRConnection

        with SessionLocal() as admin:
            migrated = admin.scalar(
                select(IBKRConnection.id)
                .where(
                    IBKRConnection.tenant_id == tenant_id,
                )
                .execution_options(include_all_tenants=True)
            )
        if migrated is not None:
            return {"actor": "sync_ibkr_flex", "status": "skipped", "reason": "tenant_connector"}
    account_id = (get_settings().ibkr_flex_account_id or "").strip()
    if not client.configured() or tenant_id is None or not account_id:
        return {"actor": "sync_ibkr_flex", "status": "skipped", "reason": "not_configured"}
    user_id = next((uid for tid, uid in tenant_contexts() if tid == tenant_id), None)
    if user_id is None:
        return {"actor": "sync_ibkr_flex", "status": "skipped", "reason": "tenant_not_active"}
    try:
        xml_text = _run(client.fetch_latest_xml())
    except Exception as exc:  # noqa: BLE001 - IBKRFlexError ya viene sin token
        return _handle_actor_error("sync_ibkr_flex", exc)
    db = _session(tenant_id, user_id)
    try:
        result = IBKRImportService().import_flex_xml(
            db,
            xml_text,
            reconcile=True,
            expected_account_id=account_id,
            query_complete_attested=bool(
                get_settings().ibkr_flex_complete_query_id
                and get_settings().ibkr_flex_complete_query_id == get_settings().ibkr_flex_query_id
            ),
        )
        return {
            "actor": "sync_ibkr_flex",
            "status": result["status"],
            "positions_imported": result["positions_imported"],
            "cash_imported": result["cash_imported"],
            "trades_imported": result["trades_imported"],
            "rows_skipped": result["rows_skipped"],
            "row_errors": len(result["row_errors"]),
            "positions_closed": result["positions_closed"],
            "cash_removed": result["cash_removed"],
            "reconcile_blocked": result["reconcile_blocked"],
        }
    except IBKRPnlNotReadyError as exc:
        _rollback(db)
        # At most the actor's two retries, one hour apart. Each retry obtains
        # a new statement; no repeated polling of the incomplete report.
        raise dramatiq.Retry("IBKR PyG aun no disponible; reintento en una hora", delay=3_600_000) from exc
    except IBKRImportError as exc:
        _rollback(db)
        return _failure("sync_ibkr_flex", exc)
    except Exception as exc:  # noqa: BLE001
        _rollback(db)
        return _handle_actor_error("sync_ibkr_flex", exc)
    finally:
        db.close()


@dramatiq.actor(max_retries=2, min_backoff=15_000, queue_name="prices")
def refresh_market_pipeline(
    tenant_id: int | None = None,
    user_id: str | None = None,
    scope: str = "tracked",
) -> dict[str, Any]:
    from app.services.market_refresh_service import MarketRefreshService

    if scope not in ("tracked", "universe"):
        raise ValueError(f"scope de refresh_market_pipeline desconocido: {scope!r}")
    db = _session(tenant_id, user_id)
    # La sesion se abre ANTES de tomar el lease: _session() lanza
    # ValueError si el tenant no esta activo, y esa excepcion entre la
    # toma del lease y el try se escapaba sin pasar por el finally que
    # lo libera, dejando el lease retenido hasta su TTL.
    try:
        lease = acquire_job_lease(
            f"refresh_market_pipeline:{tenant_id}",
            ttl_seconds=3000,
            redis_url=_lease_redis_url(),
        )
    except Exception:
        # Si la adquisicion lanza (Redis caido, red, ...), la sesion abierta
        # justo arriba no puede quedar sin cerrar.
        db.close()
        raise
    if lease is None:
        db.close()
        return {
            "status": "skipped",
            "actor": "refresh_market_pipeline",
            "reason": "lease_held",
        }
    try:
        # Dos velocidades: cartera+watchlist+reglas de alerta activas cada
        # ciclo horario; el universo completo va en el job scope="universe"
        # de menor cadencia (scheduler). El screener sirve quotes en vivo
        # por su propia via de vendors, asi que su frescura no depende del
        # barrido de universo.
        companies = None if scope == "universe" else _price_tracked_companies(db)
        result = _run(MarketRefreshService().refresh(db, companies=companies))
        return {"actor": "refresh_market_pipeline", "scope": scope, **result}
    except Exception as exc:
        _rollback(db)
        return _handle_actor_error("refresh_market_pipeline", exc, tenant_id=tenant_id)
    finally:
        release_job_lease(f"refresh_market_pipeline:{tenant_id}", lease, redis_url=_lease_redis_url())
        db.close()


@dramatiq.actor(max_retries=1, min_backoff=30_000)
def refresh_portfolio_moves(tenant_id: int | None = None, user_id: str | None = None) -> dict[str, Any]:
    """Digest the last completed session's closes (skips weekends) for one tenant."""
    from app.services.portfolio_moves_service import build_digest

    db = _session(tenant_id, user_id)
    try:
        from app.services.daily_digest_alerts import last_session_date

        as_of = last_session_date(datetime.now(UTC).date())
        digest = build_digest(db, as_of)
        from app.services.daily_digest_alerts import emit_digest_alert

        try:
            emitted = emit_digest_alert(db, digest, as_of)
        except Exception as exc:
            _rollback(db)
            logger.exception("refresh_portfolio_moves: fallo emitiendo el resumen diario")
            # Digest construido pero aviso no emitido: parcial, nunca verde falso.
            return {
                "actor": "refresh_portfolio_moves",
                "status": "partial",
                "digest_id": digest.id,
                "coverage": digest.coverage,
                "digest_alert": "error",
                "alert_error": str(exc)[:200],
            }
        return {
            "actor": "refresh_portfolio_moves",
            "status": "ok",
            "digest_id": digest.id,
            "coverage": digest.coverage,
            "digest_alert": "emitted" if emitted is not None else "already_emitted",
            "digest_alert_id": emitted.id if emitted is not None else None,
        }
    except Exception as exc:
        _rollback(db)
        return _handle_actor_error("refresh_portfolio_moves", exc, tenant_id=tenant_id)
    finally:
        db.close()


@dramatiq.actor(max_retries=1, min_backoff=60_000, time_limit=1_800_000)
def backfill_finnhub_profiles(
    tenant_id: int | None = None,
    user_id: str | None = None,
    max_companies: int = 300,
) -> dict[str, Any]:
    """PR-D resto: backfill presupuestado de perfiles Finnhub (quote +
    profile2) para el universo: nombre real, exchange, divisa, pais de
    domicilio y market_cap de proveedor fechado con la sesion de la quote.

    Presupuesto: como mucho `max_companies` companias por ejecucion con
    pausa tras cada llamada (plan gratuito = 60 llamadas/min). La marca de
    reanudacion es un Document ``finnhub_profile`` por compania; las
    respuestas vacias no se reconsultan en 30 dias. Nunca inventa datos:
    sin clave o sin respuesta queda contado, nada escrito.
    """
    from app.services.finnhub_profile_backfill import FinnhubProfileBackfill

    db = _session(tenant_id, user_id)
    try:
        service = FinnhubProfileBackfill()
        try:
            result = service.backfill(db, max_companies=max_companies)
        finally:
            service.close()
        return {"actor": "backfill_finnhub_profiles", **result}
    except Exception as exc:
        _rollback(db)
        return _handle_actor_error("backfill_finnhub_profiles", exc, tenant_id=tenant_id)


@dramatiq.actor(max_retries=1, min_backoff=60_000, time_limit=1_800_000)
def backfill_sec_fundamentals(
    tenant_id: int | None = None,
    user_id: str | None = None,
    max_companies: int = 100,
) -> dict[str, Any]:
    """Backfill presupuestado de fundamentales SEC (companyfacts) para el
    universo US del tenant. Medido en prod (19 oct 2026): solo 164/2.135
    companias tenian fundamentales SEC porque la ingesta era solo por
    demanda (ficha/tesis); ESEF y Finnhub profiles ya tenian su carril
    programado y SEC no. Anti-atasco: candidatas prefiltradas por la
    guarda de identidad sec_eligible y rotacion por ultimo intento
    persistido (skipped/error no se reintentan hasta 3d). Fallos contados,
    nunca inventados. Coste 0 EUR."""
    from app.services.sec_fundamentals_backfill import backfill_sec_fundamentals as _run

    db = _session(tenant_id, user_id)
    try:
        return {"actor": "backfill_sec_fundamentals", **_run(db, max_companies=max_companies)}
    except Exception as exc:
        _rollback(db)
        return _handle_actor_error("backfill_sec_fundamentals", exc, tenant_id=tenant_id)
    finally:
        db.close()


@dramatiq.actor(max_retries=1, min_backoff=60_000, time_limit=600_000)
def seed_company_fundamentals(
    tenant_id: int | None = None,
    user_id: str | None = None,
    ticker: str = "",
) -> dict[str, Any]:
    """Siembra los fundamentales de una empresa en el tenant que la acaba de
    anadir a cartera o watchlist (los FinancialFact son por tenant: sin este
    carril el tenant nuevo veia «sin hechos persistidos» hasta pulsar
    «Refrescar SEC»). Misma fuente primaria que el boton (SEC companyfacts /
    snapshot ESEF local) y mismos contratos de veracidad; si el tenant ya
    tiene hechos no hace nada; un fallo del proveedor queda contado, nunca
    inventado.
    """
    from sqlalchemy import select as _select

    from app.models import Company
    from app.services.fundamentals_seed_service import seed_company_fundamentals as _seed

    db = _session(tenant_id, user_id)
    try:
        ticker = (ticker or "").strip().upper()
        company = db.scalar(_select(Company).where(Company.ticker == ticker))
        if company is None and "." in ticker:
            company = db.scalar(_select(Company).where(Company.ticker == ticker.split(".")[0]))
        if company is None:
            return {"actor": "seed_company_fundamentals", "status": "sin_company", "ticker": ticker}
        try:
            result = _seed(db, company)
        except Exception as exc:
            _rollback(db)
            logger.exception("seed fundamentals failed for %s", ticker)
            return {
                "actor": "seed_company_fundamentals",
                "status": "error",
                "ticker": ticker,
                "detail": str(exc)[:200],
            }
        return {"actor": "seed_company_fundamentals", **result}
    finally:
        db.close()


ESEF_REINGEST_CHUNK = 25


@dramatiq.actor(max_retries=1, min_backoff=60_000, time_limit=900_000)
def ingest_class_shares_outstanding(
    tenant_id: int | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    """shares_outstanding derivado (suma de clases dei ECSO) para filers
    multi-clase (META, GOOGL, BRK.B, ASTS, V): la SEC no consolida las
    clases en companyfacts, asi que sin este carril no tienen saldo de
    acciones y el market cap derivado (#1555) no puede calcularse.

    Idempotente (mismo periodo = no reescribe). CIK del Company; sin CIK o
    sin Company queda contado, nunca inventado.
    """
    from sqlalchemy import select as _select

    from app.models import Company
    from app.services.class_filer_eps_service import (
        CLASS_SHARES_FILERS,
        backfill_class_shares_outstanding,
    )

    db = _session(tenant_id, user_id)
    try:
        results: dict[str, str] = {}
        for ticker in CLASS_SHARES_FILERS:
            company = db.scalar(_select(Company).where(Company.ticker == ticker))
            if company is None:
                results[ticker] = "no_company"
                continue
            if not company.cik:
                results[ticker] = "no_cik"
                continue
            try:
                outcome = backfill_class_shares_outstanding(db, company, cik=company.cik)
                db.commit()
                results[ticker] = "ok" if outcome.written else f"skipped:{outcome.skipped_reason}"
            except Exception:
                _rollback(db)
                logger.exception("class shares ECSO failed for %s", ticker)
                results[ticker] = "error"
        return {"actor": "ingest_class_shares_outstanding", "status": "ok", "results": results}
    finally:
        db.close()


@dramatiq.actor(max_retries=1, min_backoff=60_000, time_limit=1_800_000)
def refresh_esef_fundamentals(
    tenant_id: int | None = None,
    user_id: str | None = None,
    phase: str = "build",
    cursor: int = 0,
) -> dict[str, Any]:
    """Re-ingesta ESEF semanal (emisores IBEX reviewed, gratis).

    Fase build: reconstruye los snapshots locales desde filings.xbrl.org
    (indice ESEF de XBRL International, sin key) con la misma logica del
    script build_esef_snapshots - el snapshot anterior era de 25-sep y no
    habia re-ingesta programada, asi que los fundamentales ESEF se quedaban
    congelados. Fase ingest: refresh_from_esef por emisor reviewed que
    exista como Company, en chunks auto-encolados. Los emisores sin snapshot
    o sin Company quedan contados, nunca inventados.
    """
    from sqlalchemy import select as _select

    from app.core.config import get_settings
    from app.models import Company
    from app.services.async_bridge import run_from_any_context

    db = _session(tenant_id, user_id)
    try:
        if phase == "build":
            base = get_settings().esef_snapshot_dir
            if not base:
                return {
                    "actor": "refresh_esef_fundamentals",
                    "status": "skipped",
                    "reason": "esef_snapshot_dir_not_configured",
                }
            import sys
            from datetime import date as _date
            from pathlib import Path as _Path

            scripts_dir = str(_Path(__file__).resolve().parents[2] / "scripts")
            if scripts_dir not in sys.path:
                sys.path.insert(0, scripts_dir)
            from build_esef_snapshots import _fetch_package as fetch_esef_package
            from build_esef_snapshots import build as build_esef

            from app.services.connectors.esef import EsefClient

            manifest = run_from_any_context(
                # ES + NL en un unico manifest (ASML reviewed; cada pais
                # resuelve contra su tabla: CNMV / AFM-ESEF).
                build_esef(
                    _Path(base),
                    ["ES", "NL"],
                    _date.today().isoformat(),
                    EsefClient(),
                    package_fetcher=fetch_esef_package,
                )
            )
            refresh_esef_fundamentals.send(tenant_id, user_id, phase="ingest", cursor=0)
            return {
                "actor": "refresh_esef_fundamentals",
                "status": "ok",
                "phase": "build",
                "issuers": len(manifest.get("issuers", {})),
                "unresolved": len(manifest.get("unresolved", {})),
            }

        from app.services.esef_issuer_mapping import reviewed_tickers
        from app.services.financial_ingestion_service import (
            FinancialIngestionService,
        )

        tickers = reviewed_tickers()
        chunk = tickers[cursor : cursor + ESEF_REINGEST_CHUNK]
        service = FinancialIngestionService()
        results: dict[str, str] = {}
        for ticker in chunk:
            company = db.scalar(_select(Company).where(Company.ticker == ticker))
            if company is None:
                results[ticker] = "no_company"
                continue
            try:
                run_from_any_context(service.refresh_from_esef(db=db, company=company))
                db.commit()
                results[ticker] = "ok"
            except Exception as exc:  # snapshot ausente o hechos no importables
                _rollback(db)
                results[ticker] = f"error:{type(exc).__name__}"
        next_cursor = cursor + ESEF_REINGEST_CHUNK if cursor + ESEF_REINGEST_CHUNK < len(tickers) else None
        if next_cursor is not None:
            refresh_esef_fundamentals.send(tenant_id, user_id, phase="ingest", cursor=next_cursor)
        return {
            "actor": "refresh_esef_fundamentals",
            "status": "ok",
            "phase": "ingest",
            "cursor": cursor,
            "next_cursor": next_cursor,
            "reviewed_total": len(tickers),
            "results": results,
        }
    except Exception as exc:
        _rollback(db)
        return _handle_actor_error("refresh_esef_fundamentals", exc, tenant_id=tenant_id)
    finally:
        db.close()


SPLIT_SYNC_UNIVERSE_CHUNK = 100


def split_sync_tickers(
    db: Session, scope: str, cursor: int = 0, chunk: int = SPLIT_SYNC_UNIVERSE_CHUNK
) -> tuple[list[str], int | None]:
    """Tickers a sincronizar y cursor del siguiente chunk (None = fin).

    tracked: cartera (Position.company_id) + watchlist (WatchItem.symbol).
    universe: todas las empresas, en chunks para respetar el presupuesto de
    peticiones a Yahoo/FMP."""
    from sqlalchemy import select as _select

    from app.core.tenancy import tenant_filters
    from app.models import Company, Position, WatchItem

    if scope == "tracked":
        company_ids = list(
            db.scalars(_select(Position.company_id).where(*tenant_filters(db, Position)).distinct()).all()
        )
        tickers = (
            set(db.scalars(_select(Company.ticker).where(Company.id.in_(company_ids))).all())
            if company_ids
            else set()
        )
        tickers |= {
            str(sym).upper()
            for sym in db.scalars(
                _select(WatchItem.symbol).where(*tenant_filters(db, WatchItem)).distinct()
            ).all()
        }
        return sorted(tickers), None
    tickers = list(db.scalars(_select(Company.ticker).order_by(Company.id)).all())
    chunk_tickers = tickers[cursor : cursor + chunk]
    next_cursor = cursor + chunk if cursor + chunk < len(tickers) else None
    return chunk_tickers, next_cursor


@dramatiq.actor(max_retries=1, min_backoff=30_000)
def ingest_corporate_splits(
    tenant_id: int | None = None,
    user_id: str | None = None,
    scope: str = "tracked",
    cursor: int = 0,
) -> dict[str, Any]:
    """Splits/reverse splits declarados (Yahoo; FMP de respaldo) -> CorporateAction.

    Sin estos hechos el modelo no puede expresar los recuentos historicos de
    acciones en unidades actuales y degrada el CAGR de acciones a N/D. Se
    programa semanal: tracked (cartera+watchlist) completo y universo en
    chunks auto-encolados. La ingesta es idempotente (dedup por fila).
    """
    from app.services.async_bridge import run_from_any_context
    from app.services.split_ingestion_service import SplitIngestionService

    db = _session(tenant_id, user_id)
    try:
        tickers, next_cursor = split_sync_tickers(db, scope, cursor, chunk=SPLIT_SYNC_UNIVERSE_CHUNK)
        service = SplitIngestionService()
        results = [run_from_any_context(service.sync_company(db, ticker=ticker)) for ticker in tickers]
        if next_cursor is not None:
            ingest_corporate_splits.send(tenant_id, user_id, scope=scope, cursor=next_cursor)
        return {
            "actor": "ingest_corporate_splits",
            "status": "ok",
            "scope": scope,
            "cursor": cursor,
            "next_cursor": next_cursor,
            "companies": len(results),
            "synced": sum(1 for r in results if r["status"] == "ok"),
            "unavailable": sum(1 for r in results if r["status"] == "unavailable"),
            "unknown": sum(1 for r in results if r["status"] == "unknown_company"),
            "inserted": sum(r.get("inserted", 0) for r in results),
            "existing": sum(r.get("existing", 0) for r in results),
        }
    except Exception as exc:
        _rollback(db)
        return _handle_actor_error("ingest_corporate_splits", exc, tenant_id=tenant_id)
    finally:
        db.close()


@dramatiq.actor(max_retries=1, min_backoff=30_000)
def sync_portfolio_dividends(tenant_id: int | None = None, user_id: str | None = None) -> dict[str, Any]:
    """Ingesta diaria de dividendos declarados de las posiciones abiertas (Yahoo, FMP de respaldo)."""
    from app.services.async_bridge import run_from_any_context
    from app.services.dividend_ingestion_service import DividendIngestionService

    db = _session(tenant_id, user_id)
    try:
        result = run_from_any_context(DividendIngestionService().sync_portfolio(db))
        return {
            "actor": "sync_portfolio_dividends",
            "status": "ok",
            "companies": result["companies"],
            "synced": result["synced"],
            "unavailable": result["unavailable"],
        }
    except Exception as exc:
        _rollback(db)
        return _handle_actor_error("sync_portfolio_dividends", exc, tenant_id=tenant_id)
    finally:
        db.close()


@dramatiq.actor(max_retries=1, min_backoff=30_000, queue_name="prices")
def refresh_portfolio_prices_intraday(
    tenant_id: int | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    """F17: refresco intradia (15 min, Yahoo) solo de tickers con posiciones.

    A diferencia del refresh horario (universo completo del tenant), aqui
    solo se piden precios de las empresas con posiciones abiertas: el coste
    por ciclo es minimo y aguanta la cadencia de 15 minutos.
    """
    from sqlalchemy import select as _select

    from app.core.tenancy import tenant_filters
    from app.models import Company, Position
    from app.services.market_refresh_service import (
        MarketRefreshService,
        YahooIntradayPriceProvider,
    )

    db = _session(tenant_id, user_id)
    # La sesion se abre ANTES de tomar el lease: _session() lanza
    # ValueError si el tenant no esta activo, y esa excepcion entre la
    # toma del lease y el try se escapaba sin pasar por el finally que
    # lo libera, dejando el lease retenido hasta su TTL.
    try:
        lease = acquire_job_lease(
            f"refresh_portfolio_prices_intraday:{tenant_id}",
            ttl_seconds=900,
            redis_url=_lease_redis_url(),
        )
    except Exception:
        # Si la adquisicion lanza (Redis caido, red, ...), la sesion abierta
        # justo arriba no puede quedar sin cerrar.
        db.close()
        raise
    if lease is None:
        db.close()
        return {
            "status": "skipped",
            "actor": "refresh_portfolio_prices_intraday",
            "reason": "lease_held",
        }
    try:
        # DISTINCT sobre la entidad completa rompe en Postgres: las columnas
        # json (special_sources, special_risks, factor_tags) no tienen
        # operador de igualdad. Dedup por id en subconsulta escalar.
        company_ids = (
            _select(Position.company_id)
            .where(
                Position.company_id.is_not(None),
                *tenant_filters(db, Position),
            )
            .distinct()
            .scalar_subquery()
        )
        companies = list(
            db.scalars(_select(Company).where(Company.id.in_(company_ids)).order_by(Company.ticker)).all()
        )
        if not companies:
            return {
                "actor": "refresh_portfolio_prices_intraday",
                "status": "skipped",
                "reason": "no_positions",
            }
        result = _run(
            MarketRefreshService(price_provider=YahooIntradayPriceProvider()).refresh(db, companies=companies)
        )
        return {"actor": "refresh_portfolio_prices_intraday", **result}
    except Exception as exc:
        _rollback(db)
        return _handle_actor_error("refresh_portfolio_prices_intraday", exc, tenant_id=tenant_id)
    finally:
        release_job_lease(
            f"refresh_portfolio_prices_intraday:{tenant_id}",
            lease,
            redis_url=_lease_redis_url(),
        )
        db.close()


@dramatiq.actor(max_retries=1, min_backoff=30_000, queue_name=COMPUTED_QUEUE_NAME)
def refresh_propicks_prices(
    tenant_id: int | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    """F2: precios diarios yfinance + momentum para el top-N del ultimo run."""
    from app.services.propicks_price_service import refresh_propicks_prices as _refresh

    db = _session(tenant_id, user_id)
    # La sesion se abre ANTES de tomar el lease: _session() lanza
    # ValueError si el tenant no esta activo, y esa excepcion entre la
    # toma del lease y el try se escapaba sin pasar por el finally que
    # lo libera, dejando el lease retenido hasta su TTL.
    try:
        lease = acquire_job_lease(
            f"refresh_propicks_prices:{tenant_id}",
            ttl_seconds=3600,
            redis_url=_lease_redis_url(),
        )
    except Exception:
        # Si la adquisicion lanza (Redis caido, red, ...), la sesion abierta
        # justo arriba no puede quedar sin cerrar.
        db.close()
        raise
    if lease is None:
        db.close()
        return {
            "status": "skipped",
            "actor": "refresh_propicks_prices",
            "reason": "lease_held",
        }
    try:
        result = _refresh(db)
        return {"actor": "refresh_propicks_prices", **result}
    except Exception as exc:
        _rollback(db)
        return _handle_actor_error("refresh_propicks_prices", exc, tenant_id=tenant_id)
    finally:
        release_job_lease(f"refresh_propicks_prices:{tenant_id}", lease, redis_url=_lease_redis_url())
        db.close()


@dramatiq.actor(max_retries=1, min_backoff=60_000, time_limit=1_800_000,
              queue_name=COMPUTED_QUEUE_NAME)
def propicks_radar_scan(
    tenant_id: int | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    """Radar ProPicks+DCA: barrido acotado y resumible del universo.

    Escritor explicito de snapshots PUBLICOS de precio (nico-v1). Sin red,
    sin LLM y SIN outbox de alertas: no comparte cola con el evaluador DCA
    de watchlist. El lease es global (datos publicos, no de tenant) y el
    cursor por dia hace seguro reanudar tras un fallo o un corte de
    presupuesto: un lote incompleto nunca marca el dia como cubierto.
    """
    from app.services.propicks_radar_job import run_radar_scan

    db = _session(tenant_id, user_id)
    try:
        lease = acquire_job_lease(
            "propicks_radar_scan",
            ttl_seconds=3600,
            redis_url=_lease_redis_url(),
        )
    except Exception:
        db.close()
        raise
    if lease is None:
        db.close()
        return {
            "status": "skipped",
            "actor": "propicks_radar_scan",
            "reason": "lease_held",
        }
    try:
        result = run_radar_scan(db)
        return {"actor": "propicks_radar_scan", **result}
    except Exception as exc:
        _rollback(db)
        return _handle_actor_error("propicks_radar_scan", exc, tenant_id=tenant_id)
    finally:
        release_job_lease("propicks_radar_scan", lease, redis_url=_lease_redis_url())
        db.close()


@dramatiq.actor(max_retries=1, min_backoff=30_000)
def refresh_valuation_metrics(
    tenant_id: int | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    """Metricas de valoracion (P/B, yield TTM) de todo el universo del tenant.

    Corre tras los cierres oficiales; mismo patron de lease que
    refresh_propicks_prices. Las fuentes (yfinance/Finnhub) son las por
    defecto del servicio; en tests se inyectan fixtures.
    """
    from app.services.valuation_metrics_service import (
        refresh_valuation_metrics as _refresh,
    )

    db = _session(tenant_id, user_id)
    try:
        lease = acquire_job_lease(
            f"refresh_valuation_metrics:{tenant_id}",
            ttl_seconds=3600,
            redis_url=_lease_redis_url(),
        )
    except Exception:
        db.close()
        raise
    if lease is None:
        db.close()
        return {
            "status": "skipped",
            "actor": "refresh_valuation_metrics",
            "reason": "lease_held",
        }
    try:
        result = _refresh(db)
        return {"actor": "refresh_valuation_metrics", **result}
    except Exception as exc:
        _rollback(db)
        return _handle_actor_error("refresh_valuation_metrics", exc, tenant_id=tenant_id)
    finally:
        release_job_lease(f"refresh_valuation_metrics:{tenant_id}", lease, redis_url=_lease_redis_url())
        db.close()


@dramatiq.actor(max_retries=1, min_backoff=30_000, queue_name=COMPUTED_QUEUE_NAME)
def run_propicks_funnel(
    tenant_id: int | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    """Run diario del embudo completo (F1): seleccion vigente cada dia.

    Antes solo existia el POST manual /api/propicks/runs: la pantalla de
    Seleccion IA mostraba el ultimo run manual (podia tener semanas) y el
    refresco de precios heredaba un top-N viejo. Persiste ranks hasta 100
    para que el refresco de precios cubra tambien la banda de las joyas.
    """
    from app.services.propicks_funnel_service import execute_run

    db = _session(tenant_id, user_id)
    try:
        run = execute_run(db, top_n=100)
        # Bootstrap del track record: el congelado mensual corre el dia 1, asi
        # que un despliegue a mitad de mes dejaba propick_snapshots vacio
        # hasta el mes siguiente. freeze_monthly_snapshot es idempotente: el
        # primer congelado del mes gana y lleva su as_of real.
        from app.services.propicks_snapshot_service import freeze_monthly_snapshot

        snapshot = freeze_monthly_snapshot(db)
        return {
            "actor": "run_propicks_funnel",
            "run_id": run.id,
            "passed_count": run.passed_count,
            "top_n": run.top_n,
            "snapshot_month": snapshot.month if snapshot else None,
        }
    except Exception as exc:
        _rollback(db)
        return _handle_actor_error("run_propicks_funnel", exc, tenant_id=tenant_id)
    finally:
        db.close()


@dramatiq.actor(max_retries=1, min_backoff=30_000, queue_name=COMPUTED_QUEUE_NAME)
def freeze_propicks_snapshot(
    tenant_id: int | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    """Snapshot mensual congelado (point-in-time) del embudo ProPicks."""
    from app.services.propicks_snapshot_service import freeze_monthly_snapshot

    db = _session(tenant_id, user_id)
    try:
        row = freeze_monthly_snapshot(db)
        return {
            "actor": "freeze_propicks_snapshot",
            "month": row.month if row else None,
            "passed_count": row.passed_count if row else 0,
        }
    except Exception as exc:
        _rollback(db)
        return _handle_actor_error("freeze_propicks_snapshot", exc, tenant_id=tenant_id)
    finally:
        db.close()


@dramatiq.actor(max_retries=1, min_backoff=30_000, queue_name=COMPUTED_QUEUE_NAME)
def ingest_spy_daily(
    tenant_id: int | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    """Ingesta diaria de la serie SPY (Yahoo, gratis) en benchmark_prices."""
    from app.services.propicks_track_record_service import ingest_spy_prices

    db = _session(tenant_id, user_id)
    try:
        result = ingest_spy_prices(db)
        return {"actor": "ingest_spy_daily", **result}
    except Exception as exc:
        _rollback(db)
        return _handle_actor_error("ingest_spy_daily", exc, tenant_id=tenant_id)
    finally:
        db.close()


def _official_close_session_key() -> str:
    """Last completed US session, never today's still-open session."""
    from datetime import UTC, datetime

    from app.services.market_close_sync import last_completed_us_session

    return last_completed_us_session(datetime.now(UTC)).isoformat()


@dramatiq.actor(max_retries=1, min_backoff=30_000, time_limit=3_600_000, queue_name="official-closes")
def sync_official_closes(
    tenant_id: int | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    """One global download; legacy per-tenant default messages stay harmless.

    Strict distributed lock: Redis failure retries instead of local fallback.
    Success survives lock release, so queued legacy duplicates skip too.
    """
    from app.services.market_close_sync import MIN_TARGET_COVERAGE
    from app.services.market_close_sync import sync_official_closes as _sync

    client = _redis_client()
    if client is None:
        raise RuntimeError("Redis required for global official closes")
    lock = "cavaai:job-lease:sync_official_closes:global"
    session_key = _official_close_session_key()
    # Preserve existing markers; an operator backs up and clears any known
    # false positive explicitly after this fix is deployed.
    done = "cavaai:official-closes:done:" + session_key
    attempts = "cavaai:official-closes:attempts:" + session_key
    token = uuid.uuid4().hex
    acquired = False
    db = None
    try:
        acquired = bool(client.set(lock, token, nx=True, ex=3900))
        if not acquired:
            return {"status": "skipped", "reason": "lease_held"}
        if client.get(done):
            return {"status": "skipped", "reason": "session_already_synced"}
        # Three full downloads per six-hour window, shared across tenants.
        # Old capped counters start a cooldown without downloading immediately.
        # A partial session can recover later, but queued duplicates cannot
        # turn a holiday/provider failure into an unbounded bulk-download loop.
        import time

        cooldown_key = "cavaai:official-closes:cooldown-start:" + session_key
        now_seconds = int(time.time())
        tried = int(client.get(attempts) or 0)
        if tried >= 3:
            started = client.get(cooldown_key)
            if started is None:
                client.set(cooldown_key, str(now_seconds), ex=7 * 86400)
                started = str(now_seconds)
            remaining = max(0, 6 * 3600 - (now_seconds - int(started)))
            if remaining:
                return {
                    "status": "skipped",
                    "reason": "session_attempt_cooldown",
                    "attempts": tried,
                    "target_date": session_key,
                    "retry_after_seconds": remaining,
                }
            tried = 0
        client.set(attempts, str(tried + 1), ex=7 * 86400)
        if tried + 1 >= 3:
            client.set(cooldown_key, str(now_seconds), ex=7 * 86400)
        db = _session(tenant_id, user_id)
        result = _sync(db)
        logger.info(
            "official_closes_result session=%s status=%s target_covered=%s "
            "with_symbol=%s target_coverage=%s failed_chunks=%s target_missing=%s",
            session_key,
            result.get("status"),
            result.get("target_covered"),
            result.get("with_symbol"),
            result.get("target_coverage"),
            result.get("failed_chunks"),
            result.get("target_missing"),
        )
        if (
            result.get("status") == "ok"
            and result.get("target_coverage", 0) >= MIN_TARGET_COVERAGE
            and result.get("target_date") == session_key
        ):
            client.set(done, "1", ex=7 * 86400)
        return {"actor": "sync_official_closes", **result}
    except Exception:
        if db is not None:
            _rollback(db)
        raise
    finally:
        if db is not None:
            db.close()
        if acquired:
            client.eval(_RELEASE_LEASE_LUA, 1, lock, token)
        client.close()


@dramatiq.actor(max_retries=1, min_backoff=30_000, time_limit=1_800_000)
def evaluate_dca_signals(
    tenant_id: int | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    """Senales DCA (1X-4X + recortes) de watchlist + cartera y avisos por cambio de nivel.

    La evaluacion (guardar el nivel de cada ticker para las insignias de la
    watchlist) depende solo de DCA_EVALUATION_ENABLED. Los avisos los filtra el
    servicio con DCA_ALERTS_ENABLED: con los avisos apagados se sigue evaluando
    y guardando el nivel, pero no sale ningun aviso ni correo.
    """
    from app.core.config import get_settings
    from app.services.dca_signal_service import evaluate_watchlist

    if not get_settings().dca_evaluation_enabled:
        return {"status": "skipped", "actor": "evaluate_dca_signals", "reason": "disabled"}
    db = _session(tenant_id, user_id)
    try:
        lease = acquire_job_lease(
            f"evaluate_dca_signals:{tenant_id}",
            ttl_seconds=1800,
            redis_url=_lease_redis_url(),
        )
    except Exception:
        db.close()
        raise
    if lease is None:
        db.close()
        return {"status": "skipped", "actor": "evaluate_dca_signals", "reason": "lease_held"}
    from app.services import dca_run_log

    run = dca_run_log.start_run(db, "scheduler")
    try:
        summary = evaluate_watchlist(db)
        from app.services.plan_proactivity import review_savings_plan

        summary["savings_plan_review"] = review_savings_plan(db)
        db.commit()
        dca_run_log.finish_run(db, run, summary=summary)
        return {"actor": "evaluate_dca_signals", "status": "ok", **summary}
    except Exception as exc:
        _rollback(db)
        dca_run_log.finish_run(db, run, error=f"{type(exc).__name__}: {exc}")
        return _handle_actor_error("evaluate_dca_signals", exc, tenant_id=tenant_id)
    finally:
        release_job_lease(f"evaluate_dca_signals:{tenant_id}", lease, redis_url=_lease_redis_url())
        db.close()


@dramatiq.actor(max_retries=1, min_backoff=30_000, time_limit=600_000)
def refresh_earnings_calendar(
    tenant_id: int | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    """Fechas de resultados de cartera + watchlist (Yahoo calendarEvents + NASDAQ)."""
    from app.services.earnings_dates_service import refresh_earnings_dates

    db = _session(tenant_id, user_id)
    try:
        return {"actor": "refresh_earnings_calendar", **refresh_earnings_dates(db)}
    except Exception as exc:
        _rollback(db)
        return _handle_actor_error("refresh_earnings_calendar", exc, tenant_id=tenant_id)
    finally:
        db.close()


@dramatiq.actor(max_retries=1, min_backoff=30_000, time_limit=300_000)
def backfill_company_price_history(
    company_id: int,
    tenant_id: int | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    """Backfill de ~1 ano de MarketPrice para una compania recien en cartera.

    market_prices solo acumula hacia adelante (sync_official_closes escribe
    la ultima semana cada dia); sin este backfill una posicion nueva no tiene
    pasado y las metricas de cartera miden dias con pinta de anos. Una
    compania por tarea y una unica llamada a la fuente: ritmo amable.
    """
    from app.models.entities import Company
    from app.services.market_close_sync import backfill_company_history

    db = _session(tenant_id, user_id)
    try:
        company = db.get(Company, company_id)
        if company is None:
            return {"status": "skipped", "reason": "company_not_found"}
        return {
            "actor": "backfill_company_price_history",
            **backfill_company_history(db, company),
        }
    except Exception as exc:
        _rollback(db)
        return _handle_actor_error("backfill_company_price_history", exc, company_id=company_id)
    finally:
        db.close()


@dramatiq.actor(max_retries=2, min_backoff=15_000, dedup_enqueue_ttl=DEDUP_ENQUEUE_TTL_SECONDS)
def refresh_sec_filings(
    tenant_id: int | None = None,
    user_id: str | None = None,
    ticker: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    actor_name = "refresh_sec_filings"
    try:
        from app.services.feed_ingestion_service import FeedIngestionService

        db = _session(tenant_id, user_id)
        try:
            service = FeedIngestionService()
            processed = ingested = queued_documents = 0
            skipped_documents = 0
            errors: list[dict] = []
            emitted: set[str] = set()
            companies = _companies(db, ticker)
            for company in companies:
                if not company.cik:
                    continue
                try:
                    result = _run(
                        service.poll_sec(
                            company.cik,
                            ticker=company.ticker,
                            limit=limit,
                        )
                    )
                    if result.errors:
                        errors.extend(
                            {"ticker": company.ticker, "source": "sec", "message": error}
                            for error in result.errors
                        )
                    ingestion = service.ingest_news_result(
                        db,
                        result,
                        ticker=company.ticker,
                    )
                    if result.status != "error":
                        processed += 1
                    ingested += int(ingestion.get("created", 0))
                    if settings.sec_document_jobs_enabled:
                        for item in result.items:
                            if not item.url:
                                continue
                            fingerprint = _emit_fingerprint("process_document", company.ticker, item.url)
                            if fingerprint in emitted:
                                continue
                            emitted.add(fingerprint)
                            process_document.send(
                                company.ticker,
                                item.title,
                                item.url,
                                "SEC",
                                item.published_at.isoformat() if item.published_at else None,
                                tenant_id,
                                user_id,
                                filing_metadata=getattr(item, "metadata", None),
                            )
                            queued_documents += 1
                    else:
                        # F359: la SEC bloquea la IP de OCI (403 permanente),
                        # asi que los jobs de documento SEC siempre fallan.
                        # No se emiten; la metadata sigue entrando por el
                        # mirror HF. El contador deja visible la supresion.
                        skipped_documents += sum(1 for item in result.items if item.url)
                except Exception as exc:
                    _rollback(db)
                    errors.append(
                        {
                            "ticker": company.ticker,
                            "source": "sec",
                            "type": type(exc).__name__,
                            "message": str(exc),
                        }
                    )
            return {
                "status": _batch_status(processed, errors),
                "actor": actor_name,
                "companies_processed": processed,
                "news_ingested": ingested,
                "documents_queued": queued_documents,
                "documents_skipped_sec_blocked": skipped_documents,
                "errors": errors,
            }
        finally:
            db.close()
    except Exception as exc:
        return _handle_actor_error(
            actor_name, exc, tenant_id=tenant_id, user_id=user_id, ticker=ticker, limit=limit
        )


@dramatiq.actor(max_retries=2, min_backoff=15_000, dedup_enqueue_ttl=DEDUP_ENQUEUE_TTL_SECONDS)
@_coalesce_on_success("refresh_ir_pages", 50 * 60, ("tenant_id", "ticker"))
def refresh_ir_pages(
    tenant_id: int | None = None,
    user_id: str | None = None,
    ticker: str | None = None,
) -> dict[str, Any]:
    actor_name = "refresh_ir_pages"
    try:
        from app.services.feed_ingestion_service import FeedIngestionService

        db = _session(tenant_id, user_id)
        try:
            service = FeedIngestionService()
            processed = ingested = queued_documents = 0
            errors: list[dict] = []
            emitted: set[str] = set()
            for company in _companies(db, ticker):
                if not company.ir_url:
                    continue
                try:
                    result = _run(service.poll_ir(company.ir_url, ticker=company.ticker))
                    if result.errors:
                        errors.extend(
                            {"ticker": company.ticker, "source": "ir", "message": error}
                            for error in result.errors
                        )
                    ingestion = service.ingest_news_result(
                        db,
                        result,
                        ticker=company.ticker,
                    )
                    if result.status != "error":
                        processed += 1
                    ingested += int(ingestion.get("created", 0))
                    for item in result.items:
                        if not item.url:
                            continue
                        fingerprint = _emit_fingerprint("process_document", company.ticker, item.url)
                        if fingerprint in emitted:
                            continue
                        emitted.add(fingerprint)
                        process_document.send(
                            company.ticker,
                            item.title,
                            item.url,
                            "IR",
                            item.published_at.isoformat() if item.published_at else None,
                            tenant_id,
                            user_id,
                        )
                        queued_documents += 1
                except Exception as exc:
                    _rollback(db)
                    errors.append(
                        {
                            "ticker": company.ticker,
                            "source": "ir",
                            "type": type(exc).__name__,
                            "message": str(exc),
                        }
                    )
            return {
                "status": _batch_status(processed, errors),
                "actor": actor_name,
                "companies_processed": processed,
                "news_ingested": ingested,
                "documents_queued": queued_documents,
                "errors": errors,
            }
        finally:
            db.close()
    except Exception as exc:
        return _handle_actor_error(actor_name, exc, tenant_id=tenant_id, user_id=user_id, ticker=ticker)


# Presupuesto total de la corrida por debajo del time_limit de dramatiq
# (600 s): los feeds se sondean en serie con hasta 20 s por feed y la ingesta
# de cada lote suma; sin tope, una corrida lenta moria por TimeLimitExceeded
# (prod: tenant 10, 601 s) y el tick siguiente repetia el barrido entero.
# Al agotarse, los feeds restantes quedan diferidos al siguiente tick y el
# resultado lo declara ("partial" + time_budget_exceeded), nada se silencia.
_RSS_TIME_BUDGET_SECONDS = 480.0


@dramatiq.actor(max_retries=2, min_backoff=15_000, dedup_enqueue_ttl=DEDUP_ENQUEUE_TTL_SECONDS)
@_coalesce_on_success("refresh_rss_feeds", 12 * 60, ("tenant_id", "feed_url", "ticker"))
def refresh_rss_feeds(
    tenant_id: int | None = None,
    user_id: str | None = None,
    feed_url: str | None = None,
    ticker: str | None = None,
) -> dict[str, Any]:
    actor_name = "refresh_rss_feeds"
    try:
        from app.services.feed_ingestion_service import (
            FeedIngestionService,
            RSSFeed,
            all_rss_feeds,
        )

        # Carriles RSS con detección de empresa PERMITIDA. Vacío a propósito
        # (veracidad fail-closed, auditoría #3114): TODO carril (lane no
        # None) nace cerrado — sus titulares nunca se enlazan a una Company
        # ni disparan alertas de noticias seguidas aunque nombren una
        # empresa — y abrir la detección exige declarar el carril aquí.
        lane_feeds_company_detection_allowed: frozenset[str] = frozenset()

        feeds = [RSSFeed(feed_url, ticker.upper() if ticker else None)] if feed_url else all_rss_feeds()
        if not feeds:
            return {
                "status": "skipped",
                "actor": actor_name,
                "reason": "RSS_FEEDS is empty",
                "feeds_processed": 0,
            }

        db = _session(tenant_id, user_id)
        try:
            from sqlalchemy import select as _select

            from app.models.entities import ConnectorState

            # Orden por ultima sondeada (la mas antigua primero), persistida
            # en ConnectorState: sin cursor, cada tick empezaba por el feed 0
            # y bajo lentitud sostenida los ultimos feeds no corrian nunca
            # (hallazgo del piloto en #3029). El estado se commitea ANTES de
            # sondear: si el worker muere por time_limit, el tick siguiente
            # retoma por donde quedo. Los feeds sin estado van primeros.
            tenant_clause = (
                ConnectorState.tenant_id.is_(tenant_id)
                if tenant_id is None
                else ConnectorState.tenant_id == tenant_id
            )
            states = db.scalars(
                _select(ConnectorState).where(
                    ConnectorState.connector == "rss",
                    ConnectorState.feed_url.is_not(None),
                    tenant_clause,
                )
            ).all()
            state_by_url = {state.feed_url: state for state in states}
            _never = datetime.min.replace(tzinfo=UTC)

            def _last_polled(feed) -> datetime:
                state = state_by_url.get(feed.url)
                ts = state.last_started_at if state is not None else None
                if ts is None:
                    return _never
                return ts if ts.tzinfo is not None else ts.replace(tzinfo=UTC)

            feeds = sorted(feeds, key=_last_polled)  # sorted es estable: empates conservan el orden de config

            service = FeedIngestionService()
            processed = ingested = 0
            errors: list[dict] = []
            started_at = time.monotonic()
            for index, feed in enumerate(feeds):
                if time.monotonic() - started_at >= _RSS_TIME_BUDGET_SECONDS:
                    errors.append(
                        {
                            "url": None,
                            "source": "rss",
                            "type": "time_budget_exceeded",
                            "message": (
                                f"presupuesto de {_RSS_TIME_BUDGET_SECONDS:.0f}s "
                                f"agotado; {len(feeds) - index} feeds diferidos "
                                "al siguiente tick (retoman primero por orden "
                                "de ultima sondeada)"
                            ),
                        }
                    )
                    break
                state = state_by_url.get(feed.url)
                if state is None:
                    state = ConnectorState(tenant_id=tenant_id, connector="rss", feed_url=feed.url)
                    db.add(state)
                    state_by_url[feed.url] = state
                state.last_started_at = datetime.now(UTC)
                # Commit antes de sondear: si el worker muere a mitad, el tick
                # siguiente no vuelve a empezar por este feed.
                db.commit()
                try:
                    result = _run(service.poll_rss(feed.url, ticker=feed.ticker, source_label=feed.label))
                    if result.errors:
                        errors.extend(
                            {"url": feed.url, "source": "rss", "message": error} for error in result.errors
                        )
                    ingestion = service.ingest_news_result(
                        db,
                        result,
                        ticker=feed.ticker,
                        news_lane=feed.lane,
                        # Mismo presupuesto que abre feeds nuevos: agotado, la
                        # ingesta sigue pero se omite el enriquecimiento Jev/LLM.
                        llm_deadline=started_at + _RSS_TIME_BUDGET_SECONDS,
                        # Cerrado por defecto: solo feeds sin carril (o en el
                        # conjunto explícito de arriba) detectan empresa. Un
                        # titular de carril que nombra una empresa NO la
                        # enlaza (test: BEA con «Apple» queda company_id NULL).
                        detect_company=(
                            feed.lane is None or feed.lane in lane_feeds_company_detection_allowed
                        ),
                    )
                    if result.status != "error":
                        processed += 1
                        state.last_success_at = datetime.now(UTC)
                        state.consecutive_errors = 0
                    ingested += int(ingestion.get("created", 0))
                except Exception as exc:
                    _rollback(db)
                    # Tras el rollback el estado queda expirado: reanexarlo
                    # para registrar el error sin perder el last_started_at
                    # ya commiteado antes de sondear.
                    db.add(state)
                    state.consecutive_errors = (state.consecutive_errors or 0) + 1
                    state.last_error = redact_secrets(str(exc))[:500]
                    db.commit()
                    errors.append(
                        {
                            "url": feed.url,
                            "source": "rss",
                            "type": type(exc).__name__,
                            "message": str(exc),
                        }
                    )
            return {
                "status": _batch_status(processed, errors),
                "actor": actor_name,
                "feeds_processed": processed,
                "news_ingested": ingested,
                "errors": errors,
            }
        finally:
            db.close()
    except Exception as exc:
        return _handle_actor_error(
            actor_name,
            exc,
            tenant_id=tenant_id,
            user_id=user_id,
            feed_url=feed_url,
            ticker=ticker,
        )


@dramatiq.actor(max_retries=1, min_backoff=30_000, queue_name=ALERT_QUEUE_NAME)
def analyze_tracked_news_alert(
    alert_id: int, *, tenant_id: int | None = None, user_id: str | None = None
) -> dict[str, Any]:
    """Idempotent attributed-headline baseline, never a verified claim."""
    from app.services.alert_analysis_service import analyze_alert

    db = _session(tenant_id, user_id)
    lease_key = f"analyze_tracked_news_alert:{tenant_id}:{alert_id}"
    try:
        lease = acquire_job_lease(lease_key, ttl_seconds=300, redis_url=_lease_redis_url())
    except Exception:
        db.close()
        raise
    if lease is None:
        db.close()
        return {"status": "skipped", "reason": "lease_held", "alert_id": alert_id}
    try:
        return analyze_alert(db, alert_id)
    except Exception as exc:
        _rollback(db)
        return _handle_actor_error("analyze_tracked_news_alert", exc, alert_id=alert_id)
    finally:
        release_job_lease(lease_key, lease, redis_url=_lease_redis_url())
        db.close()


@dramatiq.actor(max_retries=1, min_backoff=30_000, queue_name=ALERT_QUEUE_NAME)
def dispatch_tracked_news_alerts(tenant_id: int | None = None, user_id: str | None = None) -> dict[str, Any]:
    """Evaluate persisted, cited news for one tenant; no upstream request."""
    from app.services.asts_spacex_signal import evaluate as evaluate_asts_signal
    from app.services.tracked_news_alerts import evaluate

    db = _session(tenant_id, user_id)
    try:
        lease = acquire_job_lease(
            f"dispatch_tracked_news_alerts:{tenant_id}",
            ttl_seconds=900,
            redis_url=_lease_redis_url(),
        )
    except Exception:
        db.close()
        raise
    if lease is None:
        db.close()
        return {"actor": "dispatch_tracked_news_alerts", "status": "skipped", "reason": "lease_held"}
    try:
        result = evaluate(db)
        result["asts_spacex_signal"] = evaluate_asts_signal(db)
        # A broker outage between alert commit and send leaves a pending row.
        # Requeue a bounded backlog on the next normal dispatch cycle.
        from sqlalchemy import select

        from app.models import AlertAnalysis
        from app.services.alert_analysis_service import VERSION

        pending = db.scalars(
            select(AlertAnalysis)
            .where(
                AlertAnalysis.tenant_id == tenant_id,
                AlertAnalysis.version == VERSION,
                AlertAnalysis.status == "pending",
            )
            .order_by(AlertAnalysis.id)
            .limit(20)
        ).all()
        enqueued = 0
        deduped = 0
        for row in pending:
            # Sin marca, cada ciclo re-encolaba las mismas filas pending bajo
            # starvation (29-oct: 5.534 mensajes para ~20 analisis reales).
            if not _claim_analysis_enqueue(tenant_id, row.alert_id):
                deduped += 1
                continue
            try:
                analyze_tracked_news_alert.send(row.alert_id, tenant_id=tenant_id, user_id=user_id)
            except Exception:
                _clear_analysis_enqueue_mark(tenant_id, row.alert_id)
                raise
            enqueued += 1
        return {
            "actor": "dispatch_tracked_news_alerts",
            **result,
            "analysis_enqueued": enqueued,
            "analysis_deduped": deduped,
        }
    except Exception as exc:
        _rollback(db)
        return _handle_actor_error("dispatch_tracked_news_alerts", exc, tenant_id=tenant_id)
    finally:
        release_job_lease(
            f"dispatch_tracked_news_alerts:{tenant_id}",
            lease,
            redis_url=_lease_redis_url(),
        )
        db.close()


def _gdelt_company_query(company) -> str:
    """Consulta GDELT por empresa.

    La API DOC 2.0 exige que los terminos con OR vayan entre parentesis;
    sin ellos rechaza la peticion ("Queries containing OR'd terms must be
    surrounded by ().") y el carril de noticias de empresa ingiere cero
    eventos (fallo silencioso: el error viaja en ConnectorResult.errors).
    """
    return f'("{company.name}" OR {company.ticker})'


@dramatiq.actor(max_retries=6, min_backoff=60_000, max_backoff=900_000, queue_name=GDELT_QUEUE_NAME)
@_coalesce_on_success(
    "refresh_news",
    lambda scope="all", **_: 25 * 60 if scope == "tracked" else 5 * 3600,
    ("tenant_id", "ticker", "scope"),
)
def refresh_news(
    tenant_id: int | None = None,
    user_id: str | None = None,
    ticker: str | None = None,
    max_records: int = 25,
    scope: str = "all",
) -> dict[str, Any]:
    actor_name = "refresh_news"
    try:
        from app.services.feed_ingestion_service import FeedIngestionService

        db = _session(tenant_id, user_id)
        try:
            service = FeedIngestionService()
            processed = ingested = 0
            errors: list[dict] = []
            companies = (
                _companies(db, ticker)
                if ticker
                else (_tracked_companies(db) if scope == "tracked" else _companies(db))
            )
            # El middleware TimeLimit mata el actor a los 10 min (TimeLimitExceeded
            # no es Exception): con 429 y pacing de ~5 s el barrido alfabetico
            # moria antes de llegar a ASTS. Prioritarias primero y corte limpio
            # con resultado parcial bajo el limite.
            from app.services.ticker_news_lane import (
                PRIORITY_TICKERS,
                Deadline,
                finalize_status,
                ingest_in_chunks,
            )

            companies = sorted(companies, key=lambda c: (c.ticker.upper() not in PRIORITY_TICKERS, c.ticker))
            # Cierra la transaccion de lectura de _session/_companies ANTES del
            # bucle de red (GDELT tarda segundos por empresa): la lista ya esta
            # materializada y expire_on_commit=False mantiene los atributos.
            db.commit()
            # 300 s: el ultimo query puede entrar con 429+reintentos y 30 items;
            # el margen real hasta los 600 s del TimeLimit es de 5 min.
            deadline = Deadline(300)
            for company in companies:
                if deadline.expired():
                    break
                try:
                    query = _gdelt_company_query(company)
                    result = _run(
                        service.poll_gdelt(
                            query,
                            ticker=company.ticker,
                            max_records=max_records,
                        )
                    )
                    if result.errors:
                        errors.extend(
                            {"ticker": company.ticker, "source": "gdelt", "message": error}
                            for error in result.errors
                        )
                    ingested += ingest_in_chunks(
                        lambda part, _c=company: service.ingest_news_result(db, part, ticker=_c.ticker),
                        result,
                        deadline,
                    )
                    if result.status != "error":
                        processed += 1
                except Exception as exc:
                    _rollback(db)
                    from app.services.connectors.gdelt import GdeltRateLimited

                    if isinstance(exc, GdeltRateLimited):
                        # Ventana cerrada: se para el barrido aqui (no se
                        # quema cuota en las empresas restantes) y el lote se
                        # reencola tras el Retry-After del servidor.
                        _raise_gdelt_retry(exc)
                    errors.append(
                        {
                            "ticker": company.ticker,
                            "source": "gdelt",
                            "type": type(exc).__name__,
                            "message": str(exc),
                        }
                    )
                deadline.expired()  # post-unidad: la ultima empresa tambien cuenta
            return {
                "status": finalize_status(_batch_status(processed, errors), deadline.truncated),
                "actor": actor_name,
                "scope": scope,
                "companies_processed": processed,
                "news_ingested": ingested,
                "truncated": deadline.truncated,
                "errors": errors,
            }
        finally:
            db.close()
    except dramatiq.Retry:
        raise
    except Exception as exc:
        return _handle_actor_error(
            actor_name,
            exc,
            tenant_id=tenant_id,
            user_id=user_id,
            ticker=ticker,
            max_records=max_records,
        )


@dramatiq.actor(max_retries=1, min_backoff=15_000, time_limit=2 * 3600 * 1000, dedup_enqueue_ttl=DEDUP_ENQUEUE_TTL_SECONDS)
@_coalesce_on_success(
    "refresh_ticker_news",
    lambda scope="tracked", **_: 20 * 60 if scope == "tracked" else 5 * 3600,
    ("tenant_id", "ticker", "scope"),
)
def refresh_ticker_news(
    tenant_id: int | None = None,
    user_id: str | None = None,
    ticker: str | None = None,
    scope: str = "tracked",
) -> dict[str, Any]:
    """Noticias por ticker desde Yahoo Finance RSS y Google News RSS (sin GDELT).

    tracked: cartera + watchlist + ASTS/SPCX, Yahoo y Google. all: universo,
    solo Yahoo y solo cotizadas en EEUU. Pacing 1,5 s entre peticiones.
    """
    actor_name = "refresh_ticker_news"
    try:
        from app.services.feed_ingestion_service import (
            FeedIngestionService,
        )
        from app.services.news_service import _ticker_evidence_level
        from app.services.ticker_news_lane import (
            PRIORITY_TICKERS,
            Deadline,
            finalize_status,
            google_feed_url,
            is_us_listed,
            label_google,
            label_yahoo,
            sweep,
            yahoo_feed_url,
        )

        db = _session(tenant_id, user_id)
        try:
            service = FeedIngestionService()
            if ticker:
                companies = _companies(db, ticker)
            elif scope == "tracked":
                found = {company.id: company for company in _tracked_companies(db)}
                for company in _companies(db):
                    if company.ticker.upper() in PRIORITY_TICKERS:
                        found[company.id] = company
                # Prioritarias primero: un fallo posterior no las deja sin barrer.
                companies = sorted(
                    found.values(),
                    key=lambda c: (c.ticker.upper() not in PRIORITY_TICKERS, c.ticker),
                )
            else:
                companies = [c for c in _companies(db) if is_us_listed(c)]
            deadline = Deadline(6600)  # margen de 10 min bajo el time_limit de 2 h

            def _lanes(company):
                lanes = [("yahoo", yahoo_feed_url(company.ticker))] if is_us_listed(company) else []
                if scope == "tracked" or ticker:
                    lanes.append(("google-en", google_feed_url(company, lang="en")))
                    if company.ticker.upper() in PRIORITY_TICKERS:
                        lanes.append(("google-es", google_feed_url(company, lang="es")))
                return lanes

            def _fetch(company, lane, url):
                result = _run(service.poll_rss(url, ticker=company.ticker, max_items=30))
                if lane == "yahoo":
                    return label_yahoo(result, company, _ticker_evidence_level)
                return label_google(result, company, _ticker_evidence_level)

            def _ingest(company, part):
                return service.ingest_news_result(
                    db,
                    part,
                    ticker=company.ticker,
                    news_lane=part.metadata.get("news_lane"),
                )

            outcome = sweep(
                companies,
                _lanes,
                _fetch,
                _ingest,
                deadline,
                pause=lambda: time.sleep(1.5),
                on_error=lambda: _rollback(db),
            )
            processed, ingested, errors = (
                outcome["processed"],
                outcome["ingested"],
                outcome["errors"],
            )
            return {
                "status": finalize_status(_batch_status(processed, errors), deadline.truncated),
                "actor": actor_name,
                "scope": scope,
                "feeds_processed": processed,
                "news_ingested": ingested,
                "truncated": deadline.truncated,
                "errors": errors,
            }
        finally:
            db.close()
    except Exception as exc:
        return _handle_actor_error(actor_name, exc, tenant_id=tenant_id, user_id=user_id, ticker=ticker)


@dramatiq.actor(max_retries=2, min_backoff=15_000, queue_name=ALERT_QUEUE_NAME)
def reconcile_alert_analyses(tenant_id: int | None = None, user_id: str | None = None) -> dict[str, Any]:
    """Queue AlertAnalysis rows for tracked_news alerts that never got one.

    Independent of NewsEvent eligibility: the evaluate() repair only runs
    while the event passes its filter, so a lost row whose event aged out
    would never be recovered. queue_analysis stays the honest gate.
    """
    actor_name = "reconcile_alert_analyses"
    from app.services.alert_analysis_service import reconcile_missing_analyses

    db = _session(tenant_id, user_id)
    try:
        lease = acquire_job_lease(
            f"reconcile_alert_analyses:{tenant_id}",
            ttl_seconds=900,
            redis_url=_lease_redis_url(),
        )
    except Exception:
        db.close()
        raise
    if lease is None:
        db.close()
        return {"actor": actor_name, "status": "skipped", "reason": "lease_held"}
    try:
        stats = reconcile_missing_analyses(db)
        return {"actor": actor_name, "status": "ok", **stats}
    except Exception as exc:
        _rollback(db)
        return _handle_actor_error(actor_name, exc, tenant_id=tenant_id)
    finally:
        release_job_lease(
            f"reconcile_alert_analyses:{tenant_id}",
            lease,
            redis_url=_lease_redis_url(),
        )
        db.close()


# --- Carril macro: dedupe entre tenants y disyuntor ante GDELT caído ---
#
# Medido en prod (30-oct-2026): GDELT inalcanzable desde la VM (HTTP 000 y
# 429 sostenido), 0 eventos macro en 72h y cada ciclo horario quemaba 13
# timeouts por tenant. Dos frenos:
# - Cache Redis por tema (TTL < 1h): el primer tenant que sondea un tema
#   cachea el lote; el resto de tenants ingiere desde cache sin red. N->1
#   llamadas GDELT por ciclo. Fail-open: sin Redis, comportamiento previo.
# - Disyuntor: 2 fallos de transporte seguidos (no-429: timeout, DNS,
#   conexión) abortan el ciclo en vez de quemar las 13 consultas contra una
#   fuente caída. El 429 tipado sigue su vía (reencolar tras la ventana).
_GDELT_MACRO_CACHE_TTL_SECONDS = 55 * 60
_GDELT_MACRO_CIRCUIT_THRESHOLD = 2


def _gdelt_macro_cache_key(theme: str) -> str:
    return f"gdelt:macro:last:{theme}"


def _gdelt_macro_cache_get(client, theme: str):
    """Lote cacheado de un tema, o None (sin Redis, miss o payload corrupto)."""
    if client is None:
        return None
    try:
        raw = client.get(_gdelt_macro_cache_key(theme))
    except Exception:  # noqa: BLE001 — cache fail-open
        return None
    if not raw:
        return None
    try:
        import json as _json

        from app.services.connectors.base import ConnectorItem, ConnectorResult

        payload = _json.loads(raw)
        items = [
            ConnectorItem(
                source=item.get("source", "gdelt"),
                title=item.get("title", ""),
                url=item.get("url"),
                summary=item.get("summary", ""),
                published_at=(
                    datetime.fromisoformat(item["published_at"]) if item.get("published_at") else None
                ),
                ticker=item.get("ticker"),
                item_type=item.get("item_type", "news"),
                external_id=item.get("external_id"),
                headline_from_source=item.get("headline_from_source", True),
                metadata=item.get("metadata") or {},
            )
            for item in payload.get("items", [])
        ]
        return ConnectorResult(
            source=payload.get("source", "gdelt"),
            items=items,
            errors=list(payload.get("errors", [])),
            metadata={**(payload.get("metadata") or {}), "macro_cache": "hit"},
        )
    except Exception:  # noqa: BLE001 — payload corrupto: como un miss
        return None


def _gdelt_macro_cache_set(client, theme: str, result) -> None:
    """Cachea el lote (también vacío: una respuesta fresca sin items)."""
    if client is None:
        return
    try:
        import json as _json

        payload = {
            "source": result.source,
            "errors": list(result.errors),
            "metadata": dict(result.metadata or {}),
            "items": [
                {**item.as_dict(), "headline_from_source": item.headline_from_source} for item in result.items
            ],
        }
        # redis-py depreco setex (DeprecationWarning desde 2.6.12): set con ex=ttl
        client.set(
            _gdelt_macro_cache_key(theme),
            _json.dumps(payload, ensure_ascii=False),
            ex=_GDELT_MACRO_CACHE_TTL_SECONDS,
        )
    except Exception:  # noqa: BLE001 — cache fail-open
        return


@dramatiq.actor(max_retries=6, min_backoff=60_000, max_backoff=900_000, queue_name=GDELT_QUEUE_NAME)
@_coalesce_on_success("refresh_macro_news", 50 * 60, ("tenant_id",))
def refresh_macro_news(
    tenant_id: int | None = None,
    user_id: str | None = None,
    max_records: int = 15,
) -> dict[str, Any]:
    """Carril macro: consultas GDELT por tema, sin ticker, news_lane=macro.

    Los eventos quedan con company_id NULL (sin detección de empresa por
    texto) y metadata news_lane/macro_theme en la transacción de creación.
    No alimentan alertas tracked (sin empresa, fail-closed) ni mueven tesis;
    alimentan el feed macro y el análisis de segundo orden.
    """
    actor_name = "refresh_macro_news"
    try:
        from app.services.feed_ingestion_service import FeedIngestionService
        from app.services.macro_news import MACRO_NEWS_LANE, iter_macro_queries

        db = _session(tenant_id, user_id)
        try:
            lease = acquire_job_lease(
                f"refresh_macro_news:{tenant_id}",
                ttl_seconds=1800,
                redis_url=_lease_redis_url(),
            )
        except Exception:
            db.close()
            raise
        if lease is None:
            db.close()
            return {"actor": actor_name, "status": "skipped", "reason": "lease_held"}
        try:
            service = FeedIngestionService()
            processed = ingested = 0
            errors: list[dict] = []
            consecutive_failures = 0
            try:
                cache_client = _redis_client()
            except Exception:  # noqa: BLE001 — cache fail-open
                cache_client = None
            for theme, query in iter_macro_queries():
                result = _gdelt_macro_cache_get(cache_client, theme)
                if result is None:
                    try:
                        result = _run(service.poll_gdelt(query, ticker=None, max_records=max_records))
                    except Exception as exc:
                        _rollback(db)
                        from app.services.connectors.gdelt import GdeltRateLimited

                        if isinstance(exc, GdeltRateLimited):
                            _raise_gdelt_retry(exc)
                        consecutive_failures += 1
                        errors.append(
                            {
                                "theme": theme,
                                "source": "gdelt",
                                "type": type(exc).__name__,
                                "message": str(exc),
                            }
                        )
                        if consecutive_failures >= _GDELT_MACRO_CIRCUIT_THRESHOLD:
                            errors.append(
                                {
                                    "theme": None,
                                    "source": "gdelt",
                                    "type": "circuit_open",
                                    "message": (
                                        "GDELT no responde: ciclo abortado tras "
                                        f"{consecutive_failures} fallos seguidos; "
                                        "los temas restantes quedan para el próximo tick"
                                    ),
                                }
                            )
                            break
                        continue
                    if result.status == "error":
                        # El conector no lanza: ante red caída devuelve
                        # ConnectorResult.failed. Sin esto el disyuntor no se
                        # abría nunca y el fallo quedaba cacheado 55 min para
                        # todos los tenants.
                        consecutive_failures += 1
                        errors.extend(
                            {"theme": theme, "source": "gdelt", "message": error} for error in result.errors
                        )
                        if consecutive_failures >= _GDELT_MACRO_CIRCUIT_THRESHOLD:
                            errors.append(
                                {
                                    "theme": None,
                                    "source": "gdelt",
                                    "type": "circuit_open",
                                    "message": (
                                        "GDELT no responde: ciclo abortado tras "
                                        f"{consecutive_failures} fallos seguidos; "
                                        "los temas restantes quedan para el próximo tick"
                                    ),
                                }
                            )
                            break
                        continue
                    consecutive_failures = 0
                    _gdelt_macro_cache_set(cache_client, theme, result)
                if result.errors:
                    errors.extend(
                        {"theme": theme, "source": "gdelt", "message": error} for error in result.errors
                    )
                ingestion = service.ingest_news_result(
                    db,
                    result,
                    ticker=None,
                    news_lane=MACRO_NEWS_LANE,
                    macro_theme=theme,
                    detect_company=False,
                )
                if result.status != "error":
                    processed += 1
                ingested += int(ingestion.get("created", 0))
            return {
                "status": _batch_status(processed, errors),
                "actor": actor_name,
                "themes_processed": processed,
                "news_ingested": ingested,
                "errors": errors,
            }
        finally:
            release_job_lease(
                f"refresh_macro_news:{tenant_id}",
                lease,
                redis_url=_lease_redis_url(),
            )
            db.close()
    except dramatiq.Retry:
        raise
    except Exception as exc:
        return _handle_actor_error(actor_name, exc, tenant_id=tenant_id, user_id=user_id)


@dramatiq.actor(max_retries=3, min_backoff=30_000)
def process_document(
    ticker: str,
    title: str,
    url: str,
    source_type: str,
    published_at: str | None = None,
    tenant_id: int | None = None,
    user_id: str | None = None,
    filing_metadata: dict | None = None,
) -> dict[str, Any]:
    actor_name = "process_document"
    try:
        from app.services.feed_ingestion_service import FeedIngestionService

        published = datetime.fromisoformat(published_at.replace("Z", "+00:00")) if published_at else None
        db = _session(tenant_id, user_id)
        try:
            result = _run(
                FeedIngestionService().ingest_document_url(
                    db,
                    ticker=ticker,
                    title=title,
                    url=url,
                    source_type=source_type,
                    published_at=published,
                    filing_metadata=filing_metadata,
                )
            )
            return {"status": result.get("status", "ok"), "actor": actor_name, "result": result}
        finally:
            db.close()
    except Exception as exc:
        return _handle_actor_error(
            actor_name,
            exc,
            tenant_id=tenant_id,
            user_id=user_id,
            ticker=ticker,
            url=url,
            source_type=source_type,
        )


@dramatiq.actor(max_retries=3, min_backoff=30_000)
def process_document_structured(
    ticker: str,
    title: str,
    url: str,
    source_type: str,
    published_at: str | None = None,
    tenant_id: int | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    """Carril pesado de ingesta (worker-only): igual que process_document pero
    con el conversor Docling habilitado para PDFs con estructura (tablas/XBRL/
    escaneado, 0.3-3 s/pagina en CPU). NUNCA encolar desde la ruta sincrona de
    FastAPI para servir una respuesta: ahi se usa el carril rapido (o se
    encola este actor para reproceso diferido). Sin docling instalado degrada
    al carril rapido/clasico con warnings, nunca falla opaco.
    """
    actor_name = "process_document_structured"
    try:
        from app.services.docling_pipeline import docling_heavy_context
        from app.services.feed_ingestion_service import FeedIngestionService

        published = datetime.fromisoformat(published_at.replace("Z", "+00:00")) if published_at else None
        db = _session(tenant_id, user_id)
        try:
            with docling_heavy_context():
                result = _run(
                    FeedIngestionService().ingest_document_url(
                        db,
                        ticker=ticker,
                        title=title,
                        url=url,
                        source_type=source_type,
                        published_at=published,
                    )
                )
            return {"status": result.get("status", "ok"), "actor": actor_name, "result": result}
        finally:
            db.close()
    except Exception as exc:
        return _handle_actor_error(
            actor_name,
            exc,
            tenant_id=tenant_id,
            user_id=user_id,
            ticker=ticker,
            url=url,
            source_type=source_type,
        )


@dramatiq.actor(max_retries=1)
def consolidate_memory(
    tenant_id: int | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    actor_name = "consolidate_memory"
    try:
        from sqlalchemy import select

        from app.models import MemoryItem

        db = _session(tenant_id, user_id)
        try:
            items = list(
                db.scalars(
                    select(MemoryItem).where(MemoryItem.status == "active").order_by(MemoryItem.id)
                ).all()
            )
            canonical: dict[tuple, Any] = {}
            merged = 0
            for item in items:
                normalized = re.sub(r"\s+", " ", item.content.strip().lower())
                key = (item.company_id, item.scope, item.memory_type, normalized)
                existing = canonical.get(key)
                if existing is None:
                    canonical[key] = item
                    continue
                existing.importance = max(existing.importance, item.importance)
                existing.metadata_ = {
                    **(existing.metadata_ or {}),
                    "last_consolidated_at": datetime.now(UTC).isoformat(),
                }
                item.status = "consolidated"
                item.metadata_ = {
                    **(item.metadata_ or {}),
                    "consolidated_into": existing.id,
                }
                merged += 1
            db.commit()
            return {
                "status": "ok",
                "actor": actor_name,
                "active_scanned": len(items),
                "duplicates_consolidated": merged,
            }
        finally:
            db.close()
    except Exception as exc:
        return _handle_actor_error(actor_name, exc, tenant_id=tenant_id, user_id=user_id)


@dramatiq.actor(max_retries=1, dedup_enqueue_ttl=DEDUP_ENQUEUE_TTL_SECONDS)
def scan_contradictions(
    tenant_id: int | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    actor_name = "scan_contradictions"
    try:
        from sqlalchemy import select

        from app.models import Claim, ClaimEvidence, ThesisChange
        from app.services.thesis_change_types import claim_change_type

        db = _session(tenant_id, user_id)
        try:
            # Proyeccion: solo claim_id (las columnas Text de evidencia no se usan).
            evidence_claim_ids = list(
                db.scalars(
                    select(ClaimEvidence.claim_id).where(ClaimEvidence.evidence_type == "contradicts")
                ).all()
            )
            claim_ids = set(evidence_claim_ids)
            claims = list(db.scalars(select(Claim).where(Claim.id.in_(claim_ids))).all()) if claim_ids else []
            # Proyeccion: solo affected_claim_ids (la columna Text summary no se usa).
            existing_affected = list(
                db.scalars(
                    select(ThesisChange.affected_claim_ids).where(
                        ThesisChange.change_type == claim_change_type("contradicted")
                    )
                ).all()
            )
            already_flagged = {
                claim_id for affected in existing_affected for claim_id in (affected or [])
            }
            created = 0
            for claim in claims:
                claim.status = "contradicted"
                claim.last_reviewed_at = datetime.now(UTC)
                if claim.id in already_flagged:
                    continue
                db.add(
                    ThesisChange(
                        company_id=claim.company_id,
                        from_version_id=claim.thesis_version_id,
                        to_version_id=claim.thesis_version_id,
                        change_type=claim_change_type("contradicted"),
                        impact_direction="negative",
                        materiality_score=claim.materiality_score,
                        summary=f"La evidencia automática encontró contradicciones con la afirmación: {claim.statement[:220]}",
                        affected_claim_ids=[claim.id],
                        affected_metrics=[],
                        requires_review=True,
                    )
                )
                created += 1
            db.commit()
            return {
                "status": "ok",
                "actor": actor_name,
                "contradictory_evidence": len(evidence_claim_ids),
                "claims_flagged": len(claims),
                "changes_created": created,
            }
        finally:
            db.close()
    except Exception as exc:
        return _handle_actor_error(actor_name, exc, tenant_id=tenant_id, user_id=user_id)


@dramatiq.actor(max_retries=1)
def review_theses(
    tenant_id: int | None = None,
    user_id: str | None = None,
    ticker: str | None = None,
) -> dict[str, Any]:
    actor_name = "review_theses"
    try:
        from sqlalchemy import select

        from app.models import Company, ThesisChange
        from app.services.thesis_service import ThesisService

        db = _session(tenant_id, user_id)
        try:
            pending = list(
                db.scalars(select(ThesisChange).where(ThesisChange.requires_review.is_(True))).all()
            )
            company_ids = {change.company_id for change in pending if change.company_id}
            statement = select(Company)
            if ticker:
                statement = statement.where(Company.ticker == ticker.upper())
            elif company_ids:
                statement = statement.where(Company.id.in_(company_ids))
            else:
                return {
                    "status": "ok",
                    "actor": actor_name,
                    "companies_reviewed": 0,
                    "pending_changes": 0,
                    "reviews": [],
                }

            service = ThesisService()
            reviews: list[dict] = []
            errors: list[dict] = []
            for company in db.scalars(statement.order_by(Company.ticker)).all():
                try:
                    thesis = service.generate(db, company.ticker, force_new_version=False)
                    resolved = 0
                    for change in pending:
                        if change.company_id != company.id:
                            continue
                        thesis_created_at = thesis.created_at
                        change_created_at = change.created_at
                        if thesis_created_at and thesis_created_at.tzinfo is None:
                            thesis_created_at = thesis_created_at.replace(tzinfo=UTC)
                        if change_created_at and change_created_at.tzinfo is None:
                            change_created_at = change_created_at.replace(tzinfo=UTC)
                        thesis_is_newer = bool(
                            thesis_created_at and change_created_at and thesis_created_at >= change_created_at
                        )
                        if change.from_version_id != thesis.id and thesis_is_newer:
                            change.to_version_id = thesis.id
                            change.requires_review = False
                            resolved += 1
                    db.commit()
                    reviews.append(
                        {
                            "ticker": company.ticker,
                            "thesis_id": thesis.id,
                            "version": thesis.version,
                            "status": thesis.status,
                            "changes_resolved": resolved,
                        }
                    )
                except Exception as exc:
                    _rollback(db)
                    errors.append(
                        {
                            "ticker": company.ticker,
                            "type": type(exc).__name__,
                            "message": str(exc),
                        }
                    )
            return {
                "status": _batch_status(len(reviews), errors),
                "actor": actor_name,
                "companies_reviewed": len(reviews),
                "pending_changes": len(pending),
                "reviews": reviews,
                "errors": errors,
            }
        finally:
            db.close()
    except Exception as exc:
        return _handle_actor_error(actor_name, exc, tenant_id=tenant_id, user_id=user_id, ticker=ticker)


@dramatiq.actor(max_retries=1)
def run_daily_research() -> dict[str, Any]:
    actor_name = "run_daily_research"
    jobs: list[tuple[str, Any]] = [
        ("market_refresh", refresh_market_pipeline),
        ("sec_refresh", refresh_sec_filings),
        ("ir_refresh", refresh_ir_pages),
        ("rss_refresh", refresh_rss_feeds),
        ("news_refresh", refresh_news),
        ("memory_consolidation", consolidate_memory),
        ("contradiction_scan", scan_contradictions),
        # review_theses NO va aqui: tiene su propio cron (thesis_review, 07:00,
        # tras las noticias de run_daily_research) y estar en las dos listas lo
        # ejecutaba dos veces al dia por tenant.
    ]
    queued: list[dict] = []
    errors: list[dict] = []
    contexts = tenant_contexts()
    for tenant_id, user_id in contexts:
        for job_name, actor in jobs:
            try:
                message = actor.send(tenant_id, user_id)
                queued.append(
                    {
                        "job": job_name,
                        "tenant_id": tenant_id,
                        "user_id": user_id,
                        "message_id": _message_id(message),
                    }
                )
            except Exception as exc:
                errors.append(
                    {
                        "job": job_name,
                        "tenant_id": tenant_id,
                        "user_id": user_id,
                        "type": type(exc).__name__,
                        "message": str(exc),
                    }
                )
    return {
        "status": _batch_status(len(queued), errors),
        "actor": actor_name,
        "workflow": "DailyResearchWorkflow",
        "queued": queued,
        "errors": errors,
    }


@dramatiq.actor(max_retries=2, min_backoff=15_000, dedup_enqueue_ttl=DEDUP_ENQUEUE_TTL_SECONDS)
@_coalesce_on_success("scan_insider_watchlist", 12 * 60, ("tenant_id", "lookback", "max_new_fetches"))
def scan_insider_watchlist(
    tenant_id: int | None = None,
    user_id: str | None = None,
    lookback: int = 20,
    max_new_fetches: int = 25,
) -> dict[str, Any]:
    """PR-3: escaneo acotado de Form 4 para la watchlist/cartera.

    Solo emisores seguidos; salta accessions ya persistidos (#82) y deja
    watermark + metricas en connector_states. Reintentos Dramatiq solo para
    fallos transitorios; los permanentes devuelven payload estructurado.
    """
    actor_name = "scan_insider_watchlist"
    try:
        from app.services import insider_monitor

        db = _session(tenant_id, user_id)
        # Ver refresh_market_pipeline: la sesion se abre antes del lease para
        # que un ValueError de _session no lo retenga hasta el TTL.
        try:
            lease = acquire_job_lease(
                f"scan_insider_watchlist:{tenant_id}",
                ttl_seconds=600,
                redis_url=_lease_redis_url(),
            )
        except Exception:
            # Si la adquisicion lanza (Redis caido, red, ...), la sesion abierta
            # justo arriba no puede quedar sin cerrar.
            db.close()
            raise
        if lease is None:
            db.close()
            return {"status": "skipped", "actor": actor_name, "reason": "lease_held"}
        try:
            stats = insider_monitor.scan(
                db,
                tenant_id=tenant_id,
                lookback=lookback,
                max_new_fetches=max_new_fetches,
                backfill=True,
            )
        finally:
            release_job_lease(f"scan_insider_watchlist:{tenant_id}", lease, redis_url=_lease_redis_url())
            db.close()
        return {
            "status": stats["status"],
            "actor": actor_name,
            "tickers_scanned": stats["tickers_scanned"],
            "filings_seen": stats["filings_seen"],
            "filings_new": stats["filings_new"],
            "transactions_created": stats["transactions_created"],
            "errors": stats["errors"][:20],
        }
    except Exception as exc:
        return _handle_actor_error(actor_name, exc, tenant_id=tenant_id)


@dramatiq.actor(max_retries=2, min_backoff=15_000)
def scan_schedule13dg_watchlist(
    tenant_id: int | None = None,
    user_id: str | None = None,
    lookback: int = 40,
    max_new_fetches: int = 10,
) -> dict[str, Any]:
    """Escaneo acotado de SC 13D/13G (titulares >5%) para la watchlist/cartera.

    Solo emisores seguidos; salta accessions ya persistidos y deja
    watermark + metricas en connector_states. Lo no parseable queda N/D
    (status="unparsed"), nunca inventado. Reintentos Dramatiq solo para
    fallos transitorios; los permanentes devuelven payload estructurado.
    """
    actor_name = "scan_schedule13dg_watchlist"
    try:
        from app.services import schedule13dg_monitor

        db = _session(tenant_id, user_id)
        # Ver refresh_market_pipeline: la sesion se abre antes del lease para
        # que un ValueError de _session no lo retenga hasta el TTL.
        try:
            lease = acquire_job_lease(
                f"scan_schedule13dg_watchlist:{tenant_id}",
                ttl_seconds=600,
                redis_url=_lease_redis_url(),
            )
        except Exception:
            # Si la adquisicion lanza (Redis caido, red, ...), la sesion abierta
            # justo arriba no puede quedar sin cerrar.
            db.close()
            raise
        if lease is None:
            db.close()
            return {"status": "skipped", "actor": actor_name, "reason": "lease_held"}
        try:
            stats = schedule13dg_monitor.scan(
                db,
                tenant_id=tenant_id,
                lookback=lookback,
                max_new_fetches=max_new_fetches,
            )
        finally:
            release_job_lease(f"scan_schedule13dg_watchlist:{tenant_id}", lease, redis_url=_lease_redis_url())
            db.close()
        return {
            "status": stats["status"],
            "actor": actor_name,
            "tickers_scanned": stats["tickers_scanned"],
            "filings_seen": stats["filings_seen"],
            "filings_new": stats["filings_new"],
            "filings_unparsed": stats["filings_unparsed"],
            "filings_rejected": stats.get("filings_rejected", 0),
            "errors": stats["errors"][:20],
        }
    except Exception as exc:
        return _handle_actor_error(actor_name, exc, tenant_id=tenant_id)


@dramatiq.actor(max_retries=2, min_backoff=15_000)
@_coalesce_on_success("sync_investor_holdings", 12 * 60 * 60, ("tenant_id",))
def sync_investor_holdings(
    tenant_id: int | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    """Refresco semanal de las carteras de inversores (13F de los gestores
    revisados y Form 4 de Trump/Bezos). Cada fuente falla por separado."""
    actor_name = "sync_investor_holdings"
    try:
        from app.services.investor_sync import sync_investor_holdings as run_sync

        db = _session(tenant_id, user_id)
        try:
            lease = acquire_job_lease(
                f"sync_investor_holdings:{tenant_id}",
                ttl_seconds=1800,
                redis_url=_lease_redis_url(),
            )
        except Exception:
            db.close()
            raise
        if lease is None:
            db.close()
            return {"status": "skipped", "actor": actor_name, "reason": "lease_held"}
        try:
            result = run_sync(db)
        finally:
            release_job_lease(f"sync_investor_holdings:{tenant_id}", lease, redis_url=_lease_redis_url())
            db.close()
        return {"actor": actor_name, **result}
    except Exception as exc:
        return _handle_actor_error(actor_name, exc, tenant_id=tenant_id)


@dramatiq.actor(max_retries=1, min_backoff=30_000)
@_coalesce_on_success("ingest_letters_corpus", 6 * 60 * 60, ("tenant_id",))
def ingest_letters_corpus(
    tenant_id: int | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    """Primera carga del corpus libre de cartas para un tenant.

    Se encola desde la UI (POST /api/knowledge/corpus/ingest-async) cuando la
    biblioteca esta vacia: la cuenta nueva no espera a una corrida manual del
    script CLI. Fuentes publicas declaradas; dedupe SHA-256 en la biblioteca.
    """
    actor_name = "ingest_letters_corpus"
    try:
        from app.services.corpus_ingestion_service import ingest_free_corpus

        db = _session(tenant_id, user_id)
        try:
            lease = acquire_job_lease(
                f"ingest_letters_corpus:{tenant_id}",
                ttl_seconds=3600,
                redis_url=_lease_redis_url(),
            )
        except Exception:
            db.close()
            raise
        if lease is None:
            db.close()
            return {"status": "skipped", "actor": actor_name, "reason": "lease_held"}
        try:
            result = ingest_free_corpus(db)
        finally:
            release_job_lease(f"ingest_letters_corpus:{tenant_id}", lease, redis_url=_lease_redis_url())
            db.close()
        return {"actor": actor_name, **result}
    except Exception as exc:
        return _handle_actor_error(actor_name, exc, tenant_id=tenant_id)


@dramatiq.actor(max_retries=2, min_backoff=15_000, queue_name=ALERT_QUEUE_NAME)
def dispatch_insider_alerts(
    tenant_id: int | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    """PR-4: evalua reglas insider sobre lo persistido y escribe el outbox.

    Alert key = rule_version + fingerprint de transaccion: re-evaluar nunca
    duplica; una enmienda 4/A llega con fingerprints propios y genera sus
    propias alertas. Telegram es opt-in (INSIDER_ALERTS_ENABLED).
    """
    actor_name = "dispatch_insider_alerts"
    try:
        from app.services import insider_alerts

        db = _session(tenant_id, user_id)
        # Ver refresh_market_pipeline: la sesion se abre antes del lease para
        # que un ValueError de _session no lo retenga hasta el TTL.
        try:
            lease = acquire_job_lease(
                f"dispatch_insider_alerts:{tenant_id}",
                ttl_seconds=900,
                redis_url=_lease_redis_url(),
            )
        except Exception:
            # Si la adquisicion lanza (Redis caido, red, ...), la sesion abierta
            # justo arriba no puede quedar sin cerrar.
            db.close()
            raise
        if lease is None:
            db.close()
            return {"status": "skipped", "actor": actor_name, "reason": "lease_held"}
        try:
            stats = insider_alerts.evaluate(db, tenant_id=tenant_id)
        finally:
            release_job_lease(f"dispatch_insider_alerts:{tenant_id}", lease, redis_url=_lease_redis_url())
            db.close()
        return {
            "status": stats["status"],
            "actor": actor_name,
            "candidates": stats["candidates"],
            "alerts_created": stats["alerts_created"],
            "alerts_existing": stats["alerts_existing"],
            "telegram_sent": stats["telegram_sent"],
            "errors": stats["errors"][:20],
        }
    except Exception as exc:
        return _handle_actor_error(actor_name, exc, tenant_id=tenant_id)


@dramatiq.actor(max_retries=1, min_backoff=30_000, queue_name=ALERT_QUEUE_NAME)
def dispatch_earnings_reminders(
    tenant_id: int | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    """Avisos de proximos resultados (7 / 1 / 0 dias) de cartera + watchlist.

    Lee las fechas YA refrescadas en earnings_dates (no llama a fuentes): si el
    refresco no corrio, no hay fechas frescas y no sale nada, nunca se inventa.
    Persiste una alerta por ticker/fecha/ventana y la despacha por los canales
    con consentimiento (in_app, correo SMTP, Telegram/push con suscripcion).
    """
    actor_name = "dispatch_earnings_reminders"
    db = None
    lease = None
    try:
        from app.services.earnings_reminders import emit_earnings_reminders
        from app.services.outbound_alerts import dispatch_pending

        db = _session(tenant_id, user_id)
        lease = acquire_job_lease(
            f"{actor_name}:{tenant_id}",
            ttl_seconds=300,
            redis_url=_lease_redis_url(),
        )
        if lease is None:
            return {"status": "skipped", "actor": actor_name, "reason": "lease_held"}
        stats = emit_earnings_reminders(db)
        pending = dispatch_pending(db)
        return {
            "status": "ok",
            "actor": actor_name,
            "created": stats["created"],
            "existing": stats["existing"],
            "redispatched": pending["redispatched"],
            "errors": pending["errors"][:20],
        }
    except Exception as exc:
        if db is not None:
            _rollback(db)
        return _handle_actor_error(actor_name, exc, tenant_id=tenant_id)
    finally:
        if lease is not None:
            release_job_lease(f"{actor_name}:{tenant_id}", lease, redis_url=_lease_redis_url())
        if db is not None:
            db.close()


@dramatiq.actor(max_retries=1, min_backoff=30_000, queue_name=ALERT_QUEUE_NAME)
def dispatch_macro_reminders(
    tenant_id: int | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    """Recordatorios T-24 h / T-1 h del calendario macro oficial (FOMC, BLS).

    Persiste la alerta una vez por evento y ventana y la despacha por los
    canales con consentimiento. Fuente caida: no emite nada, nunca inventa.
    """
    actor_name = "dispatch_macro_reminders"
    db = None
    lease = None
    try:
        from datetime import timedelta

        from app.services import macro_calendar_service
        from app.services.macro_reminders import emit_macro_reminders
        from app.services.outbound_alerts import dispatch_pending

        db = _session(tenant_id, user_id)
        lease = acquire_job_lease(
            f"dispatch_macro_reminders:{tenant_id}",
            ttl_seconds=300,
            redis_url=_lease_redis_url(),
        )
        if lease is None:
            return {"status": "skipped", "actor": actor_name, "reason": "lease_held"}
        today = datetime.now(UTC).date()
        calendar = _run(
            macro_calendar_service.get_macro_events(today - timedelta(days=1), today + timedelta(days=3))
        )
        if calendar["status"] == "unavailable":
            return {"status": "skipped", "actor": actor_name, "reason": "source_unavailable"}
        stats = emit_macro_reminders(db, calendar["events"])
        pending = dispatch_pending(db)
        return {
            "status": "ok",
            "actor": actor_name,
            "calendar_status": calendar["status"],
            "created": stats["created"],
            "existing": stats["existing"],
            "redispatched": pending["redispatched"],
            "errors": pending["errors"][:20],
        }
    except Exception as exc:
        if db is not None:
            _rollback(db)
        return _handle_actor_error(actor_name, exc, tenant_id=tenant_id)
    finally:
        if lease is not None:
            release_job_lease(f"dispatch_macro_reminders:{tenant_id}", lease, redis_url=_lease_redis_url())
        if db is not None:
            db.close()


@dramatiq.actor(max_retries=2, min_backoff=15_000, queue_name=ALERT_QUEUE_NAME)
def reconcile_alert_deliveries(
    tenant_id: int | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    """Barrido periodico del outbox de entregas de alertas.

    Re-despacha filas 'sending'/'unknown'/'throttled' cuyo claim ya expiro
    (worker muerto, commit fallido, timeout/5xx, 429). Sin este barrido el
    TTL solo ayuda si el emisor original vuelve a entrar para esa alerta.
    'failed' (rechazo 4xx != 429) es permanente y no se toca.
    """
    actor_name = "reconcile_alert_deliveries"
    db = None
    lease = None
    try:
        from app.services.notification_service import NotificationService

        # Sesion ANTES del lease: si _session lanza (tenant inactivo), no hay
        # lease retenido hasta el TTL. El finally libera en cualquier camino
        # posterior a la adquisicion.
        db = _session(tenant_id, user_id)
        lease = acquire_job_lease(
            f"reconcile_alert_deliveries:{tenant_id}",
            ttl_seconds=600,
            redis_url=_lease_redis_url(),
        )
        if lease is None:
            return {"status": "skipped", "actor": actor_name, "reason": "lease_held"}
        from app.services.outbound_alerts import dispatch_pending

        pending = dispatch_pending(db)
        stats = NotificationService().reconcile_stale_deliveries(db, tenant_id=tenant_id)
        for key in ("candidates", "redispatched"):
            stats[key] += pending[key]
        stats["errors"].extend(pending["errors"])
        return {
            "status": "ok",
            "actor": actor_name,
            "candidates": stats["candidates"],
            "redispatched": stats["redispatched"],
            "errors": stats["errors"][:20],
        }
    except Exception as exc:
        return _handle_actor_error(actor_name, exc, tenant_id=tenant_id)
    finally:
        if lease is not None:
            release_job_lease(
                f"reconcile_alert_deliveries:{tenant_id}",
                lease,
                redis_url=_lease_redis_url(),
            )
        if db is not None:
            db.close()


# Short aliases keep operational imports stable while actor names remain descriptive.
refresh_sec = refresh_sec_filings
refresh_ir = refresh_ir_pages
refresh_rss = refresh_rss_feeds


if __name__ == "__main__":
    print("Dramatiq actors registered. Run with: dramatiq app.workers.dramatiq_app")


# Cola dedicada (F359): los jobs de tesis los dispara el USUARIO y son
# interactivos; en "default" quedaban hambreados detras de la ingesta por
# lotes (7476 mensajes acumulados, 5276 de ellos veneno SEC imposible desde
# OCI). El worker los escucha con -Q default prices thesis.
@dramatiq.actor(max_retries=2, min_backoff=15_000, queue_name="thesis")
def generate_thesis_job(run_id: int) -> None:
    """Execute one queued async thesis generation job (durable envelope)."""
    from app.services.thesis_job_service import run_thesis_job

    run_thesis_job(run_id)


# Se queda en default (29-oct, revision del piloto): no esta acreditado que
# sea un job corto (hasta 50 quotes de proveedor + sync de acciones
# corporativas por fila; time_limit 900 s) y en el worker-alerts de 2 hilos
# dos refrescos simultaneos podian ocupar ambos hilos y retrasar las alertas.
# La coalescencia hace que las copias encoladas bajo starvation se salten
# casi gratis (patron rss/insider; la ventana 25 min < cadencia de 30 min,
# como en refresh_news tracked).
@dramatiq.actor(max_retries=1, min_backoff=30_000, time_limit=900_000, dedup_enqueue_ttl=DEDUP_ENQUEUE_TTL_SECONDS)
@_coalesce_on_success("refresh_paper_trades", 25 * 60, ("tenant_id",))
def refresh_paper_trades(tenant_id: int | None = None, user_id: str | None = None) -> dict[str, Any]:
    from app.services.paper_trading_service import refresh_trades

    db = _session(tenant_id, user_id)
    try:
        # status ok explicito: sin el la marca de coalescencia nunca quedaba
        # fresca (el decorador solo conserva el claim con status "ok").
        return {"status": "ok", "actor": "refresh_paper_trades", **refresh_trades(db)}
    except Exception as exc:
        _rollback(db)
        return _handle_actor_error("refresh_paper_trades", exc, tenant_id=tenant_id)
    finally:
        db.close()


@dramatiq.actor(max_retries=0, time_limit=900_000)
def propose_paper_trades(tenant_id: int | None = None, user_id: str | None = None) -> dict[str, Any]:
    """Lote de propuestas LLM para el paper book (INFERIDO, solo proveedor gratuito).

    Manual (POST /paper-trading/feed) y programado (cron diario
    paper_proposals_daily): ambos comparten la cuota diaria con el endpoint de
    propuestas; este actor no define tope propio.
    """
    from app.services.paper_feed_service import run_feed

    db = _session(tenant_id, user_id)
    try:
        return {"actor": "propose_paper_trades", **_run(run_feed(db))}
    except Exception as exc:
        _rollback(db)
        return _handle_actor_error("propose_paper_trades", exc, tenant_id=tenant_id)
    finally:
        db.close()


@dramatiq.actor(max_retries=1, min_backoff=30_000)
def sync_paper_dividends(tenant_id: int | None = None, user_id: str | None = None) -> dict[str, Any]:
    """Ingesta diaria de dividendos declarados de los tickers con paper trades vivos.

    Misma fuente gratuita y servicio que la cartera real (Yahoo, FMP de
    respaldo): sin ellos el devengo del paper book no tiene con que computar.
    """
    from sqlalchemy import select

    from app.models.paper_trading import PaperTrade as _PT
    from app.services.async_bridge import run_from_any_context
    from app.services.dividend_ingestion_service import DividendIngestionService

    db = _session(tenant_id, user_id)
    try:
        tickers = [
            t
            for (t,) in db.execute(
                select(_PT.ticker).where(_PT.status.in_(("pending", "open"))).distinct()
            ).all()
        ]
        service = DividendIngestionService()
        synced, unavailable = [], []
        for ticker in tickers:
            db.commit()  # sesion libre antes de la red
            result = run_from_any_context(service.sync_company(db, ticker=ticker))
            (synced if result.get("status") == "ok" else unavailable).append(ticker)
        return {
            "actor": "sync_paper_dividends",
            "status": "ok",
            "tickers": len(tickers),
            "synced": synced,
            "unavailable": unavailable,
        }
    except Exception as exc:
        _rollback(db)
        return _handle_actor_error("sync_paper_dividends", exc, tenant_id=tenant_id)
    finally:
        db.close()


# RAG de conocimiento: registra el actor de ingesta (cola "knowledge").
import app.workers.knowledge_rag_actors  # noqa: E402,F401


@dramatiq.actor(max_retries=0, time_limit=600_000)
def sync_tenant_ibkr_connections() -> dict[str, Any]:
    """Bounded daily reporting sync, one independently scoped account per tenant."""
    from sqlalchemy import select

    from app.core.database import SessionLocal
    from app.models import IBKRConnection

    with SessionLocal() as admin:
        ids = set(
            admin.scalars(
                select(IBKRConnection.tenant_id)
                .where(
                    IBKRConnection.enabled.is_(True),
                )
                .execution_options(include_all_tenants=True)
            ).all()
        )
    scheduled = 0
    for tenant_id, user_id in tenant_contexts():
        if tenant_id in ids:
            actor = (
                sync_one_tenant_ibkr_dedicated
                if get_settings().ibkr_dedicated_sync_enabled
                else sync_one_tenant_ibkr
            )
            actor.send(tenant_id, user_id)
            scheduled += 1
    return {"scheduled": scheduled}


@dramatiq.actor(max_retries=2, time_limit=300_000)
def sync_one_tenant_ibkr(tenant_id: int, user_id: str) -> dict[str, Any]:
    from app.services import ibkr_connection_service as ibkr

    with _session(tenant_id, user_id) as db:
        revision: int | None = None
        receipt_id: int | None = None
        try:
            with ibkr.sync_lease(db):
                try:
                    token, query_id, account_id, revision = ibkr.credentials(db, get_settings())
                    receipt_id = ibkr.start_receipt(db, revision=revision, origin="scheduled")
                    xml = _run(ibkr.download(token, query_id))
                    return ibkr.import_report(db, xml, account_id, revision, receipt_id=receipt_id)
                except Exception as exc:
                    kind = ibkr.error_kind(exc)
                    ibkr.record_failure(db, revision=revision, receipt_id=receipt_id,
                                        error_code=kind)
                    if kind == "not_ready":
                        # IBKR entrego el extracto antes de calcular su PyG:
                        # transitorio por definicion. Mismo trato que el flujo
                        # global sync_ibkr_flex: como mucho max_retries (2)
                        # reintentos, una hora entre intentos, y cada uno pide
                        # un extracto NUEVO (el diferido queda sellado en IBKR).
                        # Solo not_ready reintenta: credentials/report/import no
                        # las arregla la espera y reintentar un timeout en
                        # caliente martillea la Flex Web API.
                        raise dramatiq.Retry(
                            "IBKR PyG aun no disponible; reintento en una hora",
                            delay=3_600_000,
                        ) from exc
                    return {
                        "status": "error",
                        "message": "IBKR no disponible; se conservan los datos anteriores.",
                    }
        except ibkr.SyncBusy:
            return {"status": "busy", "message": "Ya hay una sincronización IBKR en curso."}


@dramatiq.actor(queue_name="dca-manual", max_retries=0, time_limit=1_800_000)
def evaluate_manual_dca(run_id: int, token: str, tenant_id: int, user_id: str) -> dict:
    """Execute an accepted, bounded manual batch outside the HTTP request."""
    from app.services.dca_manual_job import run_manual_job

    db = _session(tenant_id, user_id)
    try:
        return run_manual_job(db, run_id, token)
    finally:
        db.close()


@dramatiq.actor(queue_name="ibkr-sync", max_retries=0, time_limit=600_000)
def sync_tenant_ibkr_connections_dedicated() -> dict[str, Any]:
    """Dedicated dispatcher so default backlog cannot delay tenant Flex imports."""
    return sync_tenant_ibkr_connections.fn()


@dramatiq.actor(queue_name="ibkr-sync", max_retries=2, time_limit=300_000)
def sync_one_tenant_ibkr_dedicated(tenant_id: int, user_id: str) -> dict[str, Any]:
    """Same revision/date validation, separate bounded read-only consumer."""
    return sync_one_tenant_ibkr.fn(tenant_id, user_id)


@dramatiq.actor(max_retries=1, min_backoff=30_000, queue_name=ALERT_QUEUE_NAME)
def dispatch_source_health_watchdog(
    tenant_id: int | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    """Alerta in-app al operador cuando una fuente de datos pasa a degradada/caída.

    Lee el circuit breaker de fuentes del PROCESO del worker (el registry es
    por proceso: ve las transiciones registradas por actores de este worker) y
    persiste una ResearchAlert in-app por fuente, estado y día. Coste 0.
    """
    actor_name = "dispatch_source_health_watchdog"
    db = None
    lease = None
    try:
        from app.services.source_health_watchdog import emit_source_health_alerts

        db = _session(tenant_id, user_id)
        lease = acquire_job_lease(
            f"dispatch_source_health_watchdog:{tenant_id}",
            ttl_seconds=120,
            redis_url=_lease_redis_url(),
        )
        if lease is None:
            return {"status": "skipped", "actor": actor_name, "reason": "lease_held"}
        stats = emit_source_health_alerts(db)
        return {"status": "ok", "actor": actor_name, **stats}
    except Exception as exc:
        if db is not None:
            _rollback(db)
        return _handle_actor_error(actor_name, exc, tenant_id=tenant_id)
    finally:
        if lease is not None:
            release_job_lease(
                f"dispatch_source_health_watchdog:{tenant_id}", lease, redis_url=_lease_redis_url()
            )
        if db is not None:
            db.close()
