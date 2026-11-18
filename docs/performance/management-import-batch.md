# Importar promesas de llamadas: consultas en lotes

Base exacta: `db79294ac4e93bb4f63be95372255386cd0ac6e2`.

## Cambio

`ManagementCredibilityService.import_call_claims` hacía una lectura para
buscar cada promesa existente y un refresh individual después del commit.
Reimportar N claims existentes hacía 1+2N SELECTs.

La búsqueda y el refresco se agrupan en lotes de 500 IDs. Para N>0 son
1+2*ceil(N/500) SELECTs en la reimportación sin modificaciones. Para una
primera importación siguen siendo necesarias las escrituras de las promesas.
No se promete un número constante de INSERTs ni reducir su coste.

Se capturan los IDs antes del commit, también con expire_on_commit=True.
El refresco usa populate_existing para conservar el contrato de devolver
objetos con los defaults y datos refrescados tras el commit, ordenados por
claim. Las promesas ya existentes conservan estado, evidencia e identidad.
La búsqueda por tenant sigue pasando por el guard ORM habitual. Este parche
no cambia el contrato existente de sesiones sin tenant ni añade permisos.

No se altera reconciliación, parsing, generación de texto, rutas o esquema.
No añade caché. La carrera de dos primeras importaciones concurrentes sobre
el mismo claim sigue protegida por el unique existente y puede producir el
mismo IntegrityError que antes; no se soluciona ni se amplía aquí.

## Evidencia

Fixture sintética local: 100 claims/promesas ya importados, sesión ORM nueva
por muestra, expire_on_commit=True, caché caliente, 20 pares alternados.
Se compara igualdad de todas las columnas mapeadas de la salida antes de
medir. p95 por nearest-rank, muestras crudas en JSON adjunto a la entrega.

| Motor | Antes mediana/p95 | Después mediana/p95 | SELECTs |
|---|---|---|---|
| SQLite en memoria | 34,44 / 35,00 ms | 4,12 / 4,34 ms | 201 a 3 |
| PostgreSQL local | 72,68 / 74,96 ms | 6,24 / 6,46 ms | 201 a 3 |

No son datos ni tiempos de producción. Desconocemos frecuencia y tamaño de
importaciones reales. No se midieron HTTP, concurrencia, CPU/RSS, transacciones
con datos pendientes ni proveedores externos. El esquema PostgreSQL temporal
se elimina al terminar las pruebas y el benchmark.

## Tests

- 4, 40 y 501 claims con expire_on_commit True y False.
- Reimportación con sesión nueva, sin INSERT/UPDATE/DELETE, presupuesto de
  SELECTs y acceso a datos devueltos dentro de la ventana del contador.
- Lote vacío, mezcla existente/nuevo, estado/evidencia/identidad conservados,
  tenant ajeno excluido.
- 9 tests del nuevo fichero ejecutados además en PostgreSQL desechable real.
- Suite dirigida de servicio, bordes, conciliación y P1: 36 tests pasados.
  Servicio entero 103/103 líneas y 34/34 ramas, 100% en ambos.

Comando desde data-engine:

```sh
APP_ENV=test python -m pytest tests/test_management_import_batch.py tests/test_management_credibility_service.py tests/test_management_credibility_bordes.py tests/test_promesas_conciliar_sin_duplicar.py tests/test_p1_financial_intelligence.py --cov=app.services.management_credibility_service --cov-branch --cov-fail-under=85 --cov-report=term-missing --cov-report=json:/downloads/management-import-coverage.json
```

Para ejecutar el nuevo fichero contra PostgreSQL, fija
MANAGEMENT_TEST_POSTGRES_URL a una base desechable con permiso de crear schemas.
Nunca se debe apuntar a producción. Sin esa variable la fixture usa SQLite.
