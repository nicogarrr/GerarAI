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
| `externa` | ingesta 2, calculo 1 | `worker-externa` | `${EXTERNA_THREADS:-2}` |
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
