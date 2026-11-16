# Hy4 Flash: selector aislado en el chat general

Contrato: `POST /api/chat`, campo opcional `model: "hy4-flash-free"`.
Ausente: comportamiento anterior. Presente: `ChatService(provider=Hy4Provider)`;
sin debate ni JEV externo, sin cascade, fallback, retries o cambio de defaults.
La UI se entrega por separado. Guia por ticker y biblioteca NO estan incluidas.

Cada inferencia consulta https://opencode.ai/inference/go/v1/models y exige
modelo exacto, endpoint Go exacto y precio input/output numerico cero. Respuesta:
modelo exacto, usage.cost=0, usage.opencode.billing_source=go,
list_cost=0 y allowance=0. Si falla, se bloquean las siguientes peticiones de ese
proceso y se muestra un aviso fijo. No se imprime la clave ni el cuerpo recibido.
El contexto del selector bloquea el transporte de helpers con otros destinos.
Admision: maximo una inferencia Hy4 en vuelo por proceso, sin cola; las
concurrentes se rechazan. Se vuelve a comprobar el latch tras el await del
catalogo y en el limite de transporte. Un request ya enviado no se puede retirar.
No se añade Hy4 al registro de fallback free ni a selecciones generales de tenant.

Limites importantes: el proveedor puede cambiar el precio entre catalogo y
respuesta; un guard posterior NO deshace un primer cargo. El bloqueo es por
proceso (no distribuido ni persistente entre reinicios). No se modifica
ExtraUsage/PAYG ni se valida su configuracion de cuenta via API. El uso propio
actual no supone permiso para ofrecer Go a terceros en el futuro. No hay fecha
contractual confirmada de fin de promocion: ante precio no verificable se corta.
No se ha desplegado ni cambiado la seleccion activa de produccion.

Validacion local: bateria focalizada de 89 tests verdes (incluye reproductor
externo del auditor). Cobertura combinada por fichero: Hy4 97,30%, ruta chat
97,32%, free_only 100%, schemas/api 99,95%; ramas individuales >= 85%.
Ruff repositorio verde; OpenAPI regenerado. Suite completa pendiente de CI.
Pyright ficheros modificados: 0 errores; completo no termino en 80 segundos
tras ampliar heap a 3 GB (primer intento agoto heap). Sin llamadas de inferencia reales en esta PR.
