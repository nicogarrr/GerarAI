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
- **Alertas**: los canales implementados en el outbox (`NotificationService` en
  `data-engine/app/services/notification_service.py`), con consentimiento por
  tipo de evento y resultado registrado por alerta y canal en `alert_deliveries`,
  son cuatro:
  - **In-app**: canal base; la alerta se persiste en `research_alerts` y se
    marca entregada en cuanto existe en la app (`in_app_alerts.py`), sin envío
    externo. Los avisos DCA están apagados por defecto
    (`DCA_ALERTS_ENABLED=false`) con `DCA_ALERT_CHANNELS=in_app`; los de
    resultados (earnings) también están apagados por defecto
    (`EARNINGS_ALERTS_ENABLED=false`, con `EARNINGS_ALERT_CHANNELS=in_app,email`
    cuando se activan).
  - **Telegram**: `sendMessage` del bot ya existente, con vinculación verificada
    de chat privado y opt-in por tipo (`docs/telegram-outbound-alerts.md`).
    Apagado por defecto: requiere `TELEGRAM_ENABLED=true`, `TELEGRAM_BOT_TOKEN`
    y un chat confirmado; la aprobación de tesis por Telegram exige además
    `TELEGRAM_APPROVAL_ENABLED=true`.
  - **Email/SMTP**: envío por `smtplib`, con contraseña nunca registrada en
    logs. Puede ir a la lista global (`ALERT_EMAIL_TO`) o a la dirección propia
    del usuario, firmada por el frontend y con opt-in por tipo
    (`email_alerts.py`); sin `SMTP_HOST` y `SMTP_FROM` el canal queda
    `not_configured`. El correo también se usa para avisos de aprobación de
    cuentas (`lib/auth/approval-notify.ts`), con respaldo no electrónico en
    `/api/admin/approvals`.
  - **Web push (PWA)**: claves VAPID propias, permiso del navegador y opt-in por
    tipo (`web_push.py`). Apagado por defecto: requiere `WEB_PUSH_ENABLED=true`,
    `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY` y `VAPID_SUBJECT`.
  - Nota sobre los **webhooks de correo/push** (`ALERT_EMAIL_WEBHOOK_URL`,
    `ALERT_PUSH_WEBHOOK_URL`): el código los contempla como destino global de
    respaldo, pero `Settings` no los modela (`extra="ignore"`), así que con la
    configuración real quedan inactivos y el destino global de correo depende
    de SMTP.
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
