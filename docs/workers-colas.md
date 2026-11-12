# Mapa de colas Dramatiq: clase logica -> cola fisica -> worker desplegado

Tabla prometida desde `app/workers/queue_taxonomy.py`. Derivada del codigo
vivo (nov 2026): colas declaradas por los actores (`broker.get_declared_queues()`),
clase segun `ACTOR_CLASS` y consumidores segun `docker-compose.prod.yml` y
`docker-compose.ibkr-sync.yml`. El test `tests/test_queue_consumers.py`
rompe si una cola declarada queda sin consumidor o sin fila aqui.

Clases (definicion completa en el docstring de `queue_taxonomy.py`):

- **interactiva**: el usuario espera el resultado. Fallo rapido y visible.
- **ingesta**: fuentes externas, idempotente, DL tras 3 fallos.
- **calculo**: trabajo pesado sobre datos ya ingeridos.
- **mantenimiento**: alertas, recordatorios, watchdogs, reconciliaciones.

## Colas declaradas y sus consumidores

| Cola | Actores por clase | Servicio consumidor | Hilos |
| --- | --- | --- | --- |
| `default` | ingesta 24, calculo 10, interactiva 1 | `worker` | `${WORKER_THREADS:-4}` |
| `prices` | ingesta 2 | `worker-prices` | `${WORKER_THREADS:-2}` |
| `externa` | ingesta 2, calculo 1 | `worker-externa` | `${EXTERNA_THREADS:-2}` compartidos con sec |
| `sec` | ingesta 1 | `worker-externa` (`-Q externa sec`) | mismo proceso/hilos, sin recursos adicionales |
| `finnhub` | ingesta 1 | `worker-finnhub` | `${FINNHUB_THREADS:-2}` |
| `yahoo` | ingesta 6 | `worker-yahoo` | `${YAHOO_THREADS:-2}` |
| `gdelt` | ingesta 2 | `worker-gdelt` | 2 |
| `documents` | interactiva 2, ingesta 1 | `worker-documents` | `${DOCUMENTS_THREADS:-1}` |
| `knowledge` | interactiva 1 | `worker-knowledge` | 1 |
| `official-closes` | ingesta 1 | `worker-official-closes` | 1 |
| `dca-manual` | interactiva 1, calculo 1 | `worker-dca-manual` | 1 |
| `kpis` | calculo 2 | `worker-kpis` | 4 |
| `computed` | calculo 4, ingesta 1 | `worker-alerts` (`-Q alerts computed`) | 2 |
| `alerts` | mantenimiento 10 | `worker-alerts` | 2 |
| `thesis` | interactiva 2 | `worker-thesis` | 2 |
| `ibkr-sync` | interactiva 2 | `worker-ibkr-sync` (overlay opt-in) | 1 |

Notas:

- `worker-alerts` consume DOS colas: el CLI de Dramatiq acepta varios
  valores tras `-Q` (`nargs="*"`), asi que `computed` viaja con `alerts`
  en el mismo proceso de 2 hilos.
- `ibkr-sync` NO tiene consumidor en `docker-compose.prod.yml` a proposito:
  la sync dedicada de IBKR es opt-in y se despliega con
  `docker-compose.ibkr-sync.yml` (+384 MiB; requiere rebalance medido
  antes de activarse, PR #2773). Sin el overlay, los mensajes encolados
  esperan en Redis; no expiran (ningun actor usa `max_age`).
- `yahoo-news` no la declara ningun actor: es la cola efimera del primer
  despliegue de #3763 y `worker-yahoo` la consume solo para drenar los
  mensajes residuales (transicion fijada en `tests/test_provider_lanes.py`).
## Inspeccion operativa rapida

- Pendientes por cola: `LLEN dramatiq:<cola>` (mas `dramatiq:<cola>.DQ`
  para reintentos diferidos; el namespace por defecto es `dramatiq`).
- Dead-letter real: `ZCARD <namespace>:<cola>.XQ` (ojo: `.DQ` es la cola
  DELAYED, no la dead-letter; detalles en el docstring de la taxonomia).
- Watchdog de colas: `app/services/queue_watchdog.py` alerta en la app
  cuando una cola declarada supera su umbral de pendientes.

## SEC: lotes y aislamiento del worker default

`refresh_sec_filings` se enruta a `sec`, consumida por el worker externa
existente. Comparte sus 2 hilos por defecto: no es un worker SEC dedicado,
no aumenta RAM/CPU ni garantiza aislamiento de otros jobs externa.
`review_theses` y el resto de tesis/cerebro/DCA no cambian.

Cada mensaje trata hasta 3 empresas con CIK ordenadas por ticker. Tras 60s
no inicia otra; cada poll asincrono tiene timeout30s (incluye pacing/retries)
y el hard limit del actor es180s. La ingesta sincrona en vuelo puede superar
el presupuesto blando; no se promete un deadline duro de60s. El SECClient
conserva el pacer global Redis, cuota, cooldown y Retry-After sin alteraciones.
No hay fanout: una continuacion por lote con tenant/user/ticker, cursor y
presupuesto de documentos restante. No se multiplica el maximo de documentos
al partir una pasada. Los fallos por empresa quedan visibles y se revisitan
en la siguiente pasada programada; no se reintentan en un bucle inmediato.
El cursor en el mensaje es el checkpoint entre lotes. Un crash dentro del
lote puede repetir hasta3 empresas (ingesta con dedup existente), no reanuda
exactamente tras cada commit de empresa.

Rollout pendiente de autorizacion: cambiar el actor no mueve los mensajes
que ya llevan queue_name=default en Redis. Operaciones debe inspeccionarlos
y decidir drenaje o reencolado preservando payload/tenant antes de afirmar
que todo el backlog SEC quedo aislado. No hacer purgas genericas. Verificar
consumer de sec, profundidad/edad default y externa y ausencia de600s SEC.
No hay deploy ni migracion de cola en este PR.
