# Flex Query: secciones y campos a marcar

Objetivo: que la Flex Query de IBKR traiga todos los campos posibles. El importador guarda cada fila cruda (todos sus atributos) en `ibkr_raw_rows`, se use o no todavia, y cada calculo fiscal se desbloquea con los campos de abajo.

Reglas:
- El token de la Flex Web Service NUNCA va por chat, ni en logs, ni en este repositorio. Se guarda solo por el enlace seguro de la boveda.
- Los nombres de campo son los de la guia oficial de IBKR (columna `Field` de cada pagina). El nombre del atributo XML sale de ibflex (`Types.py`) y no siempre coincide letra por letra; el importador guarda lo que llegue.
- Marca TODOS los campos de cada seccion salvo que IBKR no los ofrezca para tu cuenta. Pide el historico completo de años en secciones con fechas.
- Formato de fecha y hora: elige el que lleva hora y separador `;` (p. ej. `20250102;093000`), que es el que ya lee el importador. Que esa opcion exista con ese nombre en la pantalla de la Flex Query no esta verificado.

## Trades (Trades)

Fuente oficial: https://www.ibkrguides.com/reportingreference/reportguide/tradesfq.htm

Campos oficiales (marcar todos): Account ID; Account Alias; Model; Currency; Asset Class; FX Rate to Base; Symbol; Description; Conid; ListingExchange; UnderlyingConID; Security ID; Security ID Type; CUSIP; ISIN; FIGI; UnderlyingListingExchange; Underlying Conid; Underlying Symbol; Issuer; Trade ID; Report Date; Trade Date; Trade Time; Settle Date Target; Transaction Type; Exchange; Quantity; Trade Price; Multiplier; Trade Money; Proceeds; Taxes; IB Commission; IB Commission Currency; Close Price; Open/Close Indicator; Notes/Codes; Cost Basis; Realized PNL; MTM PNL; Strike; Expiry; Put/Call; Principal Adjustment Factor; Buy/Sell; IB Order ID; IB Execution ID; Brokerage Order ID; Order Reference; Volatility Order Link; Order Placement Time; Clearing Firm ID; Exchange Order ID; External Execution ID; Order Time; Open Date Time; Holding Period Date Time (Wash Sales); When Realized (Wash Sales); When Reopened (Wash Sales); Original Trade Price; Original Trade Date; Original Trade ID; Original Order ID; Level of Detail; Change in Price; Change in Quantity; Net Cash; Order Type; Trader ID; Is API Order; Commodity; Delivery; Weight; Fineness; Serial Number.

Que desbloquea:
- Trade Date, Trade Time: orden intradia de compras, ventas y cambios: regla del mismo dia del libro de divisas (anti-recompra de 1 año, art. 33.5.e) y desempate del FIFO de valores. Sin hora, el mismo dia bloquea por criterio conservador.
- Asset Class, Symbol, Buy/Sell, Quantity, Trade Price, Proceeds, Currency, Trade ID: FIFO de valores y libro de divisas. Asset Class=CASH identifica los cambios EUR.USD (Proceeds negativo en compras, segun IBKR).
- IB Commission, IB Commission Currency, Taxes, Trade Money, Net Cash: comisiones y tasas como salida de divisa sin resultado (V0706-22) y coste de adquisicion/venta.
- Conid, ISIN, CUSIP, FIGI, Security ID, Security ID Type, ListingExchange: identificacion estable del valor, Modelo 720 y cruce con emisores.
- Open/Close Indicator, Notes/Codes, Cost Basis, Realized PNL, MTM PNL, Original Trade Price, Original Trade Date, Original Trade ID: conciliar el FIFO propio contra el del broker y detectar correcciones y anulaciones.
- Open Date Time, Holding Period Date Time (Wash Sales), When Realized (Wash Sales), When Reopened (Wash Sales): comparar la anti-recompra propia con el calculo de IBKR (norma de EEUU, solo contraste).
- IB Order ID, IB Execution ID, Order Reference, Brokerage Order ID, Exchange Order ID, External Execution ID, Order Time, Order Placement Time, Order Type: agrupar ejecuciones parciales de una orden y auditar.
- Level of Detail: marca todos los niveles que ofrezca la query (ejecucion, orden, lotes cerrados): no verificado cuales ofrece la pantalla.
- FX Rate to Base, Report Date, Settle Date Target: contraste con el BCE y fecha de liquidacion (hoy se usa fecha de operacion).

