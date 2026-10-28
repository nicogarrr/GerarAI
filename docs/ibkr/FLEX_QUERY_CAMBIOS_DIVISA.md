# Flex Query: cambios de divisa (libro de divisas)

Para que GerarAI calcule la ganancia por convertir USD a EUR hace falta que la
Flex Query traiga tus cambios de divisa reales.

## Qué activar

Sección **Trades** (en el XML, elemento `<Trade>` dentro de `<Trades>`). Los
cambios de divisa de IBKR (p. ej. EUR.USD) salen ahí con `assetCategory="CASH"`
(valor `CASH` del enum AssetClass de ibflex).

Campos que lee el importador, con su nombre XML (ibflex `Types.py`, clase `Trade`;
descripciones en la guía oficial de IBKR, Trades - Flex Statement):

- Asset Class (`assetCategory`), Symbol (`symbol`, p. ej. `EUR.USD`), Buy/Sell
  (`buySell`), Quantity (`quantity`), Trade Price (`tradePrice`), Proceeds
  (`proceeds`), Currency (`currency`), Trade Date (`tradeDate`), Trade ID (`tradeID`).
- Marca también Account ID y Report Date; el importador ya los usa para validar la cuenta.

Opciones de la sección: no filtres por tipo de activo (no marques solo «Stocks»),
o los cambios CASH no llegan. Pide el histórico completo de años: el libro FIFO
necesita todas las ventas y cambios anteriores.

## Cómo se interpreta un `<Trade>` CASH

Par `BASE.QUOTE`. `BUY` compra BASE y gasta QUOTE (importe QUOTE = |proceeds|, que
IBKR da negativo en compras). `SELL` vende BASE y recibe QUOTE. Un `BUY EUR.USD`
es por tanto una conversión USD a EUR. Sin lado, fecha o importe legible la fila se
omite y se cuenta en `fx_conversions_skipped`; nunca se inventa. Las comisiones no
se descuentan del importe cambiado.

## Qué NO se usa

- `FxTransactions` (ibflex `FxTransaction`): es el P/L de divisa que calcula IBKR
  sobre saldos, no tus cambios. Se ignora.
- `ConversionRates`: es el tipo del broker; el cálculo fiscal usa el cambio BCE del día.
- `CashTransactions`: IBKR no los trae como cambios de divisa en las fuentes
  consultadas; no se leen para esto.

## Cuándo sale número

El libro devuelve "no calculado" sin conversiones, y "incompleto" (nunca 0) si:
falta el BCE de algún día, la conversión supera la divisa conocida, no se confirma
el saldo anterior (`POST /api/taxes/report/{año}/regenerate?fx_opening_complete=true`
solo si tu histórico en GerarAI está completo desde el primer dólar), hay cambios
a otra divisa distinta de EUR, o hay compras, dividendos, intereses o comisiones en
esa divisa, que el libro todavía no modela.

## Reglas del libro (doctrina aportada por Auditor 2)

- Entradas: ventas de acciones al tipo con que tributaron (V0282-22) y cambios EUR a divisa
  (valor de adquisición = EUR pagados; añadido propio, art. 35 LIRPF, pendiente de validar).
- Salidas sin resultado propio: compras de valores y comisiones en la divisa (V0282-22, V0706-22).
  El resultado aparece solo al convertir a EUR.
- Pérdida al convertir: no se integra en la parte cubierta por adquisición de la misma divisa en el
  año POSTERIOR a la transmisión, solo posterior y solo la misma divisa (art. 33.5.e LIRPF, V1613-25; AEAT, Manual práctico IRPF 2025, https://sede.agenciatributaria.gob.es/Sede/ayuda/manuales-videos-folletos/manuales-practicos/irpf-2025/c11-ganancias-perdidas-patrimoniales/ganancias-perdidas-patrimoniales-que-no-bi/perdidas-patrimoniales-que-no-se-tales.html), no 2 meses. Se suma al valor de los lotes
  readquiridos. Si la ventana de 1 año sigue abierta a fecha de los datos, queda "incompleto".
- Dividendos e intereses como entradas: sin consulta, solo analogía. Solo con
  `?fx_income_by_analogy=true`, etiquetado "criterio por analogía, sin consulta".
- Fondos/ETF comprados con divisa propia (V0775-21): fuera de alcance, "incompleto".

## Fuentes

- https://github.com/csingley/ibflex (`ibflex/Types.py`: `Trade`, `FxTransaction`,
  `ConversionRate`; `ibflex/enums.py`: `AssetClass.CASH`)
- https://www.ibkrguides.com/reportingreference/reportguide/tradesfq.htm
- DGT V2466-08, V0234-07, V0282-22; art. 14.2.e LIRPF (criterio del libro).
- No se envía ningún token: el importador usa el XML que ya recibe el conector.
