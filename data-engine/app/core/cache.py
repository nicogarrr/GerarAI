"""Redis caching decorator for market data, portfolio valuations, and DCA schedules.

Provides a unified caching layer with:
- 5-minute TTL for market data
- Dependency-based invalidation for portfolio valuations
- Cache hit rate tracking
- Fail-open behavior (degrades gracefully if Redis is unavailable)
- Tenant isolation

Expected cache hit rate >70% for repeated requests.
"""

from __future__ import annotations

import functools
import hashlib
import json
import logging
import threading
import time
from collections.abc import Callable
from typing import Any, ParamSpec, TypeVar, cast

logger = logging.getLogger(__name__)

P = ParamSpec("P")
T = TypeVar("T")

# TTL por tipo de dato
MARKET_DATA_TTL = 300  # 5 minutos
PORTFOLIO_VALUATION_TTL = 600  # 10 minutos
DCA_SCHEDULE_TTL = 300  # 5 minutos

# Prefijos de cache
MARKET_DATA_PREFIX = "market_data"
PORTFOLIO_VALUATION_PREFIX = "portfolio_valuation"
DCA_SCHEDULE_PREFIX = "dca_schedule"

# Metricas de cache
_cache_stats: dict[str, dict[str, int]] = {
    "market_data": {"hits": 0, "misses": 0},
    "portfolio_valuation": {"hits": 0, "misses": 0},
    "dca_schedule": {"hits": 0, "misses": 0},
}
_stats_lock = threading.Lock()

# Cliente Redis con backoff
_redis_state: dict[str, Any] = {
    "client": None,
    "down_until": 0.0,
}
_REDIS_BACKOFF_S = 30.0


def _redis_client():
    """Cliente Redis con timeouts cortos; None sin URL o en backoff tras un fallo."""
    if time.monotonic() < _redis_state["down_until"]:
        return None
    if _redis_state["client"] is not None:
        return _redis_state["client"]
    try:
        import redis as _redis_lib

        from app.core.config import get_settings
        from app.core.redis_retry import no_retry

        url = get_settings().redis_url
        if not url:
            return None
        client = _redis_lib.from_url(
            url, socket_connect_timeout=0.5, socket_timeout=0.5, retry=no_retry()
        )
        client.ping()  # Verificar conectividad
    except Exception as exc:
        logger.warning(f"Redis unavailable for caching: {exc}")
        _redis_down()
        return None
    _redis_state["client"] = client
    return client


def _redis_down() -> None:
    """Marca Redis como caido y activa el backoff."""
    _redis_state["client"] = None
    _redis_state["down_until"] = time.monotonic() + _REDIS_BACKOFF_S


def _tenant_from_db(db) -> int | None:
    """Extrae tenant_id de db.info o None."""
    if hasattr(db, 'info'):
        return db.info.get("tenant_id")
    return None


def _make_cache_key(prefix: str, tenant_id: int | None, *args: Any, **kwargs: Any) -> str:
    """Genera clave de cache con aislamiento por tenant."""
    # Tenant en la clave para aislamiento
    tenant_part = f"tenant:{tenant_id}" if tenant_id else "unscoped"
    
    # Serializar args y kwargs de forma determinista
    key_data = {
        "args": args,
        "kwargs": {k: v for k, v in sorted(kwargs.items())},
    }
    key_json = json.dumps(key_data, sort_keys=True, default=str)
    key_hash = hashlib.sha256(key_json.encode()).hexdigest()[:16]
    
    return f"{prefix}:{tenant_part}:{key_hash}"


def _record_hit(category: str) -> None:
    """Registra un cache hit en las metricas."""
    with _stats_lock:
        _cache_stats[category]["hits"] += 1


def _record_miss(category: str) -> None:
    """Registra un cache miss en las metricas."""
    with _stats_lock:
        _cache_stats[category]["misses"] += 1


def get_cache_stats() -> dict[str, dict[str, Any]]:
    """Devuelve estadisticas de cache con hit rate."""
    with _stats_lock:
        stats = {}
        for category, counts in _cache_stats.items():
            hits = counts["hits"]
            misses = counts["misses"]
            total = hits + misses
            hit_rate = (hits / total * 100) if total > 0 else 0.0
            stats[category] = {
                "hits": hits,
                "misses": misses,
                "total": total,
                "hit_rate": hit_rate,
            }
        return stats


def reset_cache_stats() -> None:
    """Resetea las metricas de cache (para tests)."""
    with _stats_lock:
        for category in _cache_stats:
            _cache_stats[category] = {"hits": 0, "misses": 0}


def invalidate_portfolio_cache(tenant_id: int | None = None, db=None) -> None:
    """Invalida cache de valoraciones de cartera por tenant.
    
    Args:
        tenant_id: ID del tenant a invalidar, o None para invalidar todo.
        db: Session opcional para extraer tenant_id de db.info.
    """
    if tenant_id is None and db is not None:
        tenant_id = _tenant_from_db(db)
    client = _redis_client()
    if client is None:
        return
    
    try:
        if tenant_id is not None:
            # Invalidar solo este tenant
            pattern = f"{PORTFOLIO_VALUATION_PREFIX}*:tenant:{tenant_id}:*"
        else:
            # Invalidar todo
            pattern = f"{PORTFOLIO_VALUATION_PREFIX}:*"
        
        cursor = 0
        while True:
            cursor, keys = client.scan(cursor, match=pattern, count=100)
            if keys:
                client.delete(*keys)
            if cursor == 0:
                break
        logger.info(f"Invalidated portfolio cache for tenant_id={tenant_id}")
    except Exception as exc:
        logger.warning(f"Failed to invalidate portfolio cache: {exc}")
        _redis_down()


