# Screener cold: no esperar a la cola del refresco

Base 64b535150. Medición 15-nov-2026 CET, local, sin proveedores/red/modelos.

Causa verificada: si no existe LKG y el vendor es offline/Yahoo, la ruta llama
Future.result(timeout=0.05). Incluso el trabajo local puede quedar detrás del
refresh de otro tenant: una ruta vacía paga 50 ms sin obtener datos. El banco
previo de 62,9 ms es compatible con ese suelo, pero no se atribuye todo su
p95 a este mecanismo sin rerun integral. No se cambia el proveedor ni su cuota.

La ruta ahora sólo adopta los datos ya publicados en su bucket, nunca espera
al Future. Si sigue en vuelo conserva vacío + refreshing=true; si terminó
vacío conserva unavailable y cooldown. LKG/fuentes/fechas/aislamiento tenant
no cambian. Desaparece la posibilidad de recibir el primer resultado por
haber esperado 50 ms: la siguiente consulta de UI lo recoge. El trabajo no
se acelera, sólo deja de bloquear la petición.

A/B N20, misma función y Future pendiente offline, caché vacía: antes p50/p95
50,102/50,167 ms; después 0,0034/0,0200 ms. Respuesta vacía/refreshing igual.
NO es latencia HTTP ni producción. Muestras crudas en evidence/.

Rojo primero prueba que Future.result fue llamado. Verde: test exige cero
llamadas, sin usar umbral wall. 79 tests (nuevo + veracidad + vecinos batch15)
verdes; 12 tests de nuevo/veracidad/contrato HTTP también verdes antes.
Cobertura cambiada ejecutable 2/2 (100%); el resto del diff elimina espera o
mueve líneas ya existentes. Ruff limpio. Sin push, merge ni deploy.
