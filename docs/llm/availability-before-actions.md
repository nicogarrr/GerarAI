# Disponibilidad antes de iniciar IA

Cerebro (chat o análisis de biblioteca), generación de tesis y debate muestran un aviso antes del botón. Consultan un endpoint de estado local, no la API del proveedor ni una generación de prueba. Al iniciar, repiten esa lectura para evitar usar una comprobación anterior al breaker. No hay sondeo automático ni reenvío automático de la pregunta.

Estados: configuración desactivada, breaker abierto, respaldo disponible o configuración sin probar. Un estado desconocido impide iniciar una generación y ofrece actualizar el estado. Actualizar nunca inicia el trabajo pendiente. El usuario conserva su pregunta al bloquearse el preflight.

Los breakers por credencial se comparan con la credencial de cada proveedor efectivo, sin exponer clave ni huella en la respuesta. Un breaker de otra clave no se atribuye a este tenant. Se usa la factoría de cada función, incluido el gate free-only, sin ampliar cadenas.

## Límites de la señal

El estado es local al proceso API que atiende la lectura. No confirma cuota real ni el estado de todos los workers/procesos. Un reinicio puede perder breakers locales. La barrera de transporte y el manejo de errores existentes siguen siendo necesarios: esta UI no sustituye el gate de gasto ni garantiza que una llamada vaya a funcionar. Las tesis pueden conservar cálculos o secciones N/D sin una narrativa completa.

Las capturas de revisión muestran el componente real renderizado con estado simulado de pausa a 390 y 1280 px, no una consulta a producción. Pruebas de interacción verifican bloqueo, preflight fresco, ausencia de generación al montar/actualizar y respuestas fuera de orden.

Se enumeran pares efectivos (adaptador, modelo), no solo instancias: los modelos explícitos de los respaldos pasan por el router como en la ejecución, los dos modelos de Gemini se conservan aunque compartan adaptador, y el respaldo interno del adaptador conserva su semántica directa y su supresión cuando el override lo equipara al primario. Solo se bloquea por pausa si todos los candidatos efectivos tienen un breaker local abierto. Las pruebas reproducen un primario con 402 y un respaldo que contesta mediante HTTP simulado, y luego bloquean ambos.
