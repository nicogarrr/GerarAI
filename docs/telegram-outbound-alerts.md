# Alertas salientes por el bot de Asistenta

Sin API de pago. GerarAI usa `sendMessage` de Telegram Bot API y el bot ya
existente de Asistenta, sin crear otro bot ni consumir `getUpdates`.
Asistenta sigue siendo el único consumidor de actualizaciones/webhook.

## Configuración y contrato

1. Configurar `TELEGRAM_BOT_TOKEN` en el entorno privado del backend y worker
   con el token del bot de Asistenta. Nunca guardarlo en Git, frontend o logs.
2. `TELEGRAM_ENABLED=true` habilita el adaptador, pero **no** crea suscripciones.
3. Asistenta debe obtener `message.chat.id` de una conversación privada iniciada
   por el usuario y verificar su asociación con la identidad autenticada de
   GerarAI. No confiar en un chat reenviado ni permitir grupos para esta conexión.
4. El propietario confirma el chat y los tipos deseados desde la sesión firmada
   de GerarAI. La API no permite que otro usuario modifique la suscripción del
   propietario. El chat positivo privado se guarda por workspace personal/tipo;
   nunca se reutiliza `TELEGRAM_CHAT_ID` global para estos eventos.
5. `PUT /api/alerts/telegram-subscriptions/{event_type}`:
   `{ "enabled": true, "chat_id": "<chat privado confirmado>" }`.
   Tipos (`EVENT_TYPES` en `app/services/outbound_alerts.py`):
   `thesis_broken`, `new_filing`, `insiders`, `shorts_rising`, `daily_digest`,
   `dca_levels`, `macro_event`, `earnings`.
   `GET /api/alerts/telegram-subscriptions` devuelve los ocho tipos, apagados
   por defecto. Activar exige el chat ya vinculado (`403 chat_link_required`
   si no lo está) y solo el dueño de la suscripción puede modificarla
   (`403 subscription_owner_only`). Desactivar usa el mismo PUT con
   `enabled:false`.
   Este PR ofrece las APIs de prueba del bot y confirmación del propietario,
   no una pantalla nueva. Hasta verificar el chat y activar cada tipo no se envía nada.

Una suscripción requiere tenant y usuario verificados por el puente de auth
existente, nunca IDs suministrados en el cuerpo. El modelo actual de GerarAI es
un workspace personal de un propietario; no es un servicio multiusuario dentro
del mismo workspace. Para añadir miembros se necesitaría un outbox por destinatario.

## Eventos y datos

- Tesis: `claim_contradicted`/`thesis_broken` persistidos; no se afirma que una
  inferencia del LLM sea un hecho. Una contradicción pide revisión, no vender.
- Filing: documento SEC/CNMV oficial de empresa en cartera/seguimiento. Se avisa
  aunque aún falte texto o informe comparable; se dice que el análisis puede
  estar pendiente/sin datos. Una misma fuente/checksum no crea dos avisos.
- Insiders: señales persistidas Form 4, con huella de transacción y versión de
  regla. Se elimina el envío directo sin outbox del evaluador insider.
- Cortos: subida de posiciones FINRA respecto al periodo anterior (fecha válida
  y <=35 días) o aumento de suma pública CNMV con los mismos titulares entre
  consultas. La suma CNMV es parcial. El volumen corto diario FINRA nunca se
  interpreta como posición abierta ni sentimiento bajista.

Se leen eventos existentes; el barrido no descarga fuentes ni llama al LLM.
La actualización de cortos consulta FINRA pública además de volumen diario.
El reconciliador existente se ejecuta cada 10 minutos por tenant en Dramatiq,
con lease Redis. Recoge alertas nuevas de emisores que solo escriben a DB.
Los emisores que ya llaman `dispatch` pueden enviar sin esperar al barrido.
No se reproduce historial anterior a la activación/re-activación/cambio de chat.

## Deduplicación, fallos y revocación

