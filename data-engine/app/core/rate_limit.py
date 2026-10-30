"""Post-signature rate limiting by real client IP + verified principal.

This is intentionally a dependency (not global middleware): it runs after
``get_research_principal`` has verified the HMAC identity, so the limiting key
is built from the *verified* tenant/user plus the socket client IP — never
from spoofable request headers.

The window is a true sliding window (Redis ZSET of hit timestamps; a local
timestamp deque as fallback) so a burst cannot straddle a minute boundary and
double the effective rate. In production the counter never degrades to the
process-local store: if Redis is down, requests fail closed with 503.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import math
import time
import uuid
from collections import deque

from fastapi import Depends, HTTPException, Request, Response

from app.core.auth import ResearchPrincipal, get_research_principal, sign_research_identity
from app.core.config import get_settings

logger = logging.getLogger(__name__)

WINDOW_SECONDS = 60

EXPENSIVE_PATH_MARKERS = (
    "/chat",
    "/extract-kpis",
    "/long-term-model/generate",
    "/thesis/generate",
    "/snapshot/refresh",
)

EXEMPT_PATHS = {"/", "/health", "/health/live", "/health/ready"}


def is_exempt_path(path: str) -> bool:
    """Health/readiness probes are never rate limited.

    Exact matches plus any ``/health*`` prefix, with or without the
    ``/api`` mount prefix (``/api/health``, ``/api/health/live``, ...).
    """
    if path in EXEMPT_PATHS:
        return True
    if path == "/api/health" or path.startswith("/api/health/"):
        return True
    stripped = path[len("/api") :] if path.startswith("/api/") else path
    return stripped == "/health" or stripped.startswith("/health/")

_local_hits: dict[str, deque[float]] = {}
_local_lock = asyncio.Lock()


class RateLimitBackendUnavailable(RuntimeError):
    """Redis is down and production must not degrade to a local counter."""


def _now() -> float:
    return time.time()


def _tier_for(path: str) -> str:
    """Tier del bucket: expensive y market cuentan aparte del estandar para
    que las rafagas de lecturas de mercado (una llamada por ticker) no
    estrangulen el resto de la navegacion, ni al reves."""
    if any(marker in path for marker in EXPENSIVE_PATH_MARKERS):
        return "expensive"
    if path.startswith("/api/market/"):
        return "market"
    return "standard"


def _limit_for(settings, path: str) -> int:
    tier = _tier_for(path)
    if tier == "expensive":
        limit = settings.rate_limit_expensive_requests_per_minute
    elif tier == "market":
        limit = getattr(
            settings, "rate_limit_market_requests_per_minute", 900
        )
    else:
        limit = settings.rate_limit_requests_per_minute
    if settings.is_local_environment:
        limit = max(limit, settings.rate_limit_local_request_floor)
    return limit


def _rate_limit_identity(
    principal: ResearchPrincipal | None, request: Request
) -> str:
    """Identity = verified principal + real client IP (socket peer)."""
    client_ip = request.client.host if request.client else "unknown"
    if principal is not None:
        who = f"{principal.tenant_external_id}:{principal.user_id}"
    else:
        who = "anonymous"
    return f"{who}@{client_ip}"


async def _record_hit(
    key: str,
    *,
    window_seconds: int,
    use_redis: bool,
    redis_url: str,
    degrade_to_local: bool,
) -> tuple[int, int]:
    """Record one hit and return ``(hits_in_window, retry_after_seconds)``."""
    now = _now()
    if use_redis:
        try:
            import redis.asyncio as redis

            from app.core.redis_retry import no_retry_async

            client = redis.from_url(redis_url, socket_connect_timeout=0.25, socket_timeout=0.5, retry=no_retry_async())
            member = f"{now:.6f}:{uuid.uuid4().hex}"
            try:
                async with client.pipeline(transaction=True) as pipe:
                    pipe.zremrangebyscore(key, "-inf", now - window_seconds)
                    pipe.zadd(key, {member: now})
                    pipe.zcard(key)
                    pipe.expire(key, window_seconds + 5)
                    pipe.zrange(key, 0, 0, withscores=True)
                    _, _, count, _, oldest = await pipe.execute()
            finally:
                await client.aclose()
            retry_after = _retry_after(
                oldest[0][1] if oldest else now, now, window_seconds
            )
            return int(count), retry_after
        except Exception as exc:  # noqa: BLE001
            if not degrade_to_local:
                # Production keeps counting or it is not a limit at all.
                raise RateLimitBackendUnavailable(
                    "rate-limit store unreachable"
                ) from exc

    async with _local_lock:
        hits = _local_hits.setdefault(key, deque())
        cutoff = now - window_seconds
        while hits and hits[0] <= cutoff:
            hits.popleft()
        hits.append(now)
        return len(hits), _retry_after(hits[0], now, window_seconds)


def _retry_after(oldest: float, now: float, window_seconds: int) -> int:
    return max(1, math.ceil(oldest + window_seconds - now))


async def enforce_rate_limit(
    request: Request,
    response: Response,
    principal: ResearchPrincipal | None = Depends(get_research_principal),
) -> None:
    settings = get_settings()
    if (
        not settings.rate_limit_enabled
        or is_exempt_path(request.url.path)
        or request.method == "OPTIONS"
    ):
        return

    limit = _limit_for(settings, request.url.path)
    identity = _rate_limit_identity(principal, request)
    digest = hashlib.sha256(
        f"{identity}:{_tier_for(request.url.path)}".encode()
    ).hexdigest()
    key = f"cavaai:rate:{digest}"
    use_redis = not settings.is_local_environment
    try:
        count, retry_after = await _record_hit(
            key,
            window_seconds=WINDOW_SECONDS,
            use_redis=use_redis,
            redis_url=settings.redis_url,
            degrade_to_local=not settings.is_production,
        )
    except RateLimitBackendUnavailable as exc:
        raise HTTPException(
            status_code=503, detail="Rate limit backend unavailable"
        ) from exc

    if count > limit:
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded",
            headers={"Retry-After": str(retry_after)},
        )
    response.headers["X-RateLimit-Limit"] = str(limit)
    response.headers["X-RateLimit-Remaining"] = str(max(0, limit - count))


LLM_TEST_LIMIT_PER_MINUTE = 10


async def enforce_llm_test_rate_limit(
    request: Request,
    principal: ResearchPrincipal | None = Depends(get_research_principal),
) -> None:
    """Prueba de conexion LLM: 10/min por identidad (evita sondear a ciegas)."""
    settings = get_settings()
    if not settings.rate_limit_enabled:
        return
    limit = LLM_TEST_LIMIT_PER_MINUTE
    if settings.is_local_environment:
        limit = max(limit, settings.rate_limit_local_request_floor)
    identity = _rate_limit_identity(principal, request)
    digest = hashlib.sha256(f"{identity}:llm-test".encode()).hexdigest()
    try:
        count, retry_after = await _record_hit(
            f"cavaai:rate:{digest}",
            window_seconds=WINDOW_SECONDS,
            use_redis=not settings.is_local_environment,
            redis_url=settings.redis_url,
            degrade_to_local=not settings.is_production,
        )
    except RateLimitBackendUnavailable as exc:
        raise HTTPException(
            status_code=503, detail="Rate limit backend unavailable"
        ) from exc
    if count > limit:
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded",
            headers={"Retry-After": str(retry_after)},
        )


PUBLIC_FEED_LIMIT_PER_MINUTE = 60


def public_client_ip(request: Request) -> str:
    """IP real para el limite publico.

    Detras de Caddy el peer del socket es la IP privada del proxy (todo el
    mundo compartiria un cubo). Solo si el peer es privado/loopback se usa la
    ULTIMA entrada de X-Forwarded-For: la anade el proxy de confianza con la
    IP que ve; las anteriores las puede falsificar el cliente. Un peer
    publico (acceso directo) usa su propia IP e ignora la cabecera.
    """
    import ipaddress

    peer = request.client.host if request.client else "unknown"
    try:
        peer_ip = ipaddress.ip_address(peer)
    except ValueError:
        return peer
    if not (peer_ip.is_private or peer_ip.is_loopback):
        return peer
    forwarded = request.headers.get("x-forwarded-for", "")
    last = forwarded.split(",")[-1].strip() if forwarded else ""
    try:
        return str(ipaddress.ip_address(last))
    except ValueError:
        return peer


async def enforce_public_ip_rate_limit(request: Request) -> None:
    """Limite por IP para rutas publicas sin identidad (feed ICS).

    La IP sale de public_client_ip (peer del socket; tras proxy privado, la ultima entrada de X-Forwarded-For). En
    produccion falla cerrado (503) si Redis no responde, como el limite
    principal.
    """
    settings = get_settings()
    if not settings.rate_limit_enabled:
        return
    client_ip = public_client_ip(request)
    digest = hashlib.sha256(f"public-feed:{client_ip}".encode()).hexdigest()
    try:
        count, retry_after = await _record_hit(
            f"cavaai:rate:{digest}",
            window_seconds=WINDOW_SECONDS,
            use_redis=not settings.is_local_environment,
            redis_url=settings.redis_url,
            degrade_to_local=not settings.is_production,
        )
    except RateLimitBackendUnavailable as exc:
        raise HTTPException(status_code=503, detail="Rate limit backend unavailable") from exc
    if count > PUBLIC_FEED_LIMIT_PER_MINUTE:
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded",
            headers={"Retry-After": str(retry_after)},
        )


# --- Limite previo a la auth: peticiones que acaban en 401 -----------------
# enforce_rate_limit depende de get_research_principal, asi que un 401 se
# lanza ANTES de contar nada: un cliente sin credenciales podia martillear la
# API sin limite. Este middleware cuenta por IP solo las respuestas 401 y
# corta con 429 cuando una IP supera AUTH_FAILURE_LIMIT en la ventana.

AUTH_FAILURE_LIMIT = 30


async def _count_hits(key: str, *, use_redis: bool, redis_url: str) -> int:
    now = _now()
    if use_redis:
        import redis.asyncio as redis

        from app.core.redis_retry import no_retry_async

        client = redis.from_url(
            redis_url, socket_connect_timeout=0.25, socket_timeout=0.5, retry=no_retry_async()
        )
        try:
            return int(await client.zcount(key, now - WINDOW_SECONDS, "+inf"))
        finally:
            await client.aclose()
    async with _local_lock:
        hits = _local_hits.get(key)
        if not hits:
            return 0
        cutoff = now - WINDOW_SECONDS
        return sum(1 for h in hits if h > cutoff)


_SIGNATURE_RE_HEX = frozenset("0123456789abcdef")


def _carries_valid_signature(scope, settings) -> bool:
    """True si la peticion trae una firma HMAC valida del puente de identidad.

    En produccion TODO el trafico legitimo llega desde el servidor Next (las
    IP de salida de Vercel), asi que el contador de 401 por IP es compartido
    por todos los usuarios: 30 respuestas 401 en un minuto desde esa IP (de
    cualquiera que comparta la salida, o de peticiones caducadas) dejaban a
    TODOS los usuarios en 429 durante la ventana. Una firma valida demuestra
    que quien llama tiene el secreto, asi que no se corta aunque la IP este
    por encima del limite. Aqui no se lee el body ni se consume el nonce:
    get_research_principal sigue haciendo la verificacion completa despues.
    """
    secret = getattr(settings, "research_auth_secret", None)
    if not secret:
        return False
    headers: dict[str, str] = {}
    for raw_name, raw_value in scope.get("headers") or []:
        name = raw_name.decode("latin-1").lower()
        if name.startswith("x-cavaai-"):
            headers[name] = raw_value.decode("latin-1")
    user = headers.get("x-cavaai-user", "")
    tenant = headers.get("x-cavaai-tenant", "")
    timestamp = headers.get("x-cavaai-timestamp", "")
    signature = headers.get("x-cavaai-signature", "")
    if not (user.strip() and tenant.strip() and timestamp and signature):
        return False
    if len(signature) != 64 or not set(signature) <= _SIGNATURE_RE_HEX:
        return False
    try:
        issued_at = int(timestamp)
    except ValueError:
        return False
    now = int(_now())
    max_age = int(getattr(settings, "research_auth_max_age_seconds", 300))
    if issued_at > now or now - issued_at > max_age:
        return False
    bound = tuple(
        headers.get(f"x-cavaai-{part}")
        for part in ("nonce", "method", "path", "body-hash")
    )
    if any(part is not None for part in bound):
        if any(part is None for part in bound):
            return False
        nonce, method, path, body_hash = bound
        if (method or "").upper() != str(scope.get("method") or "").upper():
            return False
        if path != str(scope.get("path") or ""):
            return False
    else:
        nonce = method = path = body_hash = None
    expected = sign_research_identity(
        secret,
        tenant_id=tenant,
        user_id=user,
        timestamp=timestamp,
        nonce=nonce,
        method=method,
        path=path,
        body_hash=body_hash,
    )
    return hmac.compare_digest(expected, signature)


class AuthFailureLimitMiddleware:
    def __init__(self, app, limit: int = AUTH_FAILURE_LIMIT):
        self.app = app
        self.limit = limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        settings = get_settings()
        path = str(scope.get("path") or "")
        if not settings.rate_limit_enabled or is_exempt_path(path) or scope.get("method") == "OPTIONS":
            await self.app(scope, receive, send)
            return
        client = scope.get("client")
        ip = client[0] if client else "unknown"
        key = "cavaai:authfail:" + hashlib.sha256(ip.encode()).hexdigest()
        use_redis = not settings.is_local_environment
        try:
            failures = await _count_hits(key, use_redis=use_redis, redis_url=settings.redis_url)
        except Exception:  # noqa: BLE001 - el limite principal ya falla cerrado en prod
            failures = 0
        if failures >= self.limit and not _carries_valid_signature(scope, settings):
            from starlette.responses import JSONResponse

            response = JSONResponse(
                {"detail": "Too many failed authentication attempts"},
                status_code=429,
                headers={"Retry-After": str(WINDOW_SECONDS)},
            )
            await response(scope, receive, send)
            return

        status_holder: dict[str, int] = {}

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
            await send(message)

        await self.app(scope, receive, send_wrapper)
        if status_holder.get("status") == 401:
            try:
                await _record_hit(
                    key,
                    window_seconds=WINDOW_SECONDS,
                    use_redis=use_redis,
                    redis_url=settings.redis_url,
                    degrade_to_local=True,
                )
            except Exception:  # noqa: BLE001
                logger.warning("auth_failure_hit_not_recorded", exc_info=True)
