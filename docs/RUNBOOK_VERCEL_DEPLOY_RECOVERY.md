# Runbook: recuperación de despliegues de Vercel cuando el webhook git se retrasa o llega desordenado

## Cuándo aplica

Un merge a `main` no produce deployment en Vercel, o el alias de producción
(`gerarai.vercel.app`) acaba sirviendo un commit más viejo que el head de
`main`. El 21 oct 2026 se observó durante el incidente de GitHub
"Delays for Pull Requests and Webhook deliveries" (14:52-19:22 UTC,
https://www.githubstatus.com): entregas webhook retrasadas ~11-12 min, una
entrega no observada dentro de la ventana, y una regresión de alias por
entregas desordenadas. La coincidencia horaria con el incidente es
correlación, no prueba por-webhook (el log de deliveries del hook no era
accesible con los tokens disponibles).

## Comportamiento de Vercel que importa

- "When a production deployment succeeds, Vercel updates your production
  domains to point to the new deployment"
  (https://vercel.com/docs/deployments/environments). La promoción no
  depende de la antigüedad del commit: si el build de un commit viejo
  termina después (webhook desordenado), ese deployment toma el alias.
- Asignar un dominio a un deployment existente NO reconstruye
  (https://vercel.com/docs/deployments/promoting-a-deployment): promover o
  hacer rollback es instantáneo y gratis en builds.

## Procedimiento (€0, sin tocar secretos, plan ni variables)

a) Verifica qué SHA sirve el alias y si YA existe un deployment READY del
   SHA objetivo. No actúes por metadata de chat: relee la API.
b) Si existe un deployment READY del SHA exacto pero el alias está en otro,
   asigna el alias a ese deployment (promoción/rollback documentado, sin
   build).
c) Solo si NO existe ningún deployment del SHA objetivo y nada está
   BUILDING/QUEUED tras la ventana de lag, crea el deployment de producción
   del SHA exacto (API o CLI).
d) Nunca crees un deployment mientras haya otro BUILDING/QUEUED del mismo
   objetivo; nunca dupliques builds del mismo SHA (cada uno consume 1 de
   los 100 deploys/día de Hobby).
e) Antes de reportar éxito, verifica: deployment READY, alias asignado sin
   error, y que el alias sirve el SHA exacto.

## Llamadas usadas el 21 oct 2026 (token API de la cuenta, guardado en vault)

```bash
# Estado reciente y cola
curl -s -H "Authorization: Bearer $VERCEL_TOKEN" \
  'https://api.vercel.com/v6/deployments?limit=10'

# Qué deployment sirve un alias concreto
curl -s -H "Authorization: Bearer $VERCEL_TOKEN" \
  'https://api.vercel.com/v13/deployments/gerarai.vercel.app'

# Crear deployment production de un SHA exacto (solo si no existe, ver c/d)
curl -s -X POST -H "Authorization: Bearer $VERCEL_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"name":"gerarai","gitSource":{"type":"github","repoId":1087903428,"ref":"main","sha":"<SHA40>"},"target":"production"}' \
  'https://api.vercel.com/v13/deployments'

# Promover un deployment existente al alias (sin build, ver b)
curl -s -X POST -H "Authorization: Bearer $VERCEL_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"alias":"gerarai.vercel.app"}' \
  'https://api.vercel.com/v2/deployments/<deploymentId>/aliases'
```

## Calibración de la ventana de espera

El 21 oct, durante el incidente, los webhooks llegaron con ~11-12 min de
retraso; una vez GitHub declaró la recuperación, los deploys volvieron a
segundos. Comprueba https://www.githubstatus.com antes de asumir un fallo
local: un retraso dentro de la ventana de un incidente activo NO es un
deploy perdido.
