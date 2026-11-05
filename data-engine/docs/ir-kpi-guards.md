# Corte de repetición IR/KPI

`KPI_EXTRACTION_CALLS_PER_DAY` limita intentos de la extracción KPI principal por tenant y día UTC. Defecto:20. Los fallos del proveedor también cuentan. Redis hace la reserva atómica en producción y su fallo impide esa llamada. El exceso devuelve `status=deferred, reason=daily_call_limit`; el documento conserva `metadata.kpi_deferred` con `not_before` al siguiente día UTC y `metadata.kpi_daily_deferred` con fecha/motivo. El backfill no consume reintentos antes de ese momento. No elimina candidatos ni cambia valores.

Las fuentes IR con URL page-not-found/not-found/404, título/h1 de error o página corta de error no llegan al parser ni al LLM. Los HTTP404/410 ya se rechazan por raise_for_status del fetch público. Las fechas y cifras del negocio no se eliminan: la normalización HTML ignora scripts/styles/atributos (nonces/tokens) y ruido técnico explícitamente etiquetado. PDFs conservan hash de bytes. Digest IR por URL+empresa+tenant; ninguna compartición entre tenants. Un documento con candidatos ya existentes no vuelve a pagar extracción, ni modifica su aprobación.

El sondeo omite las empresas no seguidas antes de llamar al conector. Sigue faltando una reserva distribuida de URL pendiente: dos ticks antes de persistir la URL aún pueden encolar dos mensajes. El actor de ingesta ya deduplica URLs persistidas; esta PR no promete exactamente una ejecución en concurrencia ni modifica el broker.

## Contrafactual, no ahorro de tokens medido

Desde `data-engine`, ejecutar en un export privado:

```
PYTHONPATH=. python scripts/ir_kpi_counterfactual.py export.jsonl 20
```

El export867IR (5nov2026) trae hashes del texto normalizado por whitespace, no texto ni statusHTTP/URLfinal verificados. Con namespace tenant+URL+hash:

-126URLs page-not-found descartables por ruta.
-1duplicado adicional dentro de tenant.
-460trabajos diferidos por cap diario, NO eliminados.
-280llamadas candidatas restantes.

Los99hashes globales NO prueban ahorro88,6% aplicable: no se comparte entre tenants. SinFK entre llamada y documento no se puede atribuir tokens ahorrados. Sin texto bruto no se puede ejecutar la normalización nueva sobre este export; el contador declara cuándo usa hashes ya exportados. El cap empieza desde la activación: no reconstruye consumo anterior de budget_usage.
