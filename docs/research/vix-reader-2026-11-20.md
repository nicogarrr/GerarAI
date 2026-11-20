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

## Revisión v2

Retirado el cortocircuito de preguntas que nombran VIX. El enrutado original
resuelve empresa, revisión y DCA; después se añade la nota macro sin sustituir
la respuesta, citas, revisión ni secciones primarias. La síntesis conserva la
nota cuando devuelve extractos. La lectura opcional de macro vive dentro del
try de degradación; si falla, se conserva la respuesta principal. La biblioteca
también termina su recuperación primaria antes de leer el suplemento.

Los dos tests del Auditor se conservan. En el test mixto se completó el fixture
con MSFT y review999: sin esos registros, el comportamiento legítimo previo es
LookupError/404. Se conserva la aserción discriminante original. Se añadieron
rutas mixtas con DCA real en Cerebro y asistente, preservación de revisión/citas,
fallos macro y éxito de síntesis con nota y callbacks de presupuesto.

La muestra focal de cobertura no cumple el gate global: 89 tests ejecutados
pasaban, pero seleccionar solo 6 servicios deja el gigante chat_service en
24,48% y synthesis en37,14%, por debajo de81%; no se ha bajado el umbral ni
omitido el gate. vix_reader100%, biblioteca89,90%, assistant88,55%, narrative
76,53% en esa muestra. Se añadieron después tests de callbacks/éxito narrative;
la aprobación de cobertura completa sigue pendiente en la suite integral.

Muestra ampliada final: 156 tests verdes, incluyendo fail-closed de narrative,
validación inglesa de synthesis, DCA real, ranking bilingüe y fecha de tesis.
No se consulta macro si el caller no proporciona sesión DB (compatibilidad con
síntesis aislada); con sesión, un fallo macro conserva baseline sin excepción.

## Revisión v3: separación estricta de evidencia

Retirado el contexto macro de TODOS los prompts de síntesis financiera. En
Cerebro y asistente se añade el suplemento determinista después de recuperar
la respuesta principal (también en análisis financiero sin mención VIX). No
se envían la heurística, su nivel ni el suplemento como evidencia al modelo.
La validación de salida de síntesis estricta rechaza además menciones VIX o
spacanpanman: una cita financiera reutilizada no puede colar esa opinión como
hecho. Se conserva el test discriminante del Auditor que simula exactamente
esa respuesta. Su monkeypatch usa raising=False porque se retiró la dependencia
reader_context de la síntesis. Igualmente el test previo de fallo macro ya
no puede forzar una lectura que no existe en narrative.

Cobertura medida con muestra ampliada de157 tests, todos pasaban, gate de
cobertura ROJO42,06% (no se rebajó81%). Por fichero, con ramas:
chat24,44%; synthesis51,64%; biblioteca89,90%; assistant88,83%; narrative97,92%;
reader95,12%. Estos porcentajes son de una muestra, no de la suite integral.
Se añaden después dos tests de suplemento omitido/automático. El gate completo
VM y la cobertura global siguen pendientes. No se presenta la muestra como
aprobación de release.

## Revisión v4: regresiones detectadas por selección ampliada VM

La selección257ficheros sobre37ca62f4 encontró30regresiones de prosa: el
suplemento automático se pegaba incluso en posición/fiscal/conceptos/memoria.
2687tests pasaban, pero la corrida es ROJA y no se excluyen los fallidos.
Se restringe la adición automática a petición explícita de análisis; las
preguntas VIX siguen añadiendo contexto. No se cambia ningún test existente
para aceptar prosa añadida. Nuevos tests fijan saldo/posición/fiscal/conceptos
sin sufijo y analisis financiero con suplemento.

Cobertura37ca62f4 de esos257ficheros, líneas/ramas: chat91,69/83,57;
synthesis96,11/94,77; biblioteca93,03/86,05; narrative98,53/96,43;
assistant95,42/85,42; reader100/100. Se añaden tests de ramas de formato/riesgo
y recuperación RAG con filtros de tenant/empresa, duplicados, IDs inválidos,
texto vacío, point-ID incoherente y proveedor ausente. La medición v4 exacta
sigue pendiente. No se afirma FAV ni cobertura final.
