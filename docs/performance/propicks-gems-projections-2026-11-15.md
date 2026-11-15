# Joyas: acotar históricos financieros sin alterar el ranking

Base 64b535150. Medición local 15-nov-2026 CET. Parche parcial: no acredita
por sí solo el objetivo de producción <8 s. No cambia el timeout del cliente.

## Diagnóstico

Evidencia del piloto (no reproducida contra producción por este trabajo):
GET /api/propicks/gems 13,7 / 10,9 / 6,4 s bajo carga; Audit vacío aislado
0,419 s. A las 23:50 CET cuatro consultas acumulan ~12,63 s:
_latest_metrics 5,933 s, net_income 2,284 s, revenue 1,804 s y FCF/shares
2,607 s. No son pruebas de N+1 ni recálculo: el embudo usa métricas guardadas.
Las tres consultas de hechos cargaban revisiones completas y recortaban en
Python. La falta de índice no está demostrada sin EXPLAIN.

Este parche mejora esas TRES proyecciones. El mayor coste, _latest_metrics,
se deja sin modificar pendiente de EXPLAIN sobre datos representativos. No
se quita ningún filtro tenant, ni se cambia la política de su periodo máximo.

## Selección equivalente

- Net income: última revisión por compañía/FY, luego últimos cinco FY.
  Cero recorte arbitrario por año calendario; conserva años negativos.
- Revenue: última revisión por FY, cuenta de FY distintos, sólo extremos
  más antiguo/más reciente para CAGR. Conserva span completo y mínimo de
  tres años; no transforma CAGR largo en CAGR de cinco años.
- FCF/shares: última fila de cada compañía/métrica según FY y created_at,
  manteniendo el mínimo today.year-2 y la comprobación de que ambos FY son
  iguales. No se emparejan ejercicios diferentes ni se rescatan filas viejas.

Las selecciones y límites se hacen EN SQL con ventanas sobre columnas
escalares; no se hidratan entidades para recortarlas. Las revisiones con
empate exacto en created_at tenían desempate no especificado antes y lo
siguen teniendo: no se añade precedencia inventada. Paridad cubierta para
revisiones con orden de fuente fechado, huecos, cero/negativos y tenants.

## Evidencia local

30 compañías, 27 FY, 20 revisiones por año y cuatro métricas (64.800 hechos),
métricas guardadas y precios recientes, 20 gemas no vacías. N10 por variante,
A/B y B/A alternado. Se compara cada FunnelResult completo y cada Gem de
salida contra las funciones de la base, con igualdad exacta. No compara
stats.duration_ms, que por definición varía.

| Ejecución | Antes p50/p95 ms | Después p50/p95 ms |
|---|---:|---:|
| SQLite memoria, servicio completo | 53,342 / 115,576 | 35,487 / 42,272 |
| SQLite fichero + otro lector financiero continuo | 191,327 / 255,396 | 49,673 / 53,539 |

Filas escalares devueltas por execute().all del pipeline: 36.360 → 630.
La segunda prueba ejecuta otro lector en conexión independiente al mismo
fichero, repitiendo SELECT de net_income/revenue ordenado durante el A/B;
completó 34 lecturas. Es contención artificial SQLite/hilos/GIL, NO emula
el planner, disco o bloqueo PostgreSQL del servidor real.

Los JSON guardan todas las muestras. Son tiempos de función, NO HTTP,
Next, TLS, producción ni disponibilidad de proveedor. No hubo red ni LLM.
No extrapolar estas mejoras como garantía de quedar bajo 8 s en producción.

## Pruebas

Rojo primero: 810 filas devueltas para una empresa frente a presupuesto de
5 net_income. Ahora 5; revenue 2; FCF/shares 2. Referencias copiadas del
algoritmo anterior verifican valores exactos para seis compañías, múltiples
revisiones/años/gaps, negativos/cero, trimestre que no debe ganar, rangos
vacíos y tenant ajeno. Suites funnel/gems/precios siguen verdes: 31 tests.
Cobertura ejecutable cambiada: funnel 19/19, gems 3/3 (100 %). Ruff limpio.

## Gate pendiente

Se necesita EXPLAIN sin ANALYZE de _latest_metrics, índices/tamaño de tablas
y una medición del piloto sobre el mismo tenant/concurrencia antes/después.
Sin ese dato no se declara corregido el timeout de Nico. Si la ventana
requiere sort pesado de PostgreSQL, medir su plan antes de proponer índice.
No introducir caché de resultados sin invalidación ni servir un ranking
mensual viejo como resultado actual. No subir timeout, quitar datos,
cambiar calidad/valor, cancelar otros trabajos o añadir workers a ciegas.
