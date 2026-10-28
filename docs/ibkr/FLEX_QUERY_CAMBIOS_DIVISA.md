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

## Fuentes

- https://github.com/csingley/ibflex (`ibflex/Types.py`: `Trade`, `FxTransaction`,
  `ConversionRate`; `ibflex/enums.py`: `AssetClass.CASH`)
- https://www.ibkrguides.com/reportingreference/reportguide/tradesfq.htm
- DGT V2466-08, V0234-07, V0282-22; art. 14.2.e LIRPF (criterio del libro).
- No se envía ningún token: el importador usa el XML que ya recibe el conector.
