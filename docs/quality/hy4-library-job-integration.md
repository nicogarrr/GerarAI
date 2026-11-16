# Hy4: trabajos de principios de biblioteca

Base: defaults comunes 9d6c6b88 (y guard/scope). Factory de background ya
elige Hy4 cuando HY4_REPLACE_DEEPSEEK=1 y el modelo anterior es DeepSeek.
No se usa otro modelo ni una llamada auxiliar de reparacion.

- Maximo 3 lotes por documento en esta fase. Si hay mas, se rechaza antes
  de llamar al proveedor. Hace falta dividirlo; no se finge completado.
- Llamadas secuenciales. Presupuesto y registro 0 para Hy4, condicionado
  al guard compartido que valida catalogo, destino y factura real cero.
- Marcador persistente metadata_.hy4_principle_run_state antes de la primera
  llamada. In_progress o blocked impiden repetir el run en reentregas de
  Dramatiq, reinicios o clics manuales. No hay limpieza automatica.
- Ante cualquier Exception del provider Hy4, persiste blocked y lanza
  ProviderDisabledError, no la clase transitoria que reintenta el actor.
- Un TimeLimitExceeded hereda BaseException: conserva in_progress, y la
  reentrega corta antes del LLM. Prueba con recarga de metadata desde SQLite.
- Para volver a intentar un documento bloqueado hace falta revision humana
  del resultado y retirar explicitamente ese marcador. No lo elimina esta PR.
- Los principios siguen propuestos, sin aprobarse automaticamente; validacion
  de fragmentos, duplicados y reglas numericas no cambia. Un fallo posterior
  puede conservar propuestas de lotes ya terminados; no equivale a completitud.

64 tests pasan. service.py 93,37% lineas (352/377), 95,61% ramas (109/114).
Ruff verde; pyright 0 errores y 2 avisos rowcount en lineas fuera del cambio.
Sin inferencia real ni despliegue. Auditor sobre SHA exacto y gates de CI
siguen siendo obligatorios.
