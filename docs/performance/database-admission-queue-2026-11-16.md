# #5711: cola acotada antes de get_db

Base exacta 40235252679c8b3ef7978dafaf9a95814cb789b8 (head #5711).
Parche incremental. No levanta límites activos ni exime lecturas.

## Problema y política

El head rechaza inmediatamente el quinto request del tenant, aunque sea una
ráfaga normal de lecturas independientes. Los límites activos siguen siendo
4/tenant y 8/global con pool normal10: mantiene dos conexiones de reserva.
No se cuentan conexiones overflow como capacidad. Pools pequeños conservan
la degradación documentada 1/1 del head, sin nueva promesa de aislamiento.

Ahora espera async máximo1s ANTES de abrir SessionLocal. Máximo16 pendientes
por tenant y32 global. No obtiene conexión, Session ni hilo AnyIO para esperar.
La petición usa el presupuesto de su request normal; no amplía timeouts del
cliente. Si el primer lote dura más de1s, puede aún devolver rechazo honesto.
No se afirma corregir todas las ráfagas reales antes del replay de Frontend.

Orden FIFO entre elegibles: un tenant ya al cap no bloquea la reserva de otro.
No se permite adelantarse a un waiter elegible más viejo. Si vuelve capacidad
DESPUÉS del deadline, no entra. Cancelación del waiter quita su token;
cancelación activa libera contador por finally, como antes. Queue cap o
deadline agotados conservan429 por tenant o503 por saturación global con
Retry-After1. No convierte sobrecarga sostenida en cola ilimitada ni en éxito.

Poll async cada hasta5ms con threading.Lock breve conserva seguridad del
singleton cuando tests/servidores lo usan desde loops diferentes. Con32
pendientes el trabajo de búsqueda está acotado. No se reclama señal de
cancelación de cliente si su servidor ASGI no cancela la tarea: el deadline
sigue limitando espera incluso entonces. El gate sigue siendo por proceso,
no coordinación distribuida entre workers.

## Rojo primero, aislamiento, cobertura

Tests nuevos rojos contra el head: ráfaga8 obtenía429, no había cola/deadline
ni contador pending. Se detectó y probó además carrera de deadline cuando
vuelve capacidad tarde, corregida antes de entregar.

90 tests verdes: tests/test_database*.py + health_probes + health_routes_edges.
Adicionalmente flow_end_to_end pasó con admission. Coverage --branch del
módulo completo:85/85 sentencias y28/28 ramas (100%). Tests de:
- Ráfaga8 de un tenant: activos <=4, todas terminan.
- FIFO entre tenants elegibles y dentro de tenant, sin bloqueo de otro tenant
  por uno saturado; preservación de su reserva.
- Cancelación de activo y pendiente, cierre de sesión, cero tokens fugados.
- Deadline corto, deadline vencido con capacidad tardía y wait0 explícito.
- Caps de pendientes por tenant y global entre tenants diferentes.
- ASGI real get_db: waiter no construye SessionLocal, health sigue200.
- QueuePool real10/overflow0 mantiene admisión/reserva, tests heredados.

Ruff producto/test/script y diff limpios. Warning Pydantic preexistente.
No se ejecutó la suite completa28k ni User flows browser aquí.

## Medición sintética, no conteo real de pantallas

Script con get_db real, SQLite QueuePool10/overflow0, tenants sembrados,
20 ráfagas de8A+2B y20ms artificiales reteniendo sesión/conexión por endpoint.
Antes y después usan la MISMA carga; clase original extraída del head exacto.

| Resultado | Antes | Cola |
|---|---:|---:|
| Requests totales |200|200|
|200|120|200|
|429|80|0|
| Pico conexiones checked-out |6|6|
| p50/p95 request ms |32,195 /60,964|59,444 /72,012|

La cola añade espera deliberada a cambio de completar, no reduce el trabajo
SQL ni oculta su tiempo. Health200 en cada ráfaga; cero conexiones prestadas
y activos al terminar. Las muestras están incluidas. Esto NO mide picos de
la ficha/first-steps desktop/mobile, PG ni salud real de producción. Frontend
mide el cliente real en paralelo; ese replay sigue siendo gate de aceptación.

## Entrega y límites

Sin producción, push, merge o deploy. No elimina poolguard, no sube activos,
no exime rutas supuestamente baratas y no cambia filtros/resultados. Un
backend con endpoints que retienen las4 conexiones más de1s aún necesita
corregir ese coste; esta cola no lo arregla por arte de magia. FAV del SHA
exacto, pruebas de cliente y despliegue sólo por piloto siguen pendientes.
