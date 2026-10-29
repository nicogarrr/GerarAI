# Valoración y salud financiera

## Alcance

Un solo bloque compartido por cartera, watchlist y Mercado (Descubrir), mediante
`GET /api/valuation/summary?tickers=...`. Máximo 60 tickers, lectura por lotes,
sin llamadas a proveedores, generación de modelos, persistencia ni cambios DCA.
La precedencia de `fair_value_service` no cambia. El margen de seguridad es
`(valor - precio) / valor`, solo si ambas divisas coinciden y el valor es
publicable. No es el potencial alcista `(valor - precio) / precio` que ya se
muestra en otros contextos.

El DCF inverso procede de la última versión fundamental publicable y se muestra
con fecha, precio del modelo y versión. Es un escenario separado de la tesis,
no una predicción ni un nuevo motor. Un modelo nuevo no publicable invalida
la lectura inversa del modelo anterior.

## Piotroski

Las nueve condiciones usan ejercicios completos explícitos (FY), con fuente y
sin cifras ajustadas/inferidas. ROA y rotación usan activos iniciales; la deuda
no corriente se divide por activos medios. Se exige evidencia explícita de
emisiones de capital común: ausencia del hecho no significa cero. No se usa
variación de acciones diluidas como sustituto de emisión. Cada condición incluye
fórmula, punto o falta de dato, IDs y enlaces de documentos con sus cifras.
El beneficio disponible es `net_income` reportado, sin reconstruir partidas
extraordinarias ausentes. Esto limita la comparación estricta con la variable
"income before extraordinary items" del estudio original.

El score solo se publica con los nueve puntos evaluados. No se reescala un
score parcial ni se convierten datos ausentes en puntos fallidos. Tres cierres
consecutivos son necesarios para comparar ratios con activos iniciales.
Se rechazan monedas distintas, calendarios desplazados, cierres futuros y un
último ejercicio de más de 550 días.

Fuente: Piotroski (2000), secciones 2.3.1 a 2.3.3:
https://www.ivey.uwo.ca/media/3775523/value_investing_the_use_of_historical_financial_statement_information.pdf

El estudio original es un filtro de empresas de alto book-to-market, no una
calibración universal del potencial de rentabilidad. La UI lo llama indicador
contable, no recomendación.

## Altman

Se usa Z'' no financiero: `6.56 WC/A + 3.26 RE/A + 6.72 EBIT/A + 1.05 equity/liabilities`.
Patrimonio contable y sin constante +3.25 de mercados emergentes. EBIT procede
de beneficio antes de impuestos + intereses, nunca se sustituye silenciosamente
por resultado operativo. Sin dato, no evaluable. No se presenta como
probabilidad de quiebra ni rating de crédito.

Fuente: Altman, documento de 2002, p. 17-18:
https://w4.stern.nyu.edu/finance/docs/WP/2002/pdf/wpa02052.pdf

Ambos indicadores se excluyen para financieras, bancos, aseguradoras, REIT,
fondos/ETF y empresas preingresos identificadas; un sector desconocido no se
clasifica por intuición.

## Datos y activación

Se añaden cuatro conceptos SEC a la ingesta existente: AssetsCurrent,
LiabilitiesCurrent, LongTermDebtNoncurrent y RetainedEarningsAccumulatedDeficit.
Se poblarán en los refrescos ordinarios posteriores; esta PR no hace backfill
ni toca producción. Hasta entonces puede aparecer "No evaluable". Ceros
explícitos son datos válidos, silencios del proveedor no.

Selecciona fuente oficial antes que proveedores y última reexpresión por fecha
de publicación. Un documento de otro tenant no se usa. Los cálculos rechazan
filas sin fuente, seed, ajustes y datos futuros.

## Validación local

- 30 tests focales backend: cobertura de los dos servicios nuevos 98,94%.
- 74 tests de regresión de persistencia, ingesta SEC y valoración: verdes.
- 5 tests frontend: 100% líneas y 90,27% ramas de componente/helper nuevos.
- TypeScript y Ruff globales verdes; ESLint global sin errores.
- Capturas locales con datos ficticios a 390/1280 px, sin overflow horizontal.
- Suite completa backend NO certificada: se cortó una primera ejecución tras
  105 segundos (~6%, sin fallos hasta allí). El publisher debe completar ese
  gate antes de afirmar pytest global verde.

No hay merge ni despliegue desde este trabajo. Requiere PR lista, label
`instinct`, auditoría favorable por el SHA publicado y gate global pendiente.
