# Dedicated Flex sync (not enabled by default)

No production activation is part of this change. Existing daily 06:50 UTC sync remains on the default queue while IBKR_DEDICATED_SYNC_ENABLED=false.

Opt-in requires the flag on scheduler and every IBKR consumer, plus a dedicated 1-process/1-thread ibkr-sync consumer. The separate compose override is a template, not a validated production budget. Its 384 MiB limit is provisional and unmeasured. Do not apply until a representative maximum-size Flex import is measured, a full effective-compose budget stays <=10240 MiB, rollback is prepared, and approval is recorded. Never reduce the existing workers blindly. Never share dca-manual.

When enabled, both the dispatcher and imports use ibkr-sync, not the default backlog. Daily catch-up remains 06:50 UTC; weekday post-close runs at 18:00 America/New_York (DST-aware). Market holidays are not inferred; no report freshness is promised at 18:00. Flex is delayed reporting, not live trading. Existing revision, statement-date and account validation remain authoritative. Receipt/lease integration is a separate dependent PR. Until that is merged and tested, this is preparation, not complete autosync.

The token is not in this file. Use the encrypted connection settings, never log it. No retry loop or provider request frequency is added here. Failed report generation is shown as an error by the existing service; the morning sync is the bounded catch-up.

## Cambios de conexión durante una sincronización

Sync manual y programado, guardar/renovar credenciales y desconectar comparten
el mismo lease por tenant. Los commits internos del importador no lo liberan.
Guardar o desconectar durante un sync devuelve HTTP 409 sin cambiar revisión,
credenciales ni estado; se puede reintentar al terminar. No se promete cancelar
una importación ya iniciada al pulsar Desconectar. La validación remota de unas
credenciales nuevas puede ocurrir antes de adquirir el lease; su guardado no.
El chequeo de revisión sigue rechazando informes descargados con una revisión
anterior. Otros tenants no comparten este bloqueo. `import_report` es una función
interna: sus llamadas operativas deben permanecer dentro de `sync_lease`.
