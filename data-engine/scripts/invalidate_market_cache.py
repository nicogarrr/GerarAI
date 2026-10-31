#!/usr/bin/env python3
"""Invalida la caché GLOBAL de datos de mercado (acción de operador).

Sustituto de las rutas POST /api/cache/invalidate/market-data e
/invalidate/all cuando el gate de producción
(CACHE_GLOBAL_INVALIDATION_ENABLED, omiso = apagado en producción) las
devuelve 404: la caché de mercado es compartida entre tenants y vaciarla
por HTTP quedó restringido a entornos no productivos.

Uso (desde data-engine/, con DATABASE_URL/REDIS_URL del entorno):
    python scripts/invalidate_market_cache.py
"""

from __future__ import annotations

import sys


def main() -> int:
    from app.core.cache import invalidate_market_data_cache

    deleted = invalidate_market_data_cache()
    if deleted is None:
        print(
            "ERROR: Redis no disponible o fallo el borrado; la cache de mercado NO se ha invalidado.",
            file=sys.stderr,
        )
        return 1
    print(f"Cache global de mercado invalidada: {deleted} claves borradas (prefijo market_data:*).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
