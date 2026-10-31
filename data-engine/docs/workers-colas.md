# Colas Dramatiq por tipo de trabajo

Taxonomia canonica en `app/workers/queue_taxonomy.py` (`ACTOR_CLASS`), con
contrato en `tests/test_worker_retry_policy.py`: todo actor nuevo debe
clasificarse o el test falla.

La clasificacion es logica, no un redespliegue: no hay 4 colas nuevas. Las
colas fisicas y los workers del compose son los que ya existian; la tabla
siguiente solo mapea cada clase a donde corre hoy ese trabajo.

## Clases y colas fisicas

| Clase | Colas | Worker (docker-compose.prod.yml) |
| --- | --- | --- |
| interactiva (el usuario espera) | dca-manual, ibkr-sync, knowledge, thesis | worker-dca-manual, worker (compose ibkr-sync), worker-knowledge, worker-thesis |
| ingesta (fuentes externas, idempotente) | prices, official-closes, gdelt, default, knowledge | worker, worker-official-closes, worker-gdelt, worker-knowledge |
| calculo (pesado sobre datos ingeridos) | kpis, computed, thesis, default | worker-kpis, worker-alerts (computed), worker-thesis |
| mantenimiento (alertas, watchdogs) | alerts, default | worker-alerts |

## Politica de fallos

1. **Transitorio vs permanente**: `_handle_actor_error` relanza solo errores
   transitorios (timeouts, cortes, 429/5xx, Redis/Postgres caidos); los
   permanentes quedan registrados como fallo estructurado sin quemar
   reintentos.
2. **Reintentos con backoff**: ingesta declara `max_retries=2` +
   `min_backoff` (3 intentos totales). Los `Retry` internos con `delay`
   explicito (IBKR `not_ready`, GDELT 429) mandan sobre el backoff.
3. **Dead-letter tras 3 fallos**: agotados los reintentos, el broker Redis
   mueve el mensaje a `<namespace>:<cola>.XQ` (zset ordenado por instante de
   dead-letter; el payload queda en `<cola>.XQ.msgs`) y lo conserva
   `dead_message_ttl` (7 dias por defecto en Dramatiq 2.x). OJO: `<cola>.DQ`
   NO es la dead-letter, es la cola DELAYED (reintentos con backoff y envios
   con delay). Inspeccion: `ZCARD <namespace>:<cola>.XQ`; reencolado manual
   moviendo el mensaje de `.XQ.msgs` de vuelta a `<cola>.msgs`.
4. **Sin caducidad en cola**: ningun actor declara `max_age`; un mensaje
   aceptado no expira esperando worker (contrato en el test).

## Importaciones aceptadas: time_limit

El default implicito de Dramatiq (10 min) mataba importaciones largas a
mitad. Suelo declarado (`IMPORT_ACTORS`):

| Actor | time_limit |
| --- | --- |
| sync_ibkr_flex (import global Flex) | 60 min |
| sync_one_tenant_ibkr(_dedicated) | 30 min |
| ingest_knowledge_source | 60 min |
| sync_official_closes | 60 min |

Los backfills de datos mantienen sus limites medidos (5-30 min por lote).
