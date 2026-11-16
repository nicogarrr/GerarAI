# Posiciones institucionales nuevas por ticker

Revisión independiente sobre main 51a25e5b. Extensión aditiva de GET /api/ownership/institutions/{ticker}.
No hace falta nuevo endpoint: lectura local existente, CUSIP verificado exacto.

## Contrato para Watchlist/Cartera

new_positions: {status, count, value_known_count, top_by_shares, top_by_value,
value_basis}. Cada top tiene hasta 10 gestores, con cik/name/shares/prev_shares,
value_usd (nullable), accession/filed/filing_url/prev_filing_url y
value_filing_urls (incluye enmiendas que contribuyen al agregado).

Usar period/prior_period y source del objeto padre. count es total de NUEVAS,
no longitud del top. nuevo requiere 13F válido previo del gestor sin el CUSIP;
sin_13f_previo NO es nueva. Las listas nuevas se calculan ANTES del cap, no
filtrando buyers/top_holders, que podrían excluir nuevas importantes por valor.

status ok = detalle disponible y todos los valores nuevos conocidos;
valor_parcial = falta algún VALUE, la lista por valor ordena sólo conocidos;
sin_detalle = snapshot legado, count conocido pero no se afirma top vacío;
sin_datos = no snapshot/CUSIP elegible, count/value_known_count son NULL.
Cero nuevas con snapshot completo sí es count=0, listas vacías, status=ok.

VALUE es el declarado al cierre de trimestre, NO precio actual ni compra
monetaria inferida. USD nearest dollar desde filing 2023-01-03, antes miles
multiplicados por 1000. Regla basada en fecha de filing, no period_end.
Fuente SEC: https://www.sec.gov/filergroup/announcements-old/edgar-release-2241
(leída 16-nov-2026). No corrige errores de escala del declarante por heurística.
Si falta/negativo/no-finito un VALUE contribuyente, el total de ese CUSIP es
N/D, no suma parcial. RESTATEMENT reemplaza y NEW HOLDINGS suma conservando N/D.

## Persistencia y compatibilidad

Sin migraciones, tablas o índices nuevos. Añade hechos públicos al snapshot
existente. Checksum de versión n1: +61 hex, cabe en VARCHAR64, permite al job
semanal recalcular snapshots legados aunque ZIP no haya cambiado; no se ejecutó
job real ni se borran históricos. Lectura no descarga ZIP ni encola trabajos.
Primera actualización autorizada hará página+2ZIP como ya hacía el job.

Roles nuevos usan prefijo new_role para que rollback ignore el dato sin
KeyError. VALUE se guarda antes del hecho shares para que el loop antiguo,
que trataba métricas desconocidas como current, conserve cantidad correcta.
Un test congela esa interpretación antigua. Aun así, cualquier rollback de
escritura debe considerar reingestas del job; no se ha desplegado nada aquí.

## Pruebas y coste

Revisión independiente:123 tests verdes en16ficheros del comando comunicado en el PR.
Cobertura de archivo completo medida con --cov-branch: consultar los números
reproducidos en la descripción del PR, no cobertura de diff.
Ruff y export OpenAPI/cliente sin drift. Sin llamadas LLM ni red en la lectura.

Benchmark local repetido por revisión independiente. Datos exactos de esta
corrida en evidence/institutional-new-positions-2026-11-16.json; no son medidas
de HTTP/auth/TLS/PG/producción.50 lecturas de función de ruta existente,SQLite,
15gestores actuales/14nuevas/2trimestres. Expunge antes de cada lectura,
cuatro SELECT por ticker, salida idéntica en50lecturas.
No garantiza coste de 30 tickers; UI debe cargar bajo demanda o con concurrencia
acotada, no disparar un GET por ticker a la vez. No añade coste de red a lectura.

Script/muestras en evidence; sin push/merge/deploy. FAV SHA exacto y piloto
pendientes. Pausa de producción no levantada.
