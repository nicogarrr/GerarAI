# Frontend: despliegue manual por lotes

Desde el 29 de octubre de 2026, `vercel.json` fija
`git.deploymentEnabled: false`. Los pushes, merges y PRs no deben crear
producción ni previews. Los previews ya estaban desactivados; no se activan
porque cada build/deployment añade uso al cupo compartido Hobby.

No usar el Ignored Build Step como bloqueo principal: se ejecuta después de
iniciar el deployment y ocupa concurrencia. El script de selección por rutas
se conserva para despliegues manuales y sigue comparando contra el último
build correcto.

## Publicar un lote, solo por orden expresa de Nico

1. Fijar el SHA completo del lote. Revisar todas las PRs incluidas y esperar
   CI verde de ese SHA, incluido el gate real de cobertura backend cuando
   aplique. No desplegar automáticamente por CI ni por merge.
2. En el proyecto `gerarai` de Vercel, comprobar Production Current y los
   deployments recientes. Si ya existe un READY del SHA, no reconstruir.
3. Ruta directa a producción: usar la CLI oficial con checkout limpio del
   SHA aprobado y proyecto `gerarai` vinculado, y ejecutar
   `vercel deploy --prod`. No añadir hooks automáticos ni workflows de push.
   La alternativa del dashboard es Deployments > menú > Create Deployment:
   acepta Branch, Commit, or URL y muestra inicialmente Create Preview
   Deployment. No confundirlo con producción ni enviar sin verificar destino.
   Si se usa esa ruta, verificar el READY del SHA y promover a producción;
   la promoción no reconstruye. No crear un preview de prueba sin necesitarlo.
4. El control Git solo desactiva disparadores automáticos, no la CLI ni el
   despliegue manual. Comprobar el Ignored Build Step si el lote no cambia
   frontend. No forzar un build que no hace falta.
5. No pagar, cambiar plan o aceptar recursos de pago. Ante cuota agotada,
   conservar producción actual y esperar o consultar, sin reintentos en bucle.
6. Verificar READY, SHA, alias `gerarai.vercel.app` y QA de las rutas del lote.
   Registrar SHA anterior y URL real para rollback sin rebuild.

## Prueba del bloqueo

Tras integrar esta configuración, mergear un cambio solo de documentación.
Guardar el SHA y la hora, y contrastarlos con deployments recientes y estado
GitHub/Vercel. No interpretar ausencia de CI como despliegue correcto. Si un
webhook sigue pendiente, registrar la observación como provisional y revisar
sin lanzar un build de prueba. No crear previews para comprobar este bloqueo.

## Fuentes oficiales

- https://vercel.com/docs/project-configuration/git-configuration
- https://vercel.com/docs/builds
- https://vercel.com/docs/deployments
