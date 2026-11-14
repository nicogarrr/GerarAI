# Latencia de endpoints de pantalla: banco local y observaciones de producción

## Alcance y límites

[Medido, fixture artificial local] Base f4969f0b5; candidato incluye el fix de
Temas y el lote de basics. SQLite + TestClient ASGI, Python 3.12, misma máquina,
30 muestras calientes secuenciales por ruta y tamaño (4 y 16 posiciones),
primera petición separada. No hay ráfagas ni peticiones nuevas a producción.
Las semillas NO son datos de Nico. El banco reutiliza la semilla existente
`test_perf_guard_query_budgets.py`: 90 sesiones, precios/FX/transacciones y
watchlist. Algunos recursos (noticias/documentos/revisiones) están vacíos.

SQL es tiempo de cursor, no hidratación ni serialización. El total incluye
middleware y TestClient, NO Next, TLS, red del navegador ni proveedor remoto.
Las respuestas 2xx entran en p50/p95 por rango más próximo. Los códigos,
muestras originales, primera petición, bytes sin comprimir y errores se
conservan en los JSON de evidencia, entregados por separado en el adjunto
`screen-endpoints-raw-evidence.zip` (no incluidos en el repositorio). p95 con N=30 es orientativo, no un SLO.

La red externa está bloqueada. Un 200 de proveedor caído puede contener un
estado vacío o degradado: no prueba frescura ni disponibilidad de la fuente.
Los contadores `blocked_network_attempts` lo hacen visible; cachés calientes
pueden reutilizar el fallback generado en la primera petición. El banco no
borra todas las cachés entre endpoints, ni afirma medir un arranque frío real.
`small` precede a `large`, y las cachés públicas pueden beneficiar al segundo.

No se declara cobertura del 100 % de la app: se midieron 45 rutas de las
siete pantallas. Quedan fuera las pestañas secundarias no enumeradas de
research, Next/server-actions, proveedores vivos y la zona protegida
(cerebro/tesis/valor intrínseco/DCA). No se cambian sus reglas. Los GET públicos
404 citados abajo NO son tiempos de las rutas internas del backend.

## Tabla local completa, candidato, 16 posiciones