def invalidate_market_data_cache() -> None:
    """Invalida toda la cache de datos de mercado."""
    client = _redis_client()
    if client is None:
        return
    
    try:
        pattern = f"{MARKET_DATA_PREFIX}:*"
        cursor = 0
        while True:
            cursor, keys = client.scan(cursor, match=pattern, count=100)
            if keys:
                client.delete(*keys)
            if cursor == 0:
                break
        logger.info("Invalidated market data cache")
    except Exception as exc:
        logger.warning(f"Failed to invalidate market data cache: {exc}")
        _redis_down()


def invalidate_dca_cache(tenant_id: int | None = None, db=None) -> None:
    """Invalida cache de schedules DCA por tenant.
    
    Args:
        tenant_id: ID del tenant a invalidar, o None para invalidar todo.
        db: Session opcional para extraer tenant_id de db.info.
    """
    if tenant_id is None and db is not None:
        tenant_id = _tenant_from_db(db)
    client = _redis_client()
    if client is None:
        return
    
    try:
        if tenant_id is not None:
            pattern = f"{DCA_SCHEDULE_PREFIX}*:tenant:{tenant_id}:*"
        else:
            pattern = f"{DCA_SCHEDULE_PREFIX}:*"
        
        cursor = 0
        while True:
            cursor, keys = client.scan(cursor, match=pattern, count=100)
            if keys:
                client.delete(*keys)
            if cursor == 0:
                break
        logger.info(f"Invalidated DCA cache for tenant_id={tenant_id}")
    except Exception as exc:
        logger.warning(f"Failed to invalidate DCA cache: {exc}")
        _redis_down()


def cached(
    *,
    prefix: str,
    ttl: int,
    category: str,
    extract_tenant: Callable[[Any, Any], int | None] | None = None,
) -> Callable[[Callable[P, T]], Callable[P, T]]:
    """Decorator para cachear resultados en Redis con fail-open.
    
    Args:
        prefix: Prefijo de la clave de cache.
        ttl: Time-to-live en segundos.
        category: Categoria para metricas (market_data, portfolio_valuation, dca_schedule).
        extract_tenant: Funcion opcional para extraer tenant_id de los argumentos.
    
    Returns:
        Decorator que cachea la funcion.
    """
    def decorator(func: Callable[P, T]) -> Callable[P, T]:
        @functools.wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            # Extraer tenant_id del primer argumento Session (db)
            tenant_id = None
            if len(args) >= 2 and hasattr(args[1], 'info'):  # args[0] es self, args[1] es db
                tenant_id = _tenant_from_db(args[1])
            
            if extract_tenant is not None and tenant_id is None:
                try:
                    tenant_id = extract_tenant(args, kwargs)  # type: ignore[arg-type]
                except Exception:
                    # nosemgrep: gerarai-broad-except-pass -- extraccion opcional de tenant_id; degrada a None de forma segura
                    pass
            
            # Filtrar self y Session para una clave determinista entre requests
            clean_args = []
            for i, arg in enumerate(args):
                if i == 0 and hasattr(arg, func.__name__):
                    continue
                if hasattr(arg, "info") and (hasattr(arg, "execute") or hasattr(arg, "scalars")):
                    continue
                clean_args.append(arg)

            clean_kwargs = {
                k: v for k, v in kwargs.items()
                if k not in ("db", "session") and not (hasattr(v, "info") and hasattr(v, "scalars"))
            }

            # Generar clave de cache
            cache_key = _make_cache_key(prefix, tenant_id, *clean_args, **clean_kwargs)
            
            # Intentar leer de cache
            client = _redis_client()
            if client is not None:
                try:
                    cached_value = client.get(cache_key)
                    if cached_value is not None:
                        _record_hit(category)
                        result = json.loads(cached_value)
                        if isinstance(result, dict) and result and all(isinstance(k, str) and k.isdigit() for k in result):
                            result = {int(k): v for k, v in result.items()}
                        logger.debug(f"Cache hit: {cache_key}")
                        return cast(T, result)
                except Exception as exc:
                    logger.debug(f"Cache read failed for {cache_key}: {exc}")
                    _redis_down()
            
            # Cache miss: ejecutar funcion
            _record_miss(category)
            result = func(*args, **kwargs)
            
            # Guardar en cache
            if client is not None:
                try:
                    serialized = json.dumps(result, default=str)
                    # redis-py depreco setex (DeprecationWarning desde 2.6.12): set con ex=ttl
                    client.set(cache_key, serialized, ex=ttl)
                    logger.debug(f"Cached result: {cache_key} (TTL={ttl}s)")
                except Exception as exc:
                    logger.debug(f"Cache write failed for {cache_key}: {exc}")
                    _redis_down()
            
            return result
        
        return wrapper
    return decorator
