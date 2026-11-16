# Hy4: Cerebro biblioteca

Apilada sobre #5756/4d435fed. Ruta REAL: askKnowledge/askKnowledgeResult ->
POST/api/knowledge/chat. Nuevo campo model opcional literal hy4-flash-free.
Seleccionado inyecta proveedor Hy4 dedicado, contexto de transporte aislado,
misma recuperacion y mismos validadores de citas/numeros para respuesta/analisis.
El pin de request legacy space-bunny-free de ask_library queda remapeado a Hy4
por _pin_to_model, probado sin red. No se envia esa llamada a Space Bunny.
En corte se devuelve aviso visible, sin otro proveedor. No modifica ingesta
ni jobs de principios (PR separada). No se han hecho lotes ni llamadas de
inferencia reales en esta PR. ExtraUsage no se toca. Guardia/limites #5756.
Cambio de default autorizado por Nico posterior al selector: otra PR con mapa
completo y auditoria; esta PR sola NO activa toda la Biblioteca por defecto.