Huella de evento en `research_alerts` y UNIQUE `(alert_id, channel)` en
`alert_deliveries`. Claim SQL atómico antes del HTTP evita dobles envíos por
workers concurrentes. Se revalida consentimiento en cada intento, incluidas
reconciliaciones. Rechazo permanente 4xx no se reintenta; 429 honra el enfriamiento
hasta una hora; timeout/5xx es `unknown`, no éxito, y espera al TTL de diez minutos.
Telegram no ofrece clave de idempotencia: tras resultado ambiguo puede repetirse
un aviso. No se promete exactly-once. Desactivar no puede retirar un HTTP que
ya salió antes de la revocación. Solo HTTP exitoso **y** `ok:true` es entregado.
Los errores persistidos omiten token, URL del bot, contenido y respuesta cruda.

## Despliegue

Aplicar Alembic hasta `0055_telegram_chat_binding`, reconstruir backend/worker/
scheduler con `docker-compose.prod.yml`. Las variables de entorno de Telegram
ya existen. No se activa nada con la migración y no se toca `wake.ts`.
Comprobar primero con un chat privado de prueba y consentimiento explícito;
este PR usa HTTP simulado y no envía mensajes reales ni guarda credenciales.

## Vinculación verificada (obligatoria desde 0055)

El chat_id ya no se acepta como prueba de propiedad. Suscripciones existentes
sin vínculo confirmado quedan bloqueadas, y ningún tipo de alerta desconocido
puede usar el chat global.

1. Con sesión GerarAI firmada, `POST /api/alerts/telegram-link` devuelve un
   `challenge_id` y `/link <código de un solo uso>` que caduca en 10 minutos.
   Solo se guarda SHA-256 del código. Un nuevo inicio invalida códigos anteriores.
2. El propietario envía ese comando al bot de Asistenta en su chat privado.
3. En su handler Telegram existente, Asistenta verifica que el update procede
   del transporte Telegram autenticado, `message.chat.type == "private"`, y
   `message.chat.id == message.from.id`. Extrae el código SOLO del comando
   recibido; nunca toma chat_id/from.id de parámetros del usuario o de un
   reenvío. No incluir este código ni la firma en logs.
4. Asistenta serializa un JSON UTF-8 con `token`, `chat_id`,
   `telegram_user_id` (ambos IDs como strings) y `chat_type:"private"`.
   Lo envía por HTTPS a `POST /api/telegram/link-proof` con:
   - `X-Asistenta-Timestamp`: segundos Unix actuales.
   - `X-Asistenta-Signature`: hex HMAC-SHA256 de
     `timestamp + "." + bytes_exactos_del_JSON`.
   - `Content-Type: application/json`.
   La clave compartida `TELEGRAM_LINK_SECRET` debe tener >=32 caracteres y
   existir SOLO en el entorno servidor de Asistenta y GerarAI. Es distinta del
   bot token y de la clave de identidad GerarAI. Nunca frontend, chat ni Git.
   GerarAI valida firma y edad <=60 s, exige chat privado y remitente igual al
   chat, y consume el código una vez de forma atómica. Este endpoint no necesita
   firma de usuario GerarAI: la autenticación es HMAC del bot, fail-closed si falta.
5. El propietario consulta `GET /api/alerts/telegram-link/{challenge_id}` en
   GerarAI, revisa el chat candidato y confirma con
   `POST /api/alerts/telegram-link/{challenge_id}/confirm`, cuerpo
   `{ "chat_id": "<candidato revisado>" }`. No puede confirmar otro usuario
   ni un chat diferente del probado por el bot. Solo entonces se persiste el
   vínculo. Un chat no puede pertenecer a dos identidades.
6. Activar los tipos usando el PUT de suscripciones anterior. Cualquier cambio
   de destino requiere repetir esta prueba; confirmar un nuevo vínculo desactiva
   todas las suscripciones anteriores para exigir un opt-in nuevo.

El callback firmado certifica la observación de Asistenta, no de un cliente
anónimo. No apuntar Telegram directamente a este endpoint: el bot actual sigue
recibiendo updates y solo reenvía pruebas de `/link`. Sin ese pequeño handler de
Asistenta la vinculación no se completa y Telegram permanece bloqueado.

CNMV: además del mismo conjunto de titulares, todos los nuevos position_date
son fechas válidas, no futuras, no anteriores a la fecha previa del titular y
con antigüedad máxima de 35 días. Cada porcentaje cambiado exige avance de su
fecha, y el snapshot debe tener al menos un avance verificable. Si falla una
condición, no se emite alerta de aumento; el panel conserva su dato y fecha.
El aviso incluye el rango de fechas de las posiciones públicas comparadas.
