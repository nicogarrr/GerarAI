# Research: prefetched facts compartidos entre comparables

Base 64b535150, 15-nov-2026 CET. No red/proveedores/modelos reales.

## Causa y cambio

GET peers/comparison calculaba cada empresa con su propia precarga de hechos.
Para target + 8 peers repetía 9 consultas equivalentes. La selección ya tiene
su propio batch y no se modifica. Ahora el cálculo de lectura comparte una
precarga para los 9 participantes; las fórmulas, métrica solicitada, orden,
filas, ranking y política de muestra no cambian. El camino refresh/escritura
conserva su ciclo transaccional por empresa, fuera del batch nuevo.

El tope sigue siendo 20 hechos POR EMPRESA Y MÉTRICA, aplicado en SQL con
row_number(partition by company_id, metric) + rn <= 20, no load-then-trim.
No se limita a 20 el lote completo ni se incluye historia de otro tenant.
El cache vive sólo durante el cálculo, se limpia incluso en error y la
siguiente llamada ve datos frescos. Los IDs se dividen en lotes de 100
para no crear listas de parámetros sin límite.

## Medido

Rojo primero: test registra 9 prefetches frente al presupuesto 1.
Verde: 1. Con 50 vintages por compañía, test ORM comprueba como máximo 20
por compañía/métrica más sus dos market caps. Paridad de orden/IDs con la
consulta individual y pruebas de tenant, caché anidada/vacía y cleanup.

A/B de servicio, N20 alternado, 9 empresas artificiales con dos market caps
cada una, SQLite: consultas 14→6, p50/p95 9,584/21,410→4,249/4,474 ms;
respuesta completa exactamente igual. No equivale a datos reales abundantes.

HTTP TestClient, fixture perf_world SMALL (4 posiciones pero selección de 9
participantes), N30 warm por variante, fuente de hechos artificial:
consultas 18→10, p50/p95 22,167/24,280→16,396/17,979 ms; bytes 33.948 en
ambos. Sin intentos de red. No es A/B alternado HTTP (before precede after),
por lo que la reducción de consultas es más sólida que la diferencia wall.
Ninguno mide Next/RSC/TLS/render, producción o datos de Nico.

Muestras completas: evidence/peer-prefetch-ab-2026-11-15.json y la sección
peers del evidence/audit-endpoint-recheck-2026-11-15.json.

114 tests verdes (presupuesto nuevo, métricas, peers/selección/divisa/GET).
Cobertura ejecutable cambiada: métricas 22/22 y peers 3/3 (100%). Ruff y
diff-check limpios. Sin push, merge ni deploy. No se afirma haber reducido
62 endpoints: el banco tiene 64 rutas, y aquí se mejora sólo peers/comparison.

## Qué se descarta

No se recortan fórmulas a la lista solicitada ni se reutilizan valores viejos.
No se añade un índice sin plan real de PostgreSQL, ni más hilos/workers.
Las consultas restantes pertenecen a resolución/selección/mercado y no se
eliminan por fuerza. El backend no prueba que la UI dispare las 64 rutas a
la vez: no se traduce ese conteo a fan-out por pestaña sin captura frontend.
