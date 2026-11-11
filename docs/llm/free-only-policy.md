# Gate de modelos sin facturación para tenants de prueba

Desactivado por defecto (`LLM_FREE_ONLY=false`). No desplegar ni activarlo como parte de esta PR.

Cuando se activa:
- Solo un tenant interno verificado puede llamar a un modelo.
- Las factorías de chat, general, trabajos de fondo, narrativa/tesis y debate fuerzan la clave de plataforma, endpoint exacto `https://opencode.ai/zen/v1/chat/completions` y modelo exacto `deepseek-v4.1-flash-free`.
- No se toman overrides de modelo/destino, BYOK ni respaldos de pago. Sin clave de plataforma o con `LLM_ENABLED=false`, se desactiva el proveedor.
- Una segunda barrera justo antes del transporte impide otros destinos/modelos, incluso adaptadores construidos directamente. También cubre las microdecisiones Jev, que tienen cliente HTTP propio y pueden facturar.
- Sin contexto de tenant, se bloquea también el endpoint gratuito. No se toma identidad de metadata, payload o cabeceras sin verificar.

## Exención de la cuenta de Nico

`LLM_FREE_ONLY_EXEMPT_TENANT_IDS` es una lista de IDs internos positivos separados por coma, vacía por defecto. No inferir el ID de Nico de IDs conocidos de pruebas. El piloto corroboró en producción el ID interno 2 para Nico. Valor a configurar por el operador: `LLM_FREE_ONLY_EXEMPT_TENANT_IDS=2`, ANTES de activar el flag. El código mantiene la lista vacía por defecto. Solo esos IDs conservan el camino anterior, incluidas sus cuotas y BYOK. Esto no crea un rol de administrador público.

El alcance se liga en la dependencia HTTP a `db.info['tenant_id']` ya resuelto tras autenticar la firma, y en Dramatiq al argumento tenant_id del mensaje interno. Se limpia al terminar/saltar el mensaje. Los puentes async propagan contextvars. Un trabajo sin tenant no queda exento por ser trabajo de fondo.

## Límites y fallos

No se modifica ni se garantiza la cuota gratuita del proveedor. Un 402/429 del modelo gratuito sigue el manejo de caída existente (respuesta determinista, sección N/D o fallo controlado según función), sin ampliar la cadena. No recargar saldo para reparar una cuota gratuita. Los topes EUR son estimaciones por tenant, no un máximo de factura.

El gate cubre generación LLM y Jev. No es un bloqueo de toda salida de red ni un control de gasto de servicios no LLM (datos de mercado, alojamiento, correo, etc.).

## Activación y reversión

1. Auditor FAV del SHA exacto y despliegue ordinario por operador.
2. Verificar/configurar la exención de Nico y clave de plataforma ya existente, sin claves nuevas ni pago.
3. Activar el flag en API y en TODOS los workers; una instancia antigua o con flag distinto sigue el comportamiento antiguo.
4. Revisar con las dos altas reales: logs deben mostrar solo opencode-free para esos tenants y nunca Go/TypeSafe/BYOK-pago. No hacer una llamada real de pago para comprobar el bloqueo.

Desactivar el flag revierte al comportamiento anterior y puede volver a permitir modelos facturables. No hay migración ni cambio de rate limits. Para un cierre de emergencia mantener flag activo y retirar clave plataforma o `LLM_ENABLED=false`.
