# Comparación DCA: rentabilidad y riesgo
30 de octubre de 2026. Datos hasta septiembre de 2026 cerrado.

## Respuesta
En esta prueba, añadir caída desde máximos no demuestra más rentabilidad que aportar siempre lo mismo e invertirlo. La combinación mejora algo el resultado del sistema por niveles, pero el DCA plano gana en capital final en los 15 ETF durante el periodo largo. Los niveles conservan más caja y reducen las caídas. No hay un ganador universal ni prueba suficiente para cambiar producción.

## Diseño fijado antes de medir
- Control: DCA plano, 100 USD invertidos cada mes.
- Nico-v1: descuento frente a SMA mensual de hasta 30 meses, ajustado por volatilidad; fórmula actual sin cambios.
- Caída36m: máximos de cierres mensuales de los últimos36meses, umbrales15/25/40% para2X/3X/4X.
- Combinación: máximo de los dos niveles. No se optimizaron umbrales.
- Presupuesto idéntico100USD/mes. En los sistemas por niveles se invierten50USD x nivel, hasta agotar caja. El resto queda en caja al0%. No deuda, ventas ni aportaciones extra. Recortes se tratan como1X, como el comparador existente.
- Señal del mes terminado, compra al primer cierre diario del mes siguiente. Se excluye octubre2026 incompleto. Serie ajustadaUSD, dividendos reinvertidos de forma aproximada mediante ajuste del proveedor.
- Coste10pb por compra y liquidación terminal; sensibilidad0/25pb. Sin impuestos ni divisaEUR. Fracciones de participación permitidas.
- Máximo drawdown sobre índice diario unitizado con caja, descontando aportaciones externas; no caída del saldo nominal falseada por ingresos. TIR anualizada de flujos mensuales, aproximación mensual, no XIRR por día exacto.

## Resultados principales
Medianas por instrumento, no rentabilidad de una cartera conjunta. Periodo largo desde enero2003 cuando existe historia suficiente, hasta septiembre2026. Algunos instrumentos empiezan más tarde; cada comparación usa exactamente las mismas fechas y dinero para sus cuatro reglas.

|Panel|Regla|Instrumentos|Capital final frente a plano|TIR mediana anual|Drawdown mediano|Meses señal2X+|Meses4X|
|---|---|---:|---:|---:|---:|---:|---:|
|etf|plain|15|+0.00%|9.49%|-58.65%|0|0|
|etf|nico_v1|15|-18.66%|8.63%|-41.71%|767|273|
|etf|drawdown36|15|-17.87%|8.79%|-40.49%|851|156|
|etf|combination_max|15|-15.13%|8.97%|-42.63%|975|309|
|stock_biased|plain|49|+0.00%|10.41%|-65.31%|0|0|
|stock_biased|nico_v1|49|-12.94%|9.21%|-59.17%|3215|1026|
|stock_biased|drawdown36|49|-10.40%|9.09%|-61.49%|4421|1441|
|stock_biased|combination_max|49|-8.09%|9.20%|-61.81%|4640|1737|

Las señales se cuentan por instrumento-mes; no son operaciones independientes ni tamaño muestral estadístico. GOOG/GOOGL están correlacionados y las49acciones no son49apuestas independientes.

## Regímenes separados:15ETF
Capital final mediano frente a plano,10pb. Cada tramo empieza con caja y cartera a cero.

|Periodo|Nico-v1|Caída36m|Combinación|
|---|---:|---:|---:|
|2003-2009|+1.14%|+1.24%|+1.75%|
|2010-2019|-21.49%|-18.36%|-18.36%|
|2020-2026|-8.31%|-9.55%|-8.31%|

## Qué está medido y qué no
Medido:64instrumentos útiles,2.684resultados de instrumento/ventana/coste/regla, operaciones y curva diaria archivadas para el periodo largo10pb. Se probaron también ventanas2005-09/2010-14/2015-19/2020-24/2025-26, no son un barrido de todas las ventanas rodantes. Se descargaron66símbolos; WBD y WBA fallaron y quedan registrados, sin sustituir por otro ticker.

El panel de15ETF usa fondos de índices/regiones/sectores con composición interna que cambia en el tiempo. Evita reconstruir el SP500 de2003 usando los ganadores de2026, pero no elimina selección ex post de los fondos supervivientes ni solapamiento entre ellos. No es un universo completo libre de sesgo.

El panel de49acciones es diagnóstico y tiene sesgo de supervivencia/selección. No hay base gratuita completa de retiradas, quiebras y contraprestaciones. Identidad y corporate actions de históricos complejos como PARA/GE/T/M, adquisiciones no están auditados por emisor. Las colas extremas de ese panel no autorizan conclusiones de inversión. No se ha demostrado ausencia de ticker reutilizado. No presentar ese panel como confirmación principal.

Los ajustes históricos son los actuales del proveedor, no una base vintage point-in-time. Comparaciones y prueba de truncado evitan que la fórmula mire precios futuros, pero no prueban que cada dato fuese idéntico al publicado entonces. La fórmula Nico-v1 ya fue calibrada con históricos, por lo que estas ventanas no son un holdout totalmente virgen. Costes, reinversión y ejecución son supuestos del modelo, no operaciones reales. Una caja remunerada cambiaría la comparación, igual que otra política de despliegue; esta prueba evalúa fórmula y política de caja juntas.

## Verificaciones
5tests del experimento: truncar futuro no cambia señales pasadas; señal anterior a ejecución; igual presupuesto/fechas entre estrategias; caja no negativa; costes reducen valor; precios constantes no inventan rentabilidad/drawdown. No producción ni cambios de fórmula. Evidencia reproducible adjunta con manifiesto, hashes, script, resultados y curvas.

## Recomendación
No activar caída desde máximos como aumento automático de aportación por haber caído mucho. Añadirla como dato explicativo separado del nivel es razonable; cambiar la fórmula requiere elegir primero objetivo (capital final o menor drawdown) y validar un holdout prospectivo con datos de retiradas y política de caja explícita. Hoy la evidencia favorece DCA plano para capital final en el panelETF, no una promesa de rentabilidad futura.

## Fuentes
Precios: Yahoo Finance vía yfinance1.7.0. El manifiesto incluyeURL y fecha para cada símbolo; no son precios oficiales del mercado.
- https://finance.yahoo.com/quote/AMZN/history/
- https://finance.yahoo.com/quote/NOW/history/
- https://finance.yahoo.com/quote/META/history/
- https://finance.yahoo.com/quote/GOOGL/history/
- https://finance.yahoo.com/quote/GOOG/history/
- https://historicaldata.net/survivorship.html
- https://cleartape.ai/academy/quant-trading/data-traps
- https://en.wikipedia.org/wiki/Historical_components_of_the_Dow_Jones_Industrial_Average
- https://xfinlink.com/historical-dow-jones-constituents
- https://www.ssga.com/us/en/intermediary/etfs/state-street-spdr-sp-500-etf-trust-spy
- https://www.invesco.com/qqq-etf/en/about.html
- https://www.invesco.com/qqq-etf/en/market-outlook/get-to-know-qqq-charting-25-years-of-performance.html
