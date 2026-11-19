# Proyección de payloads del snapshot por lote

Base: `c192ea94b8a873931bfbbb67a2ef82117d952c6d`. Cambio para el siguiente corte, no modifica el corte de despliegue congelado.

`build_many()` obtiene la última tesis, modelo fundamental y valoración de cada empresa. Su respuesta resumida no consume cinco campos de archivo: `ThesisVersion.thesis_markdown`, `narrative_sections`, `invalidation_rules`, `FundamentalModelVersion.model_snapshot` y `ValuationModel.calculation_trace`. Antes el SELECT exterior materializaba y transfería esos campos completos.

Se difieren solo esos campos, sobre el alias ORM y con `raiseload=True`. El SELECT exterior deja de devolverlos. Un acceso futuro accidental falla explícitamente en vez de añadir una consulta por empresa. No se cambia el endpoint de tesis completa ni `build()`, el ranking, los filtros de tenant, los conteos ni la puerta de publicación. No se modifican datos archivados. El subquery sigue describiendo la entidad completa; no se afirma un cambio de plan interno sin EXPLAIN.

## Verificación

- 31 tests de snapshots, salud, cartera, endpoint y mutación existentes/nuevos pasan en SQLite.
- Archivo completo `company_snapshot_service.py`: 153/156 líneas (98,08%) y 53/56 ramas (94,64%). No es cobertura solo del diff ni porcentaje combinado.
- 8 tests nuevos pasan también en PostgreSQL16.2, en schema desechable eliminado al terminar.
- Se captura SQL real y comprueba que los campos no figuran en el SELECT exterior, están descargados en el ORM y leerlos falla sin consultas adicionales.
- Respuesta JSON completa de lote idéntica a la de `build()` con sesiones limpias, tesis draft/published y modelo publicable/no publicable, incluyendo valores grandes sintéticos en los campos omitidos. Son fixtures de test, no datos de empresas reales.
- Modificar otro campo de una fila cargada parcialmente no borra el archivo persistido.
- Dos mutantes mueren en PostgreSQL: quitar la proyección o quitar `raiseload` hace fallar las tres pruebas de entidades.
- Ruff y `git diff --check` pasan. No se afirma ejecución local de Semgrep.

Comando de regresión desde `data-engine`:

```sh
APP_ENV=test python -m pytest tests/test_company_snapshot_batch.py tests/test_company_snapshot_payload_projection.py tests/test_company_snapshot_health.py tests/test_company_snapshot_in_portfolio.py tests/test_company_snapshots_endpoint.py tests/test_mutation_gaps_snapshot.py --cov=app.services.company_snapshot_service --cov-branch --cov-fail-under=85 --cov-report=term-missing --cov-report=json
```

Para repetir los 8 tests en PostgreSQL, definir `SNAPSHOT_TEST_PG_URL` hacia una base desechable y ejecutar `tests/test_company_snapshot_payload_projection.py`. El usuario de prueba debe poder crear y eliminar schemas.

## Límites y reversión

La mejora demostrada es omisión de columnas y ausencia de cargas perezosas, no un número de milisegundos ahorrados en producción. No hay A/B HTTP ni benchmark de latencia del sitio en este parche. Las ganancias dependen del tamaño real de archivos/modelos y de cuánto pese esta consulta en el total. No cambia la parte de conteos que antes se observó lenta.

Una instancia que ya esté completamente cargada en la identidad de la sesión puede conservar esos campos; no se intenta borrarlos ni forzar su descarga. Las peticiones con sesiones nuevas sí reciben las columnas proyectadas. Si un consumidor futuro necesita alguno, debe pedirlo explícitamente fuera de este camino resumido y mantener pruebas de presupuesto de consultas.

Sin migración ni cambio de esquema. Reversión: revertir el commit. Requiere FAV independiente sobre el SHA exacto y CI antes de merge. No despliega.
