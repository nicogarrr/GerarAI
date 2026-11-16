# Calendario: atribución del cold artificial, sin parche de producto

Hallazgo de 14-nov: JSON screen-endpoints-fixture-expanded-2026-11-14,
SHA f0596f40, GET /api/calendar/catalysts fixture SMALL. Primera N=1:
7.179,77 ms, 8 queries y sólo 0,49 ms de cursor SQL; warm N30 p95 14,20 ms.
NO es navegación/LCP ni tiempo medido de producción. El warm 9,4 ms citado
en una síntesis corresponde a /calendar/earnings, no a /calendar/catalysts.

Repetición 15-nov, base 64b535150 con cambios locales screener+batch peers
(sin cambios calendar), proceso nuevo, misma perf_world SMALL, socket.connect
y create_connection bloqueados: primera 7.717,57 ms/8 queries; N30 warm
p50/p95 14,16/15,66 ms. Todas las respuestas HTTP 200, sin afirmar contenido
fresco: los proveedores están bloqueados. 118 intentos socket bloqueados
(incluyen Redis y proveedores) durante esa fila.

Los logs del rerun registran ConnectError de NASDAQ y SEC, reintentos SEC
1..4, pacing y circuit-breaker/cooldown. Es evidencia de espera del camino
de fallo artificial antes de enfriarse, no de un coste SQL o cold import de
7 s. El caché de fallos beneficia a las muestras calientes siguientes.

No se ha probado el cold de NASDAQ/SEC en producción. Se descarta arreglar
ese número mediante reducir deadline, eliminar pacing/retries, falsear vacío
como éxito, persistir errores como datos, o modificar la semilla para ocultarlo.
El frontend actual ya separa shell/cabecera/lista con Suspense y una promesa
compartida; tampoco se añade otro parche de streaming sin fallo demostrado.

Resultado: diagnóstico cerrado como benchmark artificial de fuente caída,
no como regresión confirmada del Calendario de producción. Se mantienen
pruebas de deadlines y respuestas parciales existentes. NO hay mejora de
Calendario que vender: su antes/después de producto es sin cambios.

Evidencia cruda: sección /api/calendar/catalysts de
`evidence/audit-endpoint-recheck-2026-11-15.json`. Los datos locales y el
conteo de intentos no son una captura de disponibilidad real de las fuentes.