## CashTransactions (Cash Transactions)

Fuente oficial: https://www.ibkrguides.com/reportingreference/reportguide/cash%20transactionsfq.htm

Campos oficiales (marcar todos): Account ID; Account Alias; Model; Currency; Asset Class; FX Rate to Base; Symbol; Description; Conid; Security ID; Security ID Type; CUSIP; ISIN; FIGI; Underlying Conid; Underlying Symbol; Issuer; Date/Time; Amount; Type; Trade ID; 871(m) Withholding; Code.

Que desbloquea:
- Date/Time, Amount, Type, Currency, Symbol, Trade ID, Code: dividendos, retenciones, intereses y comisiones por fecha y hora; entradas y salidas de divisa por analogia (fx_income_by_analogy).
- 871(m) Withholding: retenciones de EEUU sobre derivados, solo informativo.
- ISIN, Conid, CUSIP, FIGI: atribuir cada dividendo al valor correcto.

## ConversionRates (Currency Conversion Rate)

Fuente oficial: https://www.ibkrguides.com/reportingreference/reportguide/currency%20conversion%20ratefq.htm

Campos oficiales (marcar todos): Date/Time; From Currency; To Currency; Rate.

Que desbloquea:
- Date/Time, From Currency, To Currency, Rate: tipo de IBKR por dia: solo contraste. El calculo fiscal usa el BCE del dia (no sustituirlo).

## CashReport (Cash Report)

Fuente oficial: https://www.ibkrguides.com/reportingreference/reportguide/cash%20reportfq.htm

Campos oficiales (marcar todos): Account ID; Account Alias; Model; Currency; From Date; To Date; Starting Cash; Client Fees; Commissions; Commission Credits; Billable Commissions; Deposits/Withdrawals; Deposits; Withdrawals; Account Transfers; Linking Adjustments; Internal Transfers; Debit Card Activity; Bill Pay Activity; Dividends; Broker Interest Paid and Received; Bond Interest Paid and Received; Cash Settling MTM; Net Trades Sales; Net Trades Purchases; Other Fees; Advisor Fees; Fees Receivables; Fees Receivables Securities; Fees Receivables Commodities; Fees Receivables IB UKL; Payment in Lieu; Transaction Tax; Tax Receivables; Withholding Tax; 871(m) Withholding; FX Translation Gain/Loss; Ending Cash; Ending Settled Cash; Report Date.

Que desbloquea:
- Starting Cash, Ending Cash, Ending Settled Cash, Report Date, From Date, To Date: saldo inicial por divisa: permite confirmar el saldo de dolares anterior al ejercicio (fx_opening_complete) en vez de declararlo a mano.
- Commissions, Client Fees, Other Fees, Advisor Fees, Dividends, Withholding Tax, Broker Interest Paid and Received, Net Trades Sales, Net Trades Purchases, Deposits/Withdrawals, Account Transfers, Internal Transfers, FX Translation Gain/Loss, Payment in Lieu, Transaction Tax: cuadrar el libro de divisas contra los movimientos totales por divisa y detectar flujos que falten.

## OpenPositions (Open Positions)

Fuente oficial: https://www.ibkrguides.com/reportingreference/reportguide/open%20positionsfq.htm

Campos oficiales (marcar todos): Account ID; Account Alias; Model; Currency; Asset Class; FX Rate to Base; Symbol; Description; Conid; Security ID; Security ID Type; CUSIP; ISIN; FIGI; Underlying Conid; Underlying Symbol; Issuer; Report Date; Quantity; Multiplier; Mark Price; Position Value; Open Price; Cost Basis Price; Cost Basis Money; Percent of NAV; FIFO Unrealized PNL; Side; Level of Detail; Open Date Time; Holding Period Date Time (Wash Sales); Code; Originating Order ID; Originating Transaction ID; Accrued Interest; Commodity; Delivery; Weight; Fineness; Serial Number.

