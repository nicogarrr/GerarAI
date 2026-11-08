# Backlog Dramatiq: admision atomica y carriles aislados

Base auditada: bc11ea711fd42ef2d539479f160afdf278f8e907.

Los carriles ya estaban separados por proceso: default, prices, KPI (4
hilos), thesis (2), alerts (2, colas alerts+computed), GDELT (2). Los hilos
de default y prices son configurables con `WORKER_THREADS` (defectos 4 y 2 en
`docker-compose.prod.yml`). Un proceso por servicio, con pool SQLAlchemy por
proceso segun `docker-compose.prod.yml`: workers 4+2 y worker principal 8+2
(`WORKER_DB_POOL_SIZE` / `WORKER_DB_MAX_OVERFLOW`), backend 20+10
(`DB_POOL_SIZE`; overflow 10 por defecto de `config.py`). Los defaults
nativos de `config.py` (10+10) quedan sobrescritos por el compose. No
equivale a un presupuesto global fijo: la suma de procesos puede abrir mas
conexiones.
Esta PR no sube procesos, hilos, memoria ni el pool. No demuestra capacidad
fisica de la VM 2 OCPU / 12 GB: no ejecuta carga ni despliega en produccion.

## Fallos cerrados

- El read-then-send permitia sobrepasar el limite con productores simultaneos.
  Un script Lua admite y encola el mensaje KPI atomico en Redis, con ID y
  payload compatibles con Dramatiq 1.x. Los tests lo consumen y hacen ack
  con el consumidor nativo, no solo inspeccionan la lista.
- El limite incluye hashes de trabajos listos, en curso y diferidos por retry.
  Redis no disponible es N/D, nunca cero. Backfill se detiene ante N/D.
- Antes de enviar se persiste `kpi_deferred` en el documento. Cola llena deja
  el documento elegible para backfill. Timeout conserva la reserva porque
  el envio puede haber sido aceptado. La regla existente de cola vacia +
  lease vencido reconcilia esos envios, sin reenviar durante backlog.
- Si otro productor llena la cola durante backfill, se restaura el intento
  y se detiene el lote. Un rechazo por capacidad no consume intentos.
- Los reintentos/promociones siguen el broker nativo: no se descarta trabajo
  ya aceptado. Pueden superar temporalmente el tope durante retry/promocion;
  en ese estado no se admiten documentos nuevos. No es un limite duro de RAM.

Configuracion compartida por productores: `KPI_QUEUE_MAX_PENDING=500`,
`KPI_DEFER_LEASE_SECONDS=900`. El worker KPI mantiene 4 hilos y limita el
prefetch local normal/diferido a 4. Backfill sigue cada 5 minutos. No se
purga ninguna cola ni documento. Documentos agotados conservan su flag.

## Benchmark reproducible, sintetico (no datos de produccion)

```sh
cd data-engine
python scripts/benchmark_backlog.py
pytest tests/test_bounded_broker.py tests/test_kpi_backpressure.py
```

Requiere `redis-server` local. El script crea un socket privado temporal,
sin TCP, sin persistencia, sin conexiones a Postgres o LLM y sin endpoints
externos. El resultado medido esta en
`docs/benchmarks/dramatiq-backlog-synthetic.json`.

80 jobs simulados, 40 ms de espera por job, 16 productores concurrentes:
cola compartida admitio 80; carriles aislados admitieron 20 y difirieron 60.
Latencia de alerta: 810.84 ms compartida frente a 1.94 ms aislada. Drenaje
del lote ADMITIDO: 821.09 ms frente a 210.52 ms. No comparar ese drenaje como
throughput total: el segundo caso solo ejecuta 20 jobs. El caso aislado usa
4 hilos KPI + 1 alerta, el compartido 4 hilos, y los jobs son esperas sinteticas.
La prueba demuestra aislamiento y admision bajo concurrencia, no velocidad
LLM ni ausencia de todos los posibles cuellos de botella.

## Gate y despliegue pendientes del integrador

CI backend instala Redis para que las pruebas Lua no se omitan. En entornos
sin binario esas pruebas se saltan explicitamente. No hay nuevas dependencias
Python. OpenAPI y tipos TS se regeneran: sin cambios porque no cambia la API.

Despues del merge autorizado: reconstruir imagen backend y recrear todos los
productores/consumidores con la misma version; no mezclar broker anterior y
nuevo, pues productores antiguos no aplican admision atomica. Comprobar las
colas/latencias reales y memoria/CPU en VM, que no se midieron aqui. Si se
revierte, documentos diferidos siguen persistidos y backfill antiguo puede
recuperarlos; reaparece la carrera de admision. No purgar para hacer rollback.
