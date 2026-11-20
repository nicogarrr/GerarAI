# Lector de contexto VIX, 20 noviembre 2026

Cambio separado, base 6c076441813e29954080424fc636f51dcf6ef004. No modifica
la tarjeta ni la clasificación vix-context-v1 ya auditada.

## Procedencia y límites

El usuario facilitó una captura atribuida a @spacanpanman y pidió que Cerebro,
asistente y otros lectores la tuvieran en cuenta. La captura propone niveles
superiores a 50 y un intervalo 70-90 como contexto de oportunidad. No hay URL
del post verificada, no se inventa. Son afirmaciones de un tercero, no hechos
medidos: tampoco se validan los ejemplos de crisis financiera, COVID o abril
2025. No hay backtest, selección de episodios, retornos posteriores ni garantía
de suelo. No se equipara un máximo intradía a un cierre diario. La opinión
no se reproduce como una instrucción de invertir todo el capital.

## Rutas

- Cerebro y asistente: preguntas VIX/volatilidad extrema tienen respuesta
  determinista compartida. No llaman a un proveedor ni modifican estado.
- Síntesis financiera con fuentes en Cerebro y asistente: recibe también el
  contexto macro, separado en `non_evidence_market_context`, aunque la pregunta
  sea sobre una empresa y no nombre VIX. No añade IDs a las citas permitidas,
  ni amplía los tipos de evidencia aceptados. Es contexto, nunca una regla.
  No añade llamadas a modelos ni levanta presupuestos existentes.
- Biblioteca: conserva su recuperación y citas de autor. Si se pregunta por
  VIX añade un bloque macro separado, también cuando no existen fragmentos.
  La captura no se atribuye al autor consultado ni entra como cita documental.
- No se toca ejecución, alertas, valoración, publicación de tesis, asignación,
  posiciones, DCA ni planes. No se introduce una nueva fuente de ingesta.

El dato actual procede exclusivamente de latest_snapshot y de la validación
vix-context-v1. Un SELECT de snapshot persistido, sin refrescar ni conectar con
proveedores. Si falta, es inválido, futuro u obsoleto, se dice que no hay cierre
válido reciente y no se afirma un nivel actual. El método conserva metadatos de
procedencia; no añade etiquetas de proveedor a la tarjeta ni a la prosa.

## Verificación local

72 tests verdes en lector, Cerebro, asistente, historial, síntesis y biblioteca.
Entre ellos: pipeline real SQLite ingest/snapshot/read, ausencia de escrituras,
SELECT único, cierre obsoleto no presentado como actual, límites ES/EN, no
proveedor en respuesta VIX, hipótesis sin citas inventadas, aislamiento de
biblioteca, contexto automático sin ampliar evidencia. Ruff focal verde.
Pyright 1.1.414 en 6 servicios: 0 errores, 6 warnings. No es un gate completo
VM ni PostgreSQL; no se afirma despliegue ni validación histórica.
