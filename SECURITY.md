# Política de seguridad — GerarAI

## Canal de reporte

No abras un issue público para vulnerabilidades. Repórtalas por el canal
privado de GitHub: **Security → Advisories → New draft advisory** en
`nicogarrr/GerarAI` (`https://github.com/nicogarrr/GerarAI/security/advisories/new`).

Incluye: descripción, pasos de reproducción, impacto estimado y, si aplica,
rutas afectadas (`/api/*`, server actions, Telegram). Tiempo objetivo de
primera respuesta: 7 días. No se ofrece recompensa (proyecto personal sin
bug bounty).

## Alcance

Superficie cubierta por esta política:

- **Research API (`/api/*`)**: autenticación HMAC (`X-CavaAI-*`) con secreto
  de **32 caracteres mínimo** (`RESEARCH_AUTH_SECRET`), ventana de 300 s y
  tenant-scoping por `userId`. Sin secreto válido no hay acceso.
- **Tenant-scoping**: Postgres es canónico y Qdrant/MinIO se aíslan por tenant;
  toda consulta filtra por tenant (`rebuild_tenant` para reconstruir el índice).
- **Alertas**: **Telegram es el único canal de alertas** (reglas de
  precio/noticias/earnings, aprobación de tesis desde el propio Telegram).
  **Los emails están desactivados**: no se envía ni se confía en email para
  alertas o recuperación.
- **Sesiones**: Better Auth en MongoDB + `BETTER_AUTH_SECRET` (32+ caracteres).

## Política de secretos

- Nunca commitear `.env` (solo se versionan los `.example`; `.env` está en
  `.gitignore`). Generar secretos con `openssl rand -base64 32`.
- Secretos independientes: `BETTER_AUTH_SECRET` ≠ `RESEARCH_AUTH_SECRET`.
  Rotar ambos si hay sospecha de filtración.
- En producción (Vercel / Oracle / Render) los secretos van solo en el
  dashboard de deploy, nunca en el repo ni en logs. Puertos de BD cerrados
  al exterior.
- Si un secreto llega a Git, considéralo comprometido: rótalo y purga el
  historial afectado.

## Buenas prácticas exigidas en PRs

- Sin secretos ni tokens en código, tests o fixtures.
- Si tocas rutas del backend, regenera el cliente OpenAPI
  (`npm run generate:openapi`) y verifica que no hay drift.