| Endpoint interno | Pantallas | p50 ms | p95 ms | SQL p95 ms | Queries máx | Bytes máx | Intentos red bloqueados |
|---|---|---:|---:|---:|---:|---:|---:|
| `/api/screeners/real?limit=20` | screener | 61.69 | 62.12 | 0.06 | 3 | 132 | 0 |
| `/api/companies/{lead}/peers/comparison` | research | 21.95 | 22.29 | 0.62 | 18 | 33964 | 0 |
| `/api/watchlist/metrics/{lead}` | watchlist | 16.30 | 17.37 | 0.80 | 15 | 60 | 0 |
| `/api/watchlist/monitor?tickers={watch}` | watchlist | 16.39 | 16.76 | 0.37 | 11 | 4524 | 0 |
| `/api/market/indices` | screener | 16.06 | 16.50 | 0.08 | 3 | 322 | 155 |
| `/api/companies/{lead}/snapshot` | research | 14.91 | 15.16 | 0.58 | 10 | 1012 | 0 |
| `/api/portfolio/positions?page=1&page_size=200` | inicio, cartera, temas | 14.48 | 14.91 | 0.31 | 7 | 12206 | 0 |
| `/api/calendar/catalysts` | calendario | 14.16 | 14.55 | 0.20 | 8 | 1761 | 0 |
| `/api/portfolio/dividends/projection` | cartera | 13.52 | 13.88 | 0.24 | 7 | 6467 | 0 |
| `/api/portfolio/transactions/page?limit=50&offset=0` | cartera | 13.62 | 13.88 | 0.24 | 6 | 8700 | 0 |
| `/api/portfolio/summary` | inicio, cartera, watchlist | 12.96 | 13.63 | 0.19 | 6 | 709 | 0 |
| `/api/sources/documents?ticker={lead}&scope=all&include_chunks=false` | research | 13.11 | 13.33 | 0.27 | 5 | 2 | 0 |
| `/api/portfolio/forecast` | cartera | 12.91 | 13.31 | 0.18 | 6 | 4948 | 0 |
| `/api/companies/{lead}/facts?limit=250` | research | 12.71 | 13.29 | 0.21 | 5 | 11056 | 0 |
| `/api/watchlist` | inicio, watchlist, temas, screener | 12.90 | 13.21 | 0.14 | 5 | 3007 | 0 |
| `/api/portfolio/snapshots?page=1&page_size=200` | cartera | 12.56 | 13.08 | 0.25 | 7 | 117 | 0 |
| `/api/companies/{lead}/ttm` | research | 12.67 | 13.01 | 0.13 | 6 | 3664 | 0 |
| `/api/companies/{lead}/key-stats` | research | 12.50 | 12.74 | 0.16 | 7 | 281 | 0 |
| `/api/portfolio/dividends` | cartera | 12.53 | 12.73 | 0.15 | 5 | 4538 | 0 |
| `/api/portfolio/data-quality` | cartera | 12.47 | 12.67 | 0.18 | 7 | 490 | 0 |
| `/api/portfolio/tearsheet` | cartera | 12.02 | 12.67 | 0.17 | 5 | 438 | 0 |
| `/api/sources/audits?ticker={lead}` | research | 12.39 | 12.60 | 0.19 | 5 | 2 | 0 |
| `/api/news?ticker={lead}&limit=30` | research, inicio | 12.15 | 12.56 | 0.20 | 4 | 2 | 0 |
| `/api/calendar/followed` | calendario, inicio | 12.27 | 12.54 | 0.16 | 6 | 326 | 0 |
| `/api/market/flows/themes/centros-de-datos` | temas | 12.04 | 12.37 | 0.11 | 4 | 7391 | 0 |
| `/api/reviews?ticker={lead}` | research | 12.16 | 12.35 | 0.15 | 5 | 2 | 0 |
| `/api/companies/{lead}/metrics/calculated` | research | 11.92 | 12.19 | 0.16 | 5 | 60 | 0 |
| `/api/companies/basics?tickers={watch}` | watchlist, inicio | 11.52 | 12.15 | 0.13 | 4 | 819 | 0 |
| `/api/alerts?ticker={lead}&include_snoozed=true` | research | 11.90 | 12.08 | 0.18 | 5 | 2 | 0 |
| `/api/screeners/screens` | screener | 11.68 | 11.98 | 0.10 | 4 | 2 | 0 |
| `/api/market/movers?limit=10` | screener | 11.69 | 11.94 | 0.08 | 3 | 226 | 0 |
| `/api/alerts?limit=3` | inicio | 11.57 | 11.81 | 0.19 | 4 | 2 | 0 |
| `/api/market/flows/themes/utilities` | temas | 11.56 | 11.76 | 0.06 | 3 | 797 | 0 |
| `/api/market/changes?tickers={watch}` | watchlist | 11.60 | 11.75 | 0.08 | 3 | 32 | 0 |
| `/api/companies/{lead}/decision-journal` | research | 11.61 | 11.73 | 0.10 | 5 | 2 | 0 |
| `/api/market/flows/themes/defensa` | temas | 11.52 | 11.72 | 0.08 | 3 | 1378 | 0 |
| `/api/screeners/metric-coverage` | screener | 11.39 | 11.66 | 0.08 | 3 | 69 | 0 |
| `/api/companies/{lead}` | research | 11.25 | 11.51 | 0.10 | 4 | 301 | 0 |
| `/api/alerts/rules?active=true&limit=100&offset=0` | inicio | 11.17 | 11.40 | 0.14 | 4 | 2 | 0 |
| `/api/bottlenecks` | temas | 10.90 | 11.13 | 0.08 | 4 | 957 | 0 |
| `/api/market/flows/themes` | temas | 10.35 | 10.82 | 0.09 | 3 | 359 | 0 |
| `/api/calendar/ipos` | calendario | 9.51 | 10.66 | 0.09 | 3 | 194 | 0 |
| `/api/market/themes` | temas | 10.30 | 10.60 | 0.09 | 3 | 238 | 0 |
| `/api/calendar/dividends` | calendario | 9.66 | 9.89 | 0.07 | 3 | 427 | 0 |
| `/api/calendar/earnings` | calendario | 9.59 | 9.76 | 0.09 | 3 | 427 | 0 |