Que desbloquea:
- Level of Detail: segun IBKR: Summary o Lot. Marcar Lot da el lote de cada posicion (fecha de apertura, coste) para contrastar el FIFO.
- Open Date Time, Originating Transaction ID, Originating Order ID, Holding Period Date Time (Wash Sales), Cost Basis Price, Cost Basis Money, Open Price, FIFO Unrealized PNL: contraste de lotes abiertos y de la base de coste con el FIFO propio y el diferido por anti-recompra.
- Quantity, Mark Price, Position Value, Percent of NAV, Side, Accrued Interest, Code, Report Date: posiciones y Modelo 720 a 31 de diciembre.

## Transfers (Transfers)

Fuente oficial: https://www.ibkrguides.com/reportingreference/reportguide/transfersfq.htm

Campos oficiales (marcar todos): Account ID; Account Alias; Model; Currency; Asset Class; FX Rate to Base; Symbol; Description; Conid; Security ID; Security ID Type; CUSIP; ISIN; FIGI; Underlying Conid; Underlying Symbol; Issuer; Report Date; Date; Type; Direction; Transfer Company; Transfer Account; Transfer Account Name; Quantity; Transfer Price; Position Amount; Position Amount in Base; P/L Amount; P/L Amount in Base; Code; Transaction ID.

Que desbloquea:
- Date, Type, Direction, Quantity, Transfer Price, Position Amount, P/L Amount, Transfer Company, Transfer Account, Transaction ID: traspasos ACATS y entre cuentas: lotes que llegan sin compra en la cuenta (hoy salen como venta sin compra).

## CorporateActions (Corporate Actions)

Fuente oficial: https://www.ibkrguides.com/reportingreference/reportguide/corporate%20actionsfq.htm

Campos oficiales (marcar todos): Account ID; Account Alias; Model; Currency; Asset Class; FX Rate to Base; Symbol; Description; Conid; Security ID; Security ID Type; CUSIP; ISIN; FIGI; Underlying Conid; Underlying Symbol; Issuer; Multiplier; Expiry; Put/Call; Principal Adjustment Factor; Report Date; Date/Time; Amount; Proceeds; Value; Quantity; Realized P/L; MTM PNL; Code; Type; Transaction ID.

Que desbloquea:
- Date/Time, Type, Quantity, Amount, Proceeds, Value, Realized P/L, Transaction ID, Code, Principal Adjustment Factor: splits, fusiones y escisiones: ajuste de lotes y de la base de coste.

## Secciones opcionales (contraste y cuadre)

## StmtFunds (Statement of Funds)

Fuente oficial: https://www.ibkrguides.com/reportingreference/reportguide/statement%20of%20fundsfq.htm

Campos oficiales (marcar todos): Account ID; Account Alias; Model; Report Date; Date; Settle Date; Activity Code; Activity Description; Debit; Credit; Balance; Level of Detail; Currency; Amount; Trade Code; Trade ID; Trade Quantity; Trade Gross; Trade Commission; Trade Tax; Asset Class; Symbol; Description; Conid; Security ID; Security ID Type; CUSIP; ISIN; FIGI; Underlying Conid; Underlying Symbol; Issuer; Transaction ID; Commodity; Delivery; Weight; Fineness; Serial Number; ADJ; ASSIGN; BUY; CA; CINT; CO; CORP; DEL; DEP; DINT; DIV; DIVR; EXE; EXP; FOREX; FRTAX; GEA; INTP; INTR; MFEE; OFEE; PIL; REC; SELL; STAX; TTAX; WITH.

Que desbloquea:
- movimientos de caja por divisa con saldo corrido: cuadre del libro de divisas.

