# Fuzzing de la API (Schemathesis) y sondas de seguridad

## Qué hay

| Fichero | Qué comprueba | Dónde corre |
|---|---|---|
| `data-engine/tests/fuzz/test_schemathesis_api.py` | Cada operación del OpenAPI (≈326) con ejemplos generados, firmados con la auth estricta real. Falla con cualquier 500 no controlado. `FUZZ_STRICT=1` añade conformidad de esquema y códigos. | Workflow `api-fuzz` (manual + nocturno, no bloquea) |
| `data-engine/tests/fuzz/test_schemathesis_stateful.py` | Modo stateful: cadenas de llamadas unidas por links (crear → editar → ejecutar → borrar) con ids reales devueltos por la API. | Workflow `api-fuzz` |
| `data-engine/tests/test_auth_required_everywhere.py` | Recorre TODAS las rutas del esquema: sin firma, firma caducada, firma de otra ruta y de otro método → 401. Una ruta nueva sin `private_dependencies` lo rompe. | Suite normal (≈15 s) |
| `data-engine/tests/test_cross_tenant_probes.py` | Usuario A crea; usuario B intenta leer, editar y borrar cada recurso (transacciones, filtros, acciones corporativas, plan, memoria, colecciones, propuestas, diario, watchlist, promesas, Telegram). Nunca 2xx con datos de A. | Suite normal (≈10 s) |
| `data-engine/tests/test_ssrf_url_params.py` | Cada parámetro URL que el servidor descarga o usa de base recibe 13 variantes internas (127.0.0.1, decimal, hex, IPv6 mapeada, `127.1`, `0.0.0.0`, nip.io, metadata 169.254…) apuntando a un canario local: 4xx y cero conexiones. | Suite normal (≈10 s) |

## Ronda 3 (29-oct): el fuzzing estaba casi ciego

- **Límite de peticiones**: todas las peticiones salen del mismo tenant e IP, así que a los pocos segundos casi todo era 429 (9.889 de 25.904 respuestas) y 200 de 329 operaciones no llegaron nunca al handler. `fuzz_app` desactiva el límite (tiene sus propios tests).
- **Datos**: el tenant del fuzzing arranca con cartera (USD y EUR, con ventas y recompra), plan, política DCA, tesis con versiones y una propuesta simulada anclada.
- **Tickers reales**: la mitad de los `{ticker}`/`{symbol}` generados son tickers del maestro sembrado; antes todos eran aleatorios y respondían 404.
- `tests/fuzz/test_schemathesis_r3.py`: modos positivo + negativo y, en cualquier respuesta ≥400, ningún texto interno (traceback, ruta de fichero, clase de excepción, SQL). `FUZZ_STATS=fichero.tsv` guarda operación y código de cada respuesta para ver qué operaciones no llegan al handler.
- `tests/test_cross_tenant_new_endpoints.py`: aislamiento A/B en los endpoints nuevos (política DCA, proyección de ahorro, bandeja de cambios de tesis, ejecuciones DCA manuales, propuestas por ticker con tesis anclada, lecturas de tesis/memo, regenerar informe fiscal).

## Ejecutar en local

```bash
cd data-engine
uv pip install "schemathesis>=4.3,<5"
RUN_FUZZ=1 APP_ENV=test FUZZ_MAX_EXAMPLES=5 python -m pytest tests/fuzz -n 8 -p no:randomly
```

Sin `RUN_FUZZ=1` el directorio no se recoge (fuzz_app parchea red y auth a nivel de módulo y contaminaría la suite normal).

Variables: `FUZZ_MAX_EXAMPLES` (por operación, 5 por defecto), `FUZZ_STATEFUL_EXAMPLES` / `FUZZ_STATEFUL_STEPS`, `FUZZ_DERANDOMIZE=0` para semillas nuevas, `FUZZ_STRICT=1`, `FUZZ_REPORT=fichero.jsonl` (una línea por fallo con el traceback del servidor).

La red saliente está cortada en el fuzzing (sin Yahoo, SEC ni LLM): un handler que dependa de red debe responder un error controlado, no 500.

## Bugs que encontró (oct 2026)

- #2595: filtro de screener con nombre repetido → 500; ahora 400, y los archivados liberan el nombre.
- #2601: offset/ids más allá de un BIGINT → 500 en ~20 rutas; ahora 422.
- #2606: importes de transacción que no caben en la columna → 500 y posición envenenada; ahora 422.
- #2626: dos aportaciones al plan con `external_id` vacío → 500 (UNIQUE); ahora el vacío se guarda como NULL.

- #2894: `POST /api/companies/{ticker}/kpi-registry/sync` → 500 la primera vez en el marco software_ai (dos etiquetas con la misma metric_key).
- #2895: proveedor externo caído (FRED, Yahoo) → 500 en `refresh/wacc` y `refresh/yahoo-fundamentals`; ahora 502 controlado.

Las sondas de aislamiento, bypass de auth y SSRF no encontraron fugas; quedan como regresión.
