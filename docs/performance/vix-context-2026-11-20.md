# Contexto VIX, 20 noviembre 2026

## Alcance

Se añade una tarjeta de contexto a Mercado > Régimen. No es una estrategia de
trading. No produce órdenes, cambios de cartera, multiplicadores DCA, alertas
externas ni llamadas a proveedores durante GET.

Usa la observación `vix_us` ya persistida en el snapshot, procedente de FRED
VIXCLS, con unidad índice, fecha de observación y hora de recuperación.
El endpoint añade `vix_context` sin migración ni escribir el snapshot. Funciona
con snapshots anteriores que tengan esa observación trazable; sin ella muestra
el aviso de falta de lectura vigente. No activa ni fuerza la ingesta.

Referencias elegidas como contexto, sin optimizarlas contra retornos:
- valor <15: volatilidad baja;
- valor >30: volatilidad elevada;
- 15 y 30 incluidos: zona intermedia.

Ni alto significa suelo/acción barata ni bajo significa techo/vender. El VIX
refleja volatilidad implícita del S&P 500, no riesgo específico de cada empresa.

## Veracidad y frescura

Solo admite valores numéricos finitos y positivos, origen FRED, URL exacta de
VIXCLS y unidad índice. Rechaza fechas futuras, fecha de observación posterior
a la descarga, descarga futura y horas sin zona. Datos inválidos no llevan
banda ni valor. Datos caducados conservan metadatos para diagnóstico, pero sin
banda; la UI no pinta su valor como lectura vigente.

Tolerancia operativa: hasta 5 días naturales desde la observación (coherente
con la selección existente de VIX en el builder), no desde la descarga ni desde
el snapshot. Más de 5 días: sin contexto activo. No es una regla de calendario
bursátil ni afirma cubrir cualquier cierre extraordinario. Se reevalúa al leer
el endpoint. La caché de la acción existente puede retrasar el cambio hasta
300 segundos. La UI indica cierre diario, no intradía, y no reutiliza las cifras
de la captura de X. Si aún no existe snapshot también aparece el aviso.

## Fuentes consultadas

- https://fred.stlouisfed.org/series/VIXCLS . FRED, fuente original Cboe;
  frecuencia Daily, Close, unidad Index. Consulta del 20 noviembre: cierre
  28,44 del 19 noviembre, actualizado 20 noviembre 08:37 CST. Este número no está
  embebido en código ni se presenta como lectura intradía.
- https://www.cboe.com/tradable_products/vix/ . Definición del índice mediante
  precios de opciones SPX. No se usa su cotización dinámica en esta función.

No hay backtest de rentabilidad de esta regla, ni afirmación de ventaja,
probabilidad de acierto o mejora frente a mantener una cartera.

## Verificación local

- 47 tests backend focales, incluidos clasificador, snapshots, futuro, ingesta
  y migración del módulo de contexto: verdes. Solo fixtures sintéticos/SQLite.
- 32 tests frontend focales de VIX y Régimen ES/EN: verdes.
- TypeScript: los cuatro grupos originales app/tests/scripts/e2e, con sus
  raíces y grafo ambiental completos y límites originales: verdes. Se lanzaron
  separados por el límite de duración de la sesión de comandos, sin cambiar
  tsconfig ni el conjunto de raíces.
- 651 archivos de guards, descubiertos por la misma convención del runner,
  repartidos en 8 grupos disjuntos con los mismos flags de node:test: verdes,
  un skip existente. La primera invocación única se interrumpió por duración;
  no se cuenta como verde.
- ESLint focal, Ruff focal, rutas, contrato e i18n: verdes.
- Capturas del componente real con CSS real en harness local: ES 390 y 1440 px,
  EN 390 px; 4 estados sintéticos juntos solo para QA. Inspección visual sin
  recorte de texto ni scroll horizontal. No son capturas autenticadas de la
  página completa ni evidencia de datos vivos. Producción muestra una tarjeta,
  no las cuatro del harness.

Pendiente auditoría independiente del HEAD, CI y gate completo del corte antes
de desplegar. No se ha tocado producción para este cambio.