## FxPositions (Forex Balances) (Forex Balances)

Fuente oficial: https://www.ibkrguides.com/reportingreference/reportguide/forex%20balances_fq.htm

Campos oficiales (marcar todos): Account ID; Account Alias; Model; Asset Class; Report Date; Functional Currency; FX Currency; Quantity; Cost Price; Cost Basis; Close Price; Value; Unrealized P/L; Code; Lot Description; Lot Open Date/Time; Level of Detail.

Que desbloquea:
- saldo de divisas por lote de IBKR: contraste del FIFO de dolares.

## ChangeInDividendAccruals (Change in Dividend Accruals)

Fuente oficial: https://www.ibkrguides.com/reportingreference/reportguide/change%20in%20dividend%20accrualsfq.htm

Campos oficiales (marcar todos): Account ID; Account Alias; Model; Currency; Asset Class; FX Rate to Base; Symbol; Description; Conid; Security ID; Security ID Type; CUSIP; ISIN; FIGI; Underlying Conid; Underlying Symbol; Issuer; Date; Ex Date; Pay Date; Quantity; Tax; Fee; Gross Rate; Gross Amount; Net Amount; Code; FromAcct; ToAcct; Report Date.

Que desbloquea:
- dividendos devengados vs cobrados (periodificacion).

## OpenDividendAccruals (Open Dividend Accruals)

Fuente oficial: https://www.ibkrguides.com/reportingreference/reportguide/open%20dividend%20accrualsfq.htm

Campos oficiales (marcar todos): Account ID; Account Alias; Model; Currency; Asset Class; FX Rate to Base; Symbol; Description; Conid; Security ID; Security ID Type; CUSIP; ISIN; FIGI; Underlying Conid; Underlying Symbol; Issuer; Ex Date; Pay Date; Quantity; Tax; Fee; Gross Rate; Gross Amount; Net Amount; Code; FromAcct; ToAcct.

Que desbloquea:
- dividendos devengados pendientes de cobro.

## Que se usa hoy y que solo se guarda

- Se usan hoy: Trades (valores y cambios CASH), CashTransactions, CashReport (saldos), OpenPositions (posiciones), CorporateActions (como movimientos).
- Solo se guardan crudos, sin calculo todavia: ConversionRates, Transfers, lotes de OpenPositions, StmtFunds, FxPositions, devengos de dividendos, y cualquier atributo o seccion que hoy no se lea.

## No verificado
- Como nombra la pantalla de IBKR cada opcion de formato y los niveles de Level of Detail de Trades.
- Que campos ofrece tu cuenta concreta (algunos dependen del tipo de cuenta y de los activos).
- El nombre exacto del atributo XML de cada campo: se contrasto con ibflex, no con un XML real de Nico.

## Fuentes
- https://www.ibkrguides.com/reportingreference/reportguide/activity%20flex%20query%20reference.htm
- https://www.ibkrguides.com/reportingreference/reportguide/tradesfq.htm
- https://www.ibkrguides.com/reportingreference/reportguide/cash%20transactionsfq.htm
- https://www.ibkrguides.com/reportingreference/reportguide/currency%20conversion%20ratefq.htm
- https://www.ibkrguides.com/reportingreference/reportguide/cash%20reportfq.htm
- https://www.ibkrguides.com/reportingreference/reportguide/open%20positionsfq.htm
- https://www.ibkrguides.com/reportingreference/reportguide/transfersfq.htm
- https://www.ibkrguides.com/reportingreference/reportguide/corporate%20actionsfq.htm
- https://www.ibkrguides.com/reportingreference/reportguide/statement%20of%20fundsfq.htm
- https://www.ibkrguides.com/reportingreference/reportguide/forex%20balances_fq.htm
- https://www.ibkrguides.com/reportingreference/reportguide/change%20in%20dividend%20accrualsfq.htm
- https://www.ibkrguides.com/reportingreference/reportguide/open%20dividend%20accrualsfq.htm
- https://github.com/csingley/ibflex (`ibflex/Types.py`)
