# Invalidación global de la caché de mercado

La caché de mercado (Redis, prefijo `market_data:*`) es **compartida entre
tenants**. Las rutas `POST /api/cache/invalidate/market-data` y
`POST /api/cache/invalidate/all` la vacían para todos; por eso van detrás
del gate `cache_global_invalidation_allowed`:

| Entorno | Defecto | Ruta HTTP |
| --- | --- | --- |
| producción | **cerrado** | 404 (como si no existiera) |
| local / dev / test / ci | abierto | funciona |

- Variable: `CACHE_GLOBAL_INVALIDATION_ENABLED` (`true`/`false`). Explícita,
  manda sobre el defecto en cualquier entorno.
- Con el gate cerrado, invalidar desde ops:

  ```bash
  cd data-engine
  python scripts/invalidate_market_cache.py
  ```

  El script usa la `REDIS_URL` del entorno y borra el prefijo
  `market_data:*` (misma función `app.core.cache.invalidate_market_data_cache`
  que la ruta).

- Las invalidaciones **por tenant** (`/invalidate/portfolio`,
  `/invalidate/dca`) NO van detrás del gate: solo afectan al tenant firmado.

Motivo: cualquier identidad firmada podía dejar fría la caché global y
provocar re-fetch masivo contra yfinance/SEC (degradación para todos los
tenants).