## Hallazgos y acciones

- [Medido] `/companies/basics` crecía de 5 a 11 sentencias SQL al pasar
  de 2 a 8 tickers exactos. El handler hacía resolve_company por ticker.
  El fix precarga sólo coincidencias exactas y conserva el resolver de alias
  intacto para los pendientes (incluye FIGI, clases y control de listado).
  No se sustituye por un resolver de lote cuya política pueda divergir.
- [Medido A/B, mismo entorno] Basics con 8 tickers: queries 11 -> 4;
  p50 12,592 -> 11,517 ms; p95 12,817 -> 12,149 ms. Los bytes son 819
  en ambos. La reducción de queries es determinista; el pequeño cambio
  temporal es sólo una observación de esta máquina, no una promesa en prod.
- [Medido] Comparación de peers encabeza el banco pequeño; payload ~34 KB,
  18 queries. El tiempo de cursor es muy inferior al total: no hay evidencia
  de que añadir índices/hilos resuelva ese tiempo. [Hipótesis] estudiar
  hidratación/serialización con volúmenes representativos antes de tocar.
- [Medido] Temas frío bloqueaba el hilo en compute; caché caducada ya tenía
  stale-while-revalidate. Prueba causal y arreglo no bloqueante en
  `themes-cold-2026-11-14.md`. El banco sin proveedor NO reproduce los 21,8 s.
- [Hipótesis] La espera SSR de detalles de flujos también contribuye a Temas;
  no hay spans de producción para repartir el tiempo entre llamadas. La
  coordinación de render progresivo corresponde al carril frontend.
- No se propone subir workers/hilos: no se midieron CPU/RAM de la VM y los
  datos aquí no justifican esa configuración. No se cambian rate limits.

## Producción: muestras recibidas del carril móvil

[Medido por revisión móvil, 14-nov-2026 CET, sesión QA, viewport 390×844].
No son muestras del backend interno. Una observación por fila, sin p50/p95.
Los estados 200 se deducen del render, no de una captura de status HTTP.

| Documento/recurso | TTFB ms | responseEnd ms | load ms | N | Límite |
|---|---:|---:|---:|---:|---|
| /temas, 11:23:42 | 291 | 21822 | 21860 | 1 | Primera visita; 0 XHR posteriores |
| /temas, visita posterior | N/D | ~4100 | N/D | 1 | No se conoce el estado exacto de caché |
| /watchlist, 11:24:36 | 345 | 10095 | 10122 | 1 | 7 fetch/RSC posteriores |
| /calendar, 11:23:42 | 337 | 2010 | 4970 | 1 | Documento, no backend aislado |
| /screeners, 11:24:20 | 358 | 5331 | 5381 | 1 | Distinto de la página /screener |

Recursos Next del inicio, 11:22:58: `/api/home/portfolio` duración 633 ms,
4684 B transferidos; `/api/home/alerts` 642 ms, 3696 B;
`/api/home/watchlist?limit=3` 814 ms, 823 B. N=1 cada uno.

Los sondeos públicos a `/api/market/themes`, `/api/market/flows/themes`,
`/api/bottlenecks`, `/api/portfolio/positions`, `/api/watchlist`,
`/api/companies/basics`, `/api/watchlist/monitor`, `/api/market/changes`,
`/api/portfolio/summary` y `/api/watchlist/dca-signals` devolvieron 404 en
190–258 ms, N=1: esa superficie pública no expone esas rutas. No son una
medición del endpoint interno ni un motivo para repetir la carga.

## Reproducir en entorno aislado

```sh
cd data-engine
LATENCY_REPORT=/tmp/latencia.json PYTHONPATH=.:tests python -m pytest \
  tests/test_screen_endpoint_latency.py -q -s
```

