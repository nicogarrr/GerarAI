# Alertas insider: corte independiente por fecha de publicación

Base: 53568d67 (main). Continuación separada del corte ya propuesto para
feed, operations y ownership. No toca #5666, #5674 ni #5676.

## Reproducción controlada

Con fecha de evaluación 2026-11-14, compra 2026-11-13 y filing 2026-11-15,
`_candidate_purchases` devolvía 1 candidato. Que la operación sea pasada no
significa que el formulario estuviera publicado. No se afirma un incidente
de producción ni se consulta una fuente remota.

## Cambio

Leer la fecha del formulario en la misma consulta mediante outer join.
Apartar del conjunto de candidatos todo formulario con fecha legible posterior
a la evaluación, independientemente de la antigüedad de la operación. También
se aplica cuando el backfill desactiva el límite de antigüedad.

No hay N+1: continúa una sola consulta. La unión externa conserva las filas
sin formulario asociado conforme a la selección anterior. Fecha ausente o
ilegible no se inventa: conserva el comportamiento anterior. No se cambia
la regla de fechas de transacción, tenant, umbrales, dedupe, idioma, estructura
de alertas ni dispatch. No invalida ni borra alertas ya persistidas.

Antes/después: con filing futuro, candidatos 1 -> 0; evaluate no crea alertas.
Con filing de hoy/pasado/ausente/ilegible se conserva 1 candidato si la
operación pasa sus filtros previos.

## Verificación

- Rojo primero: fallan los dos casos con filing futuro, con límite 30 y None.
- Diez combinaciones de publicación (futura/hoy/pasada/None/ilegible) y límite
  de antigüedad (30/None); los dos futuros ejercitan evaluate y cero alertas.
- Se corrige el fixture de la prueba de recencia: evaluaba el día de operación
  aunque el formulario del fixture se publicaba un día después. Ahora fija
  el filing a ese día para probar recencia sin contradecir publicación.
- 24 pytest verdes; cobertura de insider_alerts: 92.21% líneas, 85.42% ramas,
  90.59% combinada. Las líneas ejecutables añadidas están cubiertas.
- Ruff, diff --check y check-i18n verdes. Guards completos: 3066 pasan,
  0 fallos, 1 omitido.
- Sin interfaz visual cambiada. Sin LLM, red de negocio, push, merge ni despliegue.
- No se ha ejecutado la suite completa del proyecto ni Semgrep local.