El banco no recibe URL externa. Importa conftest, que fuerza SQLite desechable,
y bloquea conexiones socket durante la medición. No ejecutar contra datos
personales ni presentar la fixture como una réplica. Para comparar fixes:
mismo manifiesto y semilla, guardar SHA y ambas salidas; la primera evidencia
de esta tanda cubre 40 rutas y la segunda añade 5 de flujos/proveedores.
Sólo se comparan rutas comunes. Tests nuevos de estadística: 100 % líneas;
fix de basics: 100 % de las líneas ejecutables cambiadas. Tests rojo-primero
basics: [2,16] queries donde se exige [1,1]; después 20 tests de ruta/resolver
verdes. Batería del banco y stats/ruta: 28 tests verdes.


## Ampliación de inventario (misma sesión aislada)

Se añadieron 19 GET secundarios de research y screeners, sin tocar zona
protegida: 64 rutas en total, 30 muestras por ruta/tamaño. Todos los HTTP
fueron 200; esto sigue sin validar contenido/frescura de recursos vacíos.
La evidencia ampliada no sustituye el A/B de basics: es un tercer recorrido
con manifiesto mayor, sin más cambios de backend. No debe mezclarse su
percentil con las muestras anteriores.

| Endpoint añadido | p50 ms | p95 ms | Queries máx | Bytes máx |
|---|---:|---:|---:|---:|
| `/api/companies/{lead}/financial-terminal` | 13.24 | 13.57 | 8 | 14624 |
| `/api/companies/{lead}/share-capital` | 12.00 | 12.43 | 6 | 130 |
| `/api/companies/{lead}/management-alignment` | 16.14 | 16.44 | 5 | 225 |
| `/api/companies/{lead}/management-credibility` | 11.39 | 11.62 | 5 | 200 |
| `/api/companies/{lead}/decision-lessons` | 11.44 | 11.71 | 5 | 2 |
| `/api/companies/{lead}/decision-lessons/taxonomy` | 10.97 | 11.30 | 4 | 244 |
| `/api/companies/{lead}/decision-journal/trades` | 11.89 | 12.20 | 6 | 351 |
| `/api/companies/{lead}/expectation-reality` | 11.62 | 11.95 | 5 | 2 |
| `/api/watchlist/news-preparing/{lead}` | 12.06 | 12.30 | 3 | 40 |
| `/api/ownership/schedule-13dg?ticker={lead}` | 11.51 | 11.87 | 4 | 561 |
| `/api/ownership/institutions/{lead}` | 11.54 | 11.78 | 5 | 738 |
| `/api/ownership/funds/{lead}` | 11.52 | 12.17 | 5 | 466 |
| `/api/investors/holders/{lead}` | 11.61 | 11.95 | 5 | 402 |
| `/api/insider/filings?ticker={lead}&limit=20` | 12.30 | 12.54 | 7 | 91 |
| `/api/insider/summary?ticker={lead}` | 11.38 | 11.55 | 4 | 409 |
| `/api/insider/ownership-signals?ticker={lead}` | 11.89 | 13.90 | 6 | 399 |
| `/api/politicians/ticker/{lead}` | 11.23 | 11.50 | 4 | 178 |
| `/api/paper-trading/proposals?ticker={lead}&limit=20` | 11.96 | 12.16 | 4 | 2 |
| `/api/screeners/custom-metrics` | 11.55 | 12.23 | 4 | 2 |

Pendiente para afirmar cobertura total: inventariar todas las variantes por
pestaña/parámetros y los endpoints privados de Next y proveedores, medir
con datasets no vacíos representativos, y disponer de trazas backend de
producción sin cargar el servidor. Las rutas protegidas (tesis/valor/DCA y
cerebro) se excluyen por instrucción, no se les asigna un tiempo supuesto.
La página `/screeners` también puede ejecutar POST ad-hoc si hay filtro;
no se simula ese flujo como si fuera un GET ni se dispara contra producción.
