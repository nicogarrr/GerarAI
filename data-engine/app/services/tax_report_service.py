"""Fiscal-year tax computation for the private portfolio.

The report follows Spanish IRPF conventions:

- Realized gains/losses use FIFO lot accounting on sells (required by law for
  homogeneous securities). Each buy lot's unit cost includes acquisition fees;
  a deferred wash-sale loss is added separately to preserve that basis. FX
  conversion of securities gains uses the sale-date FX rate once. Later
  currency disposal is separate; purchase-date FX does not change that gain.
- Dividends are grouped by company and converted at the payment date rate.
- Withholding is matched from cash transactions whose type contains
  "withholding" / "tax" (IBKR reports gross dividend and withheld tax as
  separate CashTransaction rows in the same statement).
- Wash-sale (art. 33.5.f LIRPF, valores cotizados): a realized loss is NOT
  computable when homogeneous shares are repurchased within two months
  before or after the sale AND those shares remain in the portfolio after
  the sale (Manual Renta 2025, cap. 11, apdo. E: "dichos valores continúan
  en el patrimonio del contribuyente tras la transmisión"; if nothing
  remains, "la pérdida patrimonial podrá imputarse íntegramente").
  Backward repurchases follow the Manual's proportionality: recompra =
  min(remanente tras la venta, comprado en los 2 meses previos), with the
  Manual's single-purchase exception (only one buy op in the prior window
  and zero holdings at its start → no limitation; the initial purchase
  itself is not a repurchase). The blocked loss is absorbed FIFO onto the
  oldest surviving in-window lots' cost basis, so it surfaces when those
  lots are sold. Forward (posterior) repurchases are also taken into
  account ("deben tenerse en cuenta las compras posteriores"),
  blocking proportionally up to the posterior buy quantity; the Manual gives no
  explicit posterior prorrata, so this is a documented interpretation.
  Losses whose forward window extends beyond the available data are
  reported as provisionally computable and flagged per sale and in the
  summary. The convention is labeled in the report
  (wash_sale_rule = "es-irpf-2m", wash_sale_basis = "manual-aeat-2025")
  and applies only to this Spanish IRPF report.
  ORIENTATIVO: this report is a working paper ("orientativo, no apto para
  declarar") until signed off by a colegiado fiscal adviser. See
  summary.fiscal_disclaimer.
  Limitation: Company metadata has no ISIN/security identifier or listing
  flag, so the engine cannot prove that a ticker is a listed homogeneous
  security or distinguish dividends from unlisted instruments. No such
  inference is made here.
"""

from __future__ import annotations

from collections import deque
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal

from dateutil.relativedelta import relativedelta
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import (
    Company,
    FxConversion,
    Position,
    TaxReport,
    Tenant,
    Transaction,
)
from app.services.currency_ledger import (
    ANALOGY_LABEL,
    COMPUTED,
    CRITERION,
    INCOMPLETE,
    SOURCES,
    Conversion,
    CurrencyLot,
    Outflow,
    compute_currency_ledger,
    lots_from_sales,
)
from app.services.portfolio_fx_service import TAX_CURRENCY, PortfolioFXService
from app.services.tax_irpf_filing import (
    CARRYFORWARD_WINDOW_YEARS,
    SPECIAL_PAYMENT_TOKENS,
    build_casillas,
    build_double_taxation,
    build_interest,
    build_loss_compensation,
    integrate_savings_base,
)
from app.services.tax_report_versioning import SECURITIES_FX_CRITERION, report_versioning
from app.valuation.currency import normalize_currency

FIFO_METHOD = "fifo"
AVERAGE_METHOD = "average"

# Spanish IRPF wash-sale convention (art. 33.5.f LIRPF, listed securities),
# developed by Manual Renta 2025 cap. 11 apdo. E (procedimiento de recompra):
# homogeneous shares acquired within two months before or after a loss sale
# block the loss only while they remain in the portfolio after the sale,
# proportionally (min(remanente, comprado previo)), absorbed FIFO.
WASH_SALE_RULE_ID = "es-irpf-2m"
WASH_SALE_BASIS = "manual-aeat-2025"
WASH_SALE_WINDOW = relativedelta(months=2)

# Working-paper label: the figures follow the Manual's procedure but the
# ledger has no ISIN/listing proof and no external-broker coverage, so the
# report must be presented as orientativo until a fiscal adviser signs off.
FISCAL_DISCLAIMER = (
    "Informe orientativo, no apto para declarar sin la validación de un "
    "asesor fiscal: wash-sale según procedimiento del Manual AEAT 2025 "
    "(art. 33.5.f LIRPF, proporcionalidad y FIFO); sin ISIN/cotización ni "
    "cobertura multibróker verificadas."
)

DIVIDEND_ACTIONS = {"dividend", "div", "cash_dividend", "withholding"}
def _execution_time(transaction) -> str:
    """HHMMSS de la ejecución si el ledger la trae, si no cadena vacía."""
    payload = transaction.raw_payload if isinstance(transaction.raw_payload, dict) else {}
    raw = str(payload.get("dateTime") or "")
    for sep in (";", " ", "T"):
        if sep in raw:
            digits = "".join(ch for ch in raw.split(sep, 1)[1] if ch.isdigit())
            if len(digits) >= 4:
                return digits[:6].ljust(6, "0")
    return ""


def _fx_time(conversion) -> str:
    """HHMMSS de un cambio de divisa: dateTime del Flex o, si no, tradeTime."""
    found = _execution_time(conversion)
    if found:
        return found
    payload = conversion.raw_payload if isinstance(conversion.raw_payload, dict) else {}
    digits = "".join(ch for ch in str(payload.get("tradeTime") or "") if ch.isdigit())
    return digits[:6].ljust(6, "0") if len(digits) >= 4 else ""


def _fifo_sort_key(transaction) -> tuple:
    action = (transaction.action or "").lower()
    return (
        transaction.trade_date,
        _execution_time(transaction),
        0 if action in BUY_ACTIONS else 1,
        transaction.id or 0,
    )


#: Antigüedad máxima del tipo de cambio aceptado para una operación. El BCE
#: no publica en fines de semana ni festivos TARGET (Navidad, Año Nuevo,
#: Viernes Santo, Lunes de Pascua, 1 de mayo): el hueco más largo entre dos
#: publicaciones es de 4 días (Viernes Santo → martes de Pascua). 7 días da
#: margen sin aceptar un tipo de otra semana.
MAX_FX_AGE_DAYS = 7


def _rate_not_older_than(
    table: dict[tuple[str, str], list[tuple[date, Decimal]]],
    *,
    quote_currency: str,
    base_currency: str,
    as_of: date,
    max_age_days: int,
) -> Decimal | None:
    """Como ``PortfolioFXService.rate_from_table`` pero sin tipos caducados.

    Devuelve el último tipo publicado en o antes de ``as_of`` solo si tiene
    como mucho ``max_age_days`` días; si no, ``None`` (importe desconocido).
    """
    from bisect import bisect_right

    quote, quote_divisor = normalize_currency(quote_currency)
    base, base_divisor = normalize_currency(base_currency)
    factor = Decimal(base_divisor) / Decimal(quote_divisor)
    if quote == base:
        return factor
    for key, invert in (((base, quote), False), ((quote, base), True)):
        series = table.get(key)
        if not series:
            continue
        idx = bisect_right(series, (as_of, Decimal("Infinity"))) - 1
        if idx < 0:
            continue
        rate_date, rate = series[idx]
        if (as_of - rate_date).days > max_age_days or not rate:
            continue
        return factor / rate if invert else rate * factor
    return None


def _defer_base(lot: dict, take: Decimal, sale: dict) -> None:
    """Difiere la pérdida bloqueada (wash-sale) también en divisa base.

    Conserva trazabilidad del importe de la pérdida al cambio de su venta.
    El cálculo DGT de una venta posterior usa el diferido nativo y lo convierte
    al cambio de esa venta posterior, no suma dos tramos FX históricos.
    deferred_base puede ser None y no sustituye esa base nativa.
    """
    if sale.get("loss_unknown"):
        # Pérdida de una venta descubierta: se calculó con coste cero en el
        # exceso, así que no es una cifra. El lote que la absorbe queda con
        # base (y diferido) desconocidos, nunca con un importe inventado.
        lot["deferred_unknown"] = True
        lot["deferred_base"] = None
        return
    if lot["deferred_base"] is None:
        return
    if sale["loss_per_share_base"] is None:
        lot["deferred_base"] = None
        return
    lot["deferred_base"] += take * sale["loss_per_share_base"]


SELL_ACTIONS = {"sell", "sold"}
BUY_ACTIONS = {"buy", "bot", "b"}

#: Movimientos de caja del ledger: nunca denominados en acciones. La forma
#: canonica de la fila es el IMPORTE en ``price`` con ``quantity`` 0 o 1
#: (``quantity=0`` es legitimo para caja; el importador IBKR escribe
#: ``quantity=1, price=amount``). Antes el informe fiscal leia
#: ``price or quantity`` y el resto de consumidores multiplicaban
#: ``quantity * price``: una entrada manual ``{"dividend", 100, 0.25}`` (= 25)
#: se declaraba como 0,25 en la declaration y como 25,00 en el XIRR, un
#: error de 100x en una cifra que acaba en un impreso fiscal.
CASH_LEDGER_ACTIONS = frozenset(
    {"dividend", "div", "cash_dividend", "withholding", "interest", "fee", "cash_misc"}
)
#: Cantidades admitidas en una fila de caja bajo la convencion canonica.
CASH_UNIT_QUANTITIES = (Decimal("0"), Decimal("1"))


def _release_deferred(lot: dict, take: Decimal) -> Decimal:
    """Saca del lote la parte del diferido que corresponde a ``take`` acciones.

    El diferido (pérdida bloqueada por la regla de los dos meses) viaja con
    las acciones del lote y sale a prorrata cuando se venden. Se lleva en dos
    importes que se consumen en la misma proporción:

    - ``deferred``: en la divisa del valor. Es el que entra en el coste de la
      venta (y de ahí en euros al cambio de ESA venta, criterio DGT). Se
      devuelve para sumarlo al coste nativo.
    - ``deferred_base``: la misma pérdida en euros al cambio de la venta que
      la originó (``_defer_base``). No entra en el coste de la venta; queda en
      los lotes restantes para ``sale_simulation``. None = desconocido y sigue
      desconocido.

    Debe llamarse ANTES de restar ``take`` de ``lot["qty"]``.
    """
    qty = lot["qty"]
    if qty <= 0:
        return Decimal("0")
    if lot["deferred_base"] is not None and lot["deferred_base"] > 0:
        lot["deferred_base"] -= lot["deferred_base"] * take / qty
    released = Decimal("0")
    if lot["deferred"] > 0:
        released = lot["deferred"] * take / qty
        lot["deferred"] -= released
    return released


def is_cash_action(action: str | None) -> bool:
    """True si la accion es un movimiento de caja (no buy/sell)."""
    return (action or "").lower() in CASH_LEDGER_ACTIONS


def cash_amount(transaction) -> Decimal:
    """Importe de un movimiento de caja, con la convencion unica del ledger.

    El importe vive en ``price``; ``quantity`` es 0 o 1 y NO multiplica. Se
    comparan con ``is not None`` y no por verdad: un dividendo de ``0,00``
    es un dividendo de cero, no un dividendo de ``quantity``. Si ``price``
    viniera a None (fila historica corrupta) se cae a ``quantity`` antes que
    declarar un 0 inventado.

    Helper COMPARTIDO con ``portfolio_intelligence_service`` (``_xirr`` y la
    atribucion de dividendos) para que el informe fiscal y la atribucion no
    puedan discrepar sobre el mismo movimiento de caja.
    """
    price = getattr(transaction, "price", None)
    if price is not None:
        return Decimal(str(price))
    quantity = getattr(transaction, "quantity", None)
    return Decimal(str(quantity)) if quantity is not None else Decimal("0")


# Claves que solo escribe el importador Flex de IBKR (``dict(element.attrib)``).
# El CSV canonico (``source: ibkr_csv``) no entra: su signo lo escribe el usuario.
_BROKER_PAYLOAD_KEYS = ("type", "trxID", "transactionID", "accountId")


def is_broker_signed_cash_row(transaction) -> bool:
    """True si la fila viene de IBKR, que firma la caja desde la cuenta.

    IBKR publica la retencion como importe NEGATIVO y su reversion como
    POSITIVO; la entrada manual guarda la retencion en positivo.
    """
    payload = getattr(transaction, "raw_payload", None) or {}
    if not isinstance(payload, dict):
        return False
    return any(key in payload for key in _BROKER_PAYLOAD_KEYS)


def withholding_cost(transaction) -> Decimal:
    """Retencion soportada por la fila, con signo: >0 retenido, <0 devuelto.

    Filas de IBKR: coste = -importe, asi una reversion (+15) resta en vez de
    sumar otra retencion. Resto (entrada manual, historico sin origen): el
    valor absoluto, como hasta ahora.

    Helper COMPARTIDO con ``portfolio_intelligence_service._xirr``.
    """
    amount = cash_amount(transaction)
    if is_broker_signed_cash_row(transaction):
        return -amount
    return abs(amount)


def cash_quantity_is_canonical(transaction) -> bool:
    """False si la fila de caja rompe la convencion (quantity fuera de {0, 1}).

    Una fila asi es ambigua: 25 unidades a 0,25 (importe 6,25) o un dividendo
    de 25 mal escrito. Se acepta el importe de ``price`` pero la fila se
    marca para revision en vez de declararse en silencio.
    """
    quantity = getattr(transaction, "quantity", None)
    return quantity is None or Decimal(str(quantity)) in CASH_UNIT_QUANTITIES


def _money(value: Decimal | None) -> float | None:
    if value is None:
        return None
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _new_cash_bucket(ticker: str, transaction) -> dict:
    return {
        "ticker": ticker,
        "currency": transaction.currency,
        "dividends_native": Decimal("0"),
        "dividends_base": Decimal("0"),
        "withholding_native": Decimal("0"),
        "withholding_base": Decimal("0"),
        "missing_fx": False,
        "ambiguous_cash": False,
        "unattributed": False,
        "payments": [],
        "special_payments": [],
    }


def _unattributed_label(transaction) -> str:
    """A stable, visible label for cash whose company could not be resolved.

    The symbol is recovered from the raw Flex payload when present so the
    reviewer can see WHICH issuer is unattributed instead of a single opaque
    "unattributed" bucket.
    """
    payload = transaction.raw_payload or {}
    for key, value in payload.items():
        if str(key).lower() in {"symbol", "underlyingsymbol"} and value:
            return f"UNATTRIBUTED:{str(value).strip().upper()}"
    return f"UNATTRIBUTED:{transaction.currency or '???'}:{transaction.action or '?'}"


def _raw_action_label(transaction) -> str:
    """Tipo ORIGINAL del bróker para el detector de pagos especiales.

    IBKR guarda el ``type`` del CashTransaction ("Dividends", "Payment In
    Lieu Of Dividends", "Withholding Tax"...) en ``Transaction.raw_payload``;
    la acción normalizada colapsa variantes a "dividend" y haría invisible un
    payment in lieu o un return of capital. Fail-closed: el tipo original
    manda cuando existe; si no hay payload, se usa la acción normalizada.
    """
    payload = transaction.raw_payload or {}
    if isinstance(payload, dict):
        original = payload.get("type") or payload.get("transactionType")
        if original:
            return str(original)
    return transaction.action


def backward_repurchase_quantity(prior_buys, prior_sells, lots, sale_date, quantity):
    """AEAT backward window, including the single initial purchase exception."""
    window_start = sale_date - WASH_SALE_WINDOW
    buys = [(day, qty) for day, qty in prior_buys if window_start <= day <= sale_date]
    holdings_before = max(
        sum((qty for day, qty in prior_buys if day < window_start), Decimal("0"))
        - sum((qty for day, qty in prior_sells if day < window_start), Decimal("0")),
        Decimal("0"),
    )
    if len(buys) == 1 and holdings_before <= 0:
        return Decimal("0")
    eligible = sum((min(lot["qty"], lot["capacity"]) for lot in lots
                    if window_start <= lot["date"] <= sale_date), Decimal("0"))
    return min(quantity, eligible, sum((qty for _, qty in buys), Decimal("0")))


ZERO_COST_REVIEW_LABEL = "Coste 0 (regalo / spin-off): revisar"


def is_zero_cost_buy(transaction) -> bool:
    """Compra con cantidad positiva a precio 0 (regalo, spin-off, liberadas)."""
    return (
        (transaction.action or "").lower() in BUY_ACTIONS
        and transaction.quantity is not None
        and transaction.quantity > 0
        and transaction.price is not None
        and transaction.price == 0
    )


def zero_cost_buys_for_review(events_by_ticker, start, end) -> list[dict]:
    """Compras a coste 0 relevantes para el ejercicio, para revisión manual.

    Relevantes: las del propio ejercicio y las anteriores de tickers con
    ventas en el ejercicio (su lote a coste 0 puede estar en esas ventas).
    No altera el FIFO ni ningún importe: solo las lista con su etiqueta.
    """
    rows: list[dict] = []
    for ticker, events in events_by_ticker.items():
        sold_in_year = any(
            (t.action or "").lower() in SELL_ACTIONS and start <= t.trade_date <= end
            for t in events
        )
        for transaction in events:
            if not is_zero_cost_buy(transaction) or transaction.trade_date > end:
                continue
            if transaction.trade_date >= start or sold_in_year:
                rows.append(
                    {
                        "ticker": ticker,
                        "date": transaction.trade_date.isoformat(),
                        "quantity": float(transaction.quantity),
                        "label": ZERO_COST_REVIEW_LABEL,
                    }
                )
    return sorted(rows, key=lambda r: (r["date"], r["ticker"]))


def replay_tax_fifo(events, resolve_rate, start, end):
    """Pure annual FIFO/recompra replay, also used by read-only sale estimates.

    Returns remaining lots (including deferred bases) and sales for the window.
    Does not write transactions or tax snapshots.
    """
    lots: deque[dict] = deque()
    open_loss_sales: list[dict] = []
    year_sales: list[dict] = []
    # Chronological buy/sell history for this ticker, used ONLY for
    # the Manual AEAT 2025 backward proportionality
    # (min(remanente, comprado previo) + single-purchase exception).
    prior_buys: list[tuple] = []  # (trade_date, quantity)
    prior_sells: list[tuple] = []  # (trade_date, quantity)
    for transaction in events:
        action = (transaction.action or "").lower()
        if action in BUY_ACTIONS:
            if transaction.quantity is None or transaction.quantity <= 0:
                # Ingesta: lotes de compra sin cantidad positiva se
                # rechazan (nunca entran a la base de coste).
                continue
            acquisition_cost = transaction.quantity * transaction.price + transaction.fees
            unit_native = (
                acquisition_cost / transaction.quantity
                if transaction.quantity
                else Decimal("0")
            )
            # IRPF: el valor de adquisición se convierte a divisa base
            # al tipo de la FECHA DE COMPRA (no al de la venta). Sin
            # tipo real el coste en base queda desconocido (None).
            buy_rate = resolve_rate(transaction.currency, transaction.trade_date)
            lot = {
                "qty": transaction.quantity,
                "unit": unit_native,
                "unit_base": unit_native * buy_rate if buy_rate is not None else None,
                "deferred": Decimal("0"),
                # Sin tipo de cambio de compra el coste en base es
                # desconocido: el diferido en base tambien (None, ver
                # _defer_base), nunca un 0 con pinta de dato conocido.
                "deferred_base": Decimal("0") if buy_rate is not None else None,
                "capacity": transaction.quantity,
                "date": transaction.trade_date,
                "currency": transaction.currency or TAX_CURRENCY,
            }
            # Forward window: this buy can repurchase earlier loss sales.
            still_open: list[dict] = []
            for sale in open_loss_sales:
                if transaction.trade_date > sale["date"] + WASH_SALE_WINDOW:
                    continue  # forward window closed
                if sale["qty_unblocked"] > 0 and lot["capacity"] > 0:
                    take = min(lot["capacity"], sale["qty_unblocked"])
                    lot["deferred"] += take * sale["loss_per_share"]
                    _defer_base(lot, take, sale)
                    lot["capacity"] -= take
                    sale["blocked_qty"] += take
                    sale["qty_unblocked"] -= take
                still_open.append(sale)
            open_loss_sales = still_open
            lots.append(lot)
            prior_buys.append((transaction.trade_date, transaction.quantity))
            continue
        if action not in SELL_ACTIONS:
            continue

        if transaction.quantity is None or transaction.quantity <= 0:
            # Ingesta: ventas sin cantidad positiva se rechazan.
            continue
        remaining = transaction.quantity
        proceeds_native = transaction.quantity * transaction.price - transaction.fees
        # Coste en la divisa del valor (incluye el diferido nativo de los
        # lotes consumidos). El coste en euros sale de aquí, al cambio de la
        # venta (criterio DGT, más abajo): NO se suma lote a lote al cambio de
        # cada compra.
        cost_native = Decimal("0")
        # Coste desconocido aunque la venta esté cubierta: algún lote consumido
        # arrastra una pérdida diferida de una venta descubierta.
        cost_unknown = False
        while remaining > Decimal("0") and lots:
            lot = lots[0]
            take = min(lot["qty"], remaining)
            if lot.get("deferred_unknown"):
                cost_unknown = True
            cost_native += take * lot["unit"]
            released = _release_deferred(lot, take)
            if released:
                cost_native += released
            lot["qty"] -= take
            if lot["qty"] == 0:
                lots.popleft()
            remaining -= take
        # Over-sell: se vendió más de lo comprado. El remanente se
        # valora a coste cero pero se MARCA con warning explícito en
        # vez de registrar una ganancia silenciosa.
        over_sell_quantity = remaining if remaining > Decimal("0") else Decimal("0")
        over_sell = over_sell_quantity > 0

        gain_native = proceeds_native - cost_native
        # Criterio DGT elegido: ganancia en moneda del valor, convertida una
        # sola vez al cambio de la venta. La posterior transmisión de divisa
        # es un hecho fiscal separado, no se mezcla con esta venta de acciones.
        sell_rate = resolve_rate(transaction.currency, transaction.trade_date)
        proceeds_base = proceeds_native * sell_rate if sell_rate is not None else None
        cost_base = cost_native * sell_rate if sell_rate is not None else None
        gain_base_raw = gain_native * sell_rate if sell_rate is not None else None
        if cost_unknown:
            # El coste nativo arrastra la pérdida diferida (inventada) de una
            # venta descubierta: convertirlo al cambio de la venta no lo hace
            # conocido. Coste y resultado en euros, N/D (#2590).
            cost_base = None
            gain_base_raw = None
        # TODA venta válida entra en el historial, con ganancia o con
        # pérdida: holdings_before_window alimenta la excepción de
        # compra única del Manual, y omitir las ventas rentables lo
        # infla (bloquearía pérdidas que AEAT permite computar).
        prior_sells.append((transaction.trade_date, transaction.quantity))
        # La pérdida del valor se calcula primero en su moneda y se convierte
        # al cambio de la venta, sin mezclar el resultado separado de divisa.
        is_loss = (
            gain_base_raw < 0 if gain_base_raw is not None else gain_native < 0
        )
        if is_loss:
            sale = {
                "date": transaction.trade_date,
                "qty_unblocked": transaction.quantity,
                # Pérdida por acción en divisa; 0 si en divisa hubo
                # ganancia (la pérdida existe solo en euros).
                "loss_per_share": max(-gain_native, Decimal("0")) / transaction.quantity,
                # Pérdida por acción en base (al cambio de esta venta,
                # criterio DGT); 0 si en base no hay pérdida que diferir.
                "loss_per_share_base": (
                    max(-gain_base_raw, Decimal("0")) / transaction.quantity
                    if gain_base_raw is not None
                    else None
                ),
                "blocked_qty": Decimal("0"),
                # Con exceso a coste cero la pérdida no es una cifra; si
                # además arrastra un diferido desconocido, tampoco. Lo que
                # se difiera de ella deja el lote con base desconocida.
                "loss_unknown": over_sell or cost_unknown,
            }
            # Backward window (Manual Renta 2025, apdo. E.1): prior-window
            # buys block only for the shares still held, proportionally:
            #   recompra = min(remanente tras la venta,
            #                  comprado en los 2 meses previos),
            # absorbed FIFO onto the oldest surviving in-window lots.
            # Exception: a single buy op in the prior window with zero
            # holdings at its start is the initial purchase itself,
            # not a repurchase → no limitation.
            window_start = transaction.trade_date - WASH_SALE_WINDOW
            recompra_prev_qty = backward_repurchase_quantity(
                prior_buys, prior_sells, lots, transaction.trade_date, sale["qty_unblocked"]
            )
            to_block = recompra_prev_qty
            for lot in lots:
                if to_block <= 0 or sale["qty_unblocked"] <= 0:
                    break
                if lot["date"] < window_start or lot["capacity"] <= 0 or lot["qty"] <= 0:
                    continue
                take = min(lot["capacity"], lot["qty"], to_block, sale["qty_unblocked"])
                lot["deferred"] += take * sale["loss_per_share"]
                _defer_base(lot, take, sale)
                lot["capacity"] -= take
                sale["blocked_qty"] += take
                sale["qty_unblocked"] -= take
                to_block -= take
            open_loss_sales.append(sale)
        else:
            sale = None

        if start <= transaction.trade_date <= end:
            year_sales.append(
                {
                    "transaction": transaction,
                    "proceeds_native": proceeds_native,
                    "cost_native": cost_native,
                    "gain_native": gain_native,
                    "proceeds_base": proceeds_base,
                    "cost_base": cost_base,
                    "gain_base_raw": gain_base_raw,
                    "sale": sale,
                    "over_sell": over_sell,
                    "over_sell_quantity": over_sell_quantity,
                    "cost_unknown": cost_unknown,
                }
            )
    return lots, year_sales


def cancelled_buy_dates(events) -> list[date]:
    """Fechas de compras anuladas por el broker (accion ``cancelled``) de un valor.

    La original anulada ya no entra en el FIFO. Si solo se conoce el sentido por
    ``raw_payload.buySell`` y no es una venta, se trata como compra. No se
    adivina el caso dudoso: sentido desconocido cuenta como compra anulada.
    """
    dates: list[date] = []
    for transaction in events:
        if (transaction.action or "").lower() != "cancelled":
            continue
        payload = transaction.raw_payload if isinstance(transaction.raw_payload, dict) else {}
        side = str(payload.get("buySell") or "").split("(", 1)[0].strip().lower()
        if side in {"sell", "sold", "s"}:
            continue
        dates.append(transaction.trade_date)
    return dates


def flag_cancelled_lot_sales(events, year_sales: list[dict]) -> None:
    """Marca ``cancelled_lot`` en las ventas del ejercicio que no se pueden fiar."""
    cancelled_dates = cancelled_buy_dates(events)
    for entry in year_sales:
        entry["cancelled_lot"] = any(
            day <= entry["transaction"].trade_date for day in cancelled_dates
        )


def sanitize_realized_over_sells(realized: list[dict]) -> list[dict]:
    """Read-time copy for legacy reports, never rewrite persisted JSON."""
    from copy import deepcopy

    result = deepcopy(realized)
    for bucket in result:
        affected = bool(bucket.get("over_sell"))
        for sale in bucket.get("sales", []):
            if sale.get("over_sell"):
                affected = True
                for key in ("cost_native", "cost_base", "gain_native", "gain_base", "raw_gain_native"):
                    sale[key] = None
        if affected:
            bucket["cost_native"] = None
            bucket["gain_native"] = None
            bucket["gain_base"] = None
    return result


def sanitize_summary_over_sells(summary: dict | None, realized: list[dict]) -> dict:
    """Copia de lectura del resumen de un informe persistido antiguo.

    Un informe guardado antes de anular las ventas descubiertas puede llevar
    la plusvalia total y la base imponible con el coste inventado (cero).
    Si algun bloque tiene over_sell, ambos totales salen None al leer (misma
    regla que ``compute_report``); el JSON persistido no se reescribe.
    """
    result = dict(summary or {})
    if any(
        bucket.get("over_sell")
        or any(sale.get("over_sell") for sale in bucket.get("sales", []))
        for bucket in realized or []
    ):
        result["total_realized_gain_base"] = None
        result["net_taxable_base"] = None
        flagged = set(result.get("over_sell") or [])
        flagged.update(
            bucket["ticker"]
            for bucket in realized
            if bucket.get("ticker")
            and (
                bucket.get("over_sell")
                or any(sale.get("over_sell") for sale in bucket.get("sales", []))
            )
        )
        result["over_sell"] = sorted(flagged)
    return result


class TaxReportService:
    """Compute and persist per-fiscal-year tax snapshots."""

    def __init__(self) -> None:
        self.fx = PortfolioFXService()
        self.settings = get_settings()

    def compute_report(self, db: Session, fiscal_year: int, include_filing: bool = True, tme: Decimal | None = None, fx_conversions=None, fx_opening_complete: bool = False,
        fx_income_by_analogy: bool = False) -> dict:
        # IRPF y Modelo 720 se declaran SIEMPRE en euros al tipo del BCE de la
        # fecha de cada operacion, sea cual sea la divisa base de la cartera
        # (EUR, USD...). La divisa base es una preferencia de visualizacion;
        # la fiscal la fija la AEAT.
        base_currency = TAX_CURRENCY

        start = date(fiscal_year, 1, 1)
        end = date(fiscal_year, 12, 31)

        # outerjoin, not join: a cash row with company_id NULL (an IBKR
        # dividend or retention whose symbol could not be resolved) is real
        # taxable income. The INNER JOIN dropped it silently, so the report
        # declared zero dividends with no flag anywhere.
        rows = db.execute(
            select(Transaction, Company)
            .outerjoin(Company, Transaction.company_id == Company.id)
            .where(Transaction.trade_date >= start, Transaction.trade_date <= end)
            .order_by(Transaction.trade_date, Transaction.id)
        ).all()

        # Lote FX: UNA tabla por informe (anti N+1). Antes `self.fx.rate(...)`
        # se llamaba una vez por cada fila de dividendo/retencion/otros y otra
        # por cada venta, con 1-2 SELECT cada vez; y como `_build_filing`
        # recalcula los cuatro ejercicios anteriores, un solo GET recorria el
        # libro entero unas 5 veces. `rate_from_table` replica `rate` en
        # memoria (mismo par, misma fecha maxima, mismo inverso).
        fx_table = self.fx.fx_table(
            db,
            currencies={transaction.currency for transaction, _ in rows if transaction.currency},
            base_currency=base_currency,
            as_of_max=max(
                (transaction.trade_date for transaction, _ in rows), default=end
            ),
        )

        def resolve_rate(currency: str | None, as_of: date) -> Decimal | None:
            # IRPF: tipo de la FECHA de cada operación. Se acepta el último
            # publicado hasta MAX_FX_AGE_DAYS antes (fines de semana y
            # festivos TARGET); uno más viejo NO es el tipo de esa fecha y
            # deja el importe en base desconocido (None, missing_fx) en vez
            # de convertir en silencio con un tipo de semanas o meses atrás.
            return _rate_not_older_than(
                fx_table,
                quote_currency=currency or "",
                base_currency=base_currency,
                as_of=as_of,
                max_age_days=MAX_FX_AGE_DAYS,
            )

        inconsistent_cash: list[dict] = []

        dividends_by_company: dict[str, dict] = {}
        realized_by_company: dict[str, dict] = {}
        misc_rows: list[dict] = []

        # First pass: dividends, withholding and misc cash movements.
        for transaction, company in rows:
            action = (transaction.action or "").lower()
            if company is None:
                # Taxable cash with no resolvable company (an IBKR dividend or
                # retention whose symbol is not in the workspace). It must not
                # disappear: it is income, and hiding it produces a filing that
                # understates the taxable base with no flag.
                if not (
                    action in DIVIDEND_ACTIONS
                    or "dividend" in action
                    or "withholding" in action
                    or "interest" in action
                    or "fee" in action
                    or action == "cash_misc"
                ):
                    continue
                ticker = _unattributed_label(transaction)
                if ticker not in dividends_by_company:
                    dividends_by_company[ticker] = _new_cash_bucket(ticker, transaction)
                dividends_by_company[ticker]["unattributed"] = True
            else:
                ticker = company.ticker
            if action in DIVIDEND_ACTIONS or "dividend" in action or "withholding" in action:
                rate = resolve_rate(transaction.currency, transaction.trade_date)
                amount_native = cash_amount(transaction)
                ambiguous_cash_row = is_cash_action(action) and not cash_quantity_is_canonical(transaction)
                if ambiguous_cash_row:
                    inconsistent_cash.append(
                        {
                            "ticker": ticker,
                            "date": transaction.trade_date.isoformat(),
                            "action": action,
                            # nosemgrep: gerarai-money-none-to-zero -- columna NOT NULL (default 0): el `or 0` no convierte ningun None real
                            "quantity": float(transaction.quantity or 0),
                            # Valor crudo (price x quantity no canonica): es
                            # un CANDIDATO a revisar, nunca un pago medido.
                            "amount": _money(amount_native),
                            "candidate": True,
                            "currency": transaction.currency,
                        }
                    )
                # Never convert at par: without a real FX rate the base
                # amount is unknown and must stay None.
                amount_base = amount_native * rate if rate is not None else None
                bucket = dividends_by_company.setdefault(
                    ticker, _new_cash_bucket(ticker, transaction)
                )
                if company is None:
                    bucket["unattributed"] = True
                if "withholding" in action or "tax" in action:
                    withheld = withholding_cost(transaction)
                    withheld_base = withheld * rate if rate is not None else None
                    if ambiguous_cash_row:
                        # Fila ambigua: NO entra en los agregados ni en las
                        # casillas derivadas hasta resolverla (None +
                        # manual_review, nunca un total con pinta de exacto).
                        bucket["ambiguous_cash"] = True
                    else:
                        bucket["withholding_native"] += withheld
                        if withheld_base is not None:
                            bucket["withholding_base"] += withheld_base
                        else:
                            bucket["missing_fx"] = True
                    withholding_row = {
                        "date": transaction.trade_date.isoformat(),
                        "type": "withholding",
                        "raw_action": _raw_action_label(transaction),
                        "amount_native": _money(withheld),
                        "amount_base": _money(withheld_base) if withheld_base is not None else None,
                    }
                    if ambiguous_cash_row:
                        # Fila ambigua: la cifra derivada de price es un
                        # candidato (lista de revision), no un pago medido.
                        withholding_row["amount_native"] = None
                        withholding_row["amount_base"] = None
                        withholding_row["ambiguous"] = True
                        withholding_row["manual_review"] = True
                    bucket["payments"].append(withholding_row)
                else:
                    raw_label = _raw_action_label(transaction)
                    special = any(
                        token in raw_label.lower()
                        for token in SPECIAL_PAYMENT_TOKENS
                    )
                    payment_row = {
                        "date": transaction.trade_date.isoformat(),
                        "type": "special" if special else "dividend",
                        "raw_action": raw_label,
                        "amount_native": _money(amount_native),
                        "amount_base": _money(amount_base),
                    }
                    if ambiguous_cash_row:
                        # La cifra cruda vive solo en inconsistent_cash como
                        # candidato etiquetado; aqui seria una invencion
                        # visible para cualquier consumidor/exportacion.
                        payment_row["amount_native"] = None
                        payment_row["amount_base"] = None
                        payment_row["ambiguous"] = True
                        payment_row["manual_review"] = True
                    bucket["payments"].append(payment_row)
                    if special:
                        # Payment in lieu / return of capital / stock lending:
                        # NO es dividendo ordinario. Queda fuera de las sumas
                        # (casilla 0029 y deducción 0588) y se lista para
                        # revisión manual: clasificarlo como ordinario sería
                        # inventar un tratamiento fiscal.
                        bucket["special_payments"].append(payment_row)
                        if amount_base is None:
                            bucket["missing_fx"] = True
                    else:
                        if ambiguous_cash_row:
                            bucket["ambiguous_cash"] = True
                        else:
                            bucket["dividends_native"] += amount_native
                            if amount_base is not None:
                                bucket["dividends_base"] += amount_base
                            else:
                                bucket["missing_fx"] = True
                continue

            if action in {"interest", "fee", "cash_misc"}:
                rate = resolve_rate(transaction.currency, transaction.trade_date)
                amount = cash_amount(transaction)
                ambiguous_cash_row = not cash_quantity_is_canonical(transaction)
                if ambiguous_cash_row:
                    inconsistent_cash.append(
                        {
                            "ticker": ticker,
                            "date": transaction.trade_date.isoformat(),
                            "action": action,
                            # nosemgrep: gerarai-money-none-to-zero -- columna NOT NULL (default 0): el `or 0` no convierte ningun None real
                            "quantity": float(transaction.quantity or 0),
                            "amount": _money(amount),
                            "currency": transaction.currency,
                        }
                    )
                # Fila ambigua: importes None + revision manual; nunca un
                # importe aceptado en silencio.
                misc_rows.append(
                    {
                        "date": transaction.trade_date.isoformat(),
                        "ticker": ticker,
                        "type": action,
                        "amount_native": None if ambiguous_cash_row else _money(amount),
                        "amount_base": None if (ambiguous_cash_row or rate is None) else _money(amount * rate),
                        "currency": transaction.currency,
                        "ambiguous": ambiguous_cash_row,
                        "manual_review": ambiguous_cash_row,
                    }
                )
                continue

            if action in SELL_ACTIONS or action in BUY_ACTIONS:
                # Accumulate for FIFO pass; done below in chronological order.
                continue

        # Second pass: FIFO realized gains/losses per company, with the
        # two-month wash-sale rule. Lots are rebuilt from the FULL
        # transaction history so cost basis and deferred losses stay correct
        # across fiscal years; only sales inside [start, end] enter the
        # report (a prior-year sale must never leak into this year's totals).
        #
        # Documented procedure (Manual Renta 2025, cap. 11, apdo. E):
        # - Backward: prior-window buys block only for the shares still held
        #   at sale time, proportionally as min(remanente, comprado previo),
        #   absorbed FIFO onto the oldest surviving in-window lots. Single
        #   prior buy op with zero holdings at the window start is the initial
        #   purchase, not a repurchase → no limitation.
        # - Forward: posterior-window buys are also taken into account and
        #   block proportionally up to the posterior buy quantity (the Manual
        #   gives no explicit posterior prorrata: documented interpretation).
        # - A partial repurchase blocks the loss proportionally.
        # - When a sale's forward window extends beyond the latest available
        #   transaction, the unblocked remainder is reported as provisionally
        #   computable and flagged (wash_sale_window_open).
        # The FIFO pass only needs buy/sell legs, which always carry a company;
        # an INNER JOIN here is correct and keeps unattributed cash out of the
        # lot rebuild (it is handled and reported in the first pass).
        tx_rows = db.execute(
            select(Transaction, Company)
            .join(Company, Transaction.company_id == Company.id)
            .order_by(Transaction.trade_date, Transaction.id)
        ).all()
        # Orden FIFO dentro del mismo día: hora de ejecución si el ledger la
        # trae (raw_payload.dateTime); sin hora, las compras van antes que las
        # ventas. El id solo refleja el orden de importación: ordenar por él
        # casaba ventas contra lotes aún vacíos (coste 0, ganancia inventada).
        tx_rows = sorted(tx_rows, key=lambda row: _fifo_sort_key(row[0]))

        last_data_date = tx_rows[-1][0].trade_date if tx_rows else end

        events_by_ticker: dict[str, list] = {}
        for transaction, company in tx_rows:
            events_by_ticker.setdefault(company.ticker, []).append(transaction)

        zero_cost_buys = zero_cost_buys_for_review(events_by_ticker, start, end)

        realized_by_company = {}
        for ticker, events in events_by_ticker.items():
            lots, year_sales = replay_tax_fifo(events, resolve_rate, start, end)
            # Venta posterior (o del mismo dia) a una compra anulada: el lote que
            # la cubria pudo ser el anulado, asi que el coste no es fiable. No se
            # recalcula: se marca para revision manual.
            flag_cancelled_lot_sales(events, year_sales)

            # Aggregate the bucket only after the full event loop so that
            # forward-window repurchases (which can postdate the sale) are
            # reflected in the blocked amounts.
            if not year_sales:
                continue
            bucket = realized_by_company.setdefault(
                ticker,
                {
                    "ticker": ticker,
                    "currency": year_sales[0]["transaction"].currency,
                    "proceeds_native": Decimal("0"),
                    "cost_native": Decimal("0"),
                    "gain_native": Decimal("0"),
                    "gain_base": Decimal("0"),
                    "blocked_loss_native": Decimal("0"),
                    "blocked_loss_base": Decimal("0"),
                    "missing_fx": False,
                    "wash_sale_window_open": False,
                    "sale_count": 0,
                    "over_sell_count": 0,
                    "over_sell": False,
                    "cost_unknown": False,
                    "cancelled_lot": False,
                    "sales": [],
                },
            )
            for entry in year_sales:
                transaction = entry["transaction"]
                sale = entry["sale"]
                blocked_native = (
                    sale["blocked_qty"] * sale["loss_per_share"]
                    if sale is not None
                    else Decimal("0")
                )
                computable_native = entry["gain_native"] + blocked_native
                window_open = bool(
                    sale is not None
                    and sale["qty_unblocked"] > 0
                    and sale["date"] + WASH_SALE_WINDOW > last_data_date
                )
                gain_base_raw = entry["gain_base_raw"]
                if gain_base_raw is not None and (
                    sale is None or sale["loss_per_share_base"] is not None
                ):
                    blocked_base = (
                        sale["blocked_qty"] * sale["loss_per_share_base"]
                        if sale is not None
                        else Decimal("0")
                    )
                    computable_base = gain_base_raw + blocked_base
                else:
                    computable_base = None
                    blocked_base = None
                bucket["proceeds_native"] += entry["proceeds_native"]
                bucket["cost_native"] += entry["cost_native"]
                bucket["gain_native"] += computable_native
                bucket["blocked_loss_native"] += blocked_native
                sale_cost_unknown = bool(entry.get("cost_unknown"))
                if computable_base is not None:
                    bucket["gain_base"] += computable_base
                    bucket["blocked_loss_base"] += blocked_base
                elif not sale_cost_unknown or entry["proceeds_base"] is None:
                    # Sin base por falta de tipo de cambio. Un coste
                    # desconocido por un diferido de venta descubierta no es
                    # un problema de FX y lleva su propia marca.
                    bucket["missing_fx"] = True
                if sale_cost_unknown:
                    bucket["cost_unknown"] = True
                if entry.get("cancelled_lot"):
                    bucket["cancelled_lot"] = True
                bucket["wash_sale_window_open"] = bucket["wash_sale_window_open"] or window_open
                bucket["sale_count"] += 1
                if entry["over_sell"]:
                    bucket["over_sell"] = True
                    bucket["over_sell_count"] += 1
                # Venta sin compras que la cubran: el exceso se valoro a
                # coste cero, asi que la base de adquisicion de la venta (y
                # por tanto su resultado) NO se conoce. N/D en coste y
                # ganancia; la transmision si es un dato observado y se
                # conserva (misma regla que los totales: nunca una cifra
                # parcial con pinta de exacta).
                sale_over_sell = bool(entry["over_sell"])
                # Mismo N/D si el lote vendido arrastra la pérdida diferida
                # de una venta descubierta (coste inventado heredado).
                sale_cancelled_lot = bool(entry.get("cancelled_lot"))
                nd = sale_over_sell or sale_cost_unknown or sale_cancelled_lot
                bucket["sales"].append(
                    {
                        "date": transaction.trade_date.isoformat(),
                        "quantity": float(transaction.quantity),
                        "proceeds_native": _money(entry["proceeds_native"]),
                        "cost_native": None if nd else _money(entry["cost_native"]),
                        "proceeds_base": _money(entry["proceeds_base"]),
                        "cost_base": None if nd else _money(entry["cost_base"]),
                        "gain_native": None if nd else _money(computable_native),
                        "gain_base": (
                            None
                            if nd or computable_base is None
                            else _money(computable_base)
                        ),
                        "raw_gain_native": None if nd else _money(entry["gain_native"]),
                        "blocked_loss_native": _money(blocked_native),
                        "blocked_loss_base": _money(blocked_base) if blocked_base is not None else None,
                        "wash_sale_blocked": blocked_native > 0 or (blocked_base is not None and blocked_base > 0),
                        "wash_sale_window_open": window_open,
                        "over_sell": sale_over_sell,
                        "over_sell_quantity": float(entry["over_sell_quantity"]),
                        "cost_unknown": sale_cost_unknown,
                        "cancelled_lot": sale_cancelled_lot,
                        "manual_review": sale_cancelled_lot,
                        "warning": (
                            "over_sell: sold more shares than the recorded lots; "
                            "excess valued at zero cost, verify the ledger"
                            if sale_over_sell
                            else (
                                "cancelled_lot: the broker cancelled a purchase dated on or "
                                "before this sale, so the lot it consumed may be void; "
                                "cost not recomputed, review manually"
                                if sale_cancelled_lot
                                else (
                                    "cost_unknown: the lot sold carries a loss deferred "
                                    "from an over_sell sale; acquisition cost unknown"
                                    if sale_cost_unknown
                                    else None
                                )
                            )
                        ),
                    }
                )

        dividends = []
        for bucket in dividends_by_company.values():
            dividends.append(
                {
                    "ticker": bucket["ticker"],
                    "currency": bucket["currency"],
                    "dividends_native": _money(bucket["dividends_native"]),
                    "dividends_base": None if (bucket["missing_fx"] or bucket["ambiguous_cash"]) else _money(bucket["dividends_base"]),
                    "withholding_native": _money(bucket["withholding_native"]),
                    "withholding_base": None if (bucket["missing_fx"] or bucket["ambiguous_cash"]) else _money(bucket["withholding_base"]),
                    "missing_fx": bucket["missing_fx"],
                    "ambiguous_cash": bucket["ambiguous_cash"],
                    "unattributed": bucket.get("unattributed", False),
                    "payments": bucket["payments"],
                    "special_payments": bucket["special_payments"],
                }
            )

        realized = []
        for bucket in realized_by_company.values():
            realized.append(
                {
                    "ticker": bucket["ticker"],
                    "currency": bucket["currency"],
                    "proceeds_native": _money(bucket["proceeds_native"]),
                    # Con alguna venta descubierta, el coste y el resultado
                    # del ticker mezclan una base desconocida (el exceso se
                    # valoro a coste cero): N/D, nunca la suma parcial. La
                    # transmision si es un dato observado y se conserva.
                    "cost_native": None if bucket["over_sell"] or bucket["cost_unknown"] else _money(bucket["cost_native"]),
                    "gain_native": None if bucket["over_sell"] or bucket["cost_unknown"] else _money(bucket["gain_native"]),
                    "gain_base": (
                        None
                        if bucket["missing_fx"] or bucket["over_sell"] or bucket["cost_unknown"]
                        else _money(bucket["gain_base"])
                    ),
                    "blocked_loss_native": _money(bucket["blocked_loss_native"]),
                    "blocked_loss_base": None if bucket["missing_fx"] else _money(bucket["blocked_loss_base"]),
                    "wash_sale_window_open": bucket["wash_sale_window_open"],
                    "missing_fx": bucket["missing_fx"],
                    "sale_count": bucket["sale_count"],
                    "over_sell": bucket["over_sell"],
                    "over_sell_count": bucket["over_sell_count"],
                    "cost_unknown": bucket["cost_unknown"],
                    "cancelled_lot": bucket["cancelled_lot"],
                    "sales": bucket["sales"],
                }
            )

        # Intereses cobrados (casilla 0027): rendimiento del capital mobiliario
        # del ahorro. None si alguno no tiene importe en EUR.
        interest_block = build_interest(misc_rows, fiscal_year)
        interest_received: Decimal | None = (
            None if interest_block["incomplete"]
            # nosemgrep: gerarai-money-none-to-zero -- con incomplete False el importe siempre está calculado
            else Decimal(str(interest_block["received"]["amount_base"] or 0))
        )
        dividend_ambiguous = any(b["ambiguous_cash"] for b in dividends)
        dividend_incomplete = any(b["missing_fx"] for b in dividends) or dividend_ambiguous
        realized_incomplete = any(b["missing_fx"] for b in realized)
        incomplete_fx = dividend_incomplete or realized_incomplete
        # Ventas sin compras que las cubran: el remanente se valora a coste
        # cero, así que la plusvalía total no es fiable. None, nunca una
        # cifra parcial con pinta de exacta (misma regla que los demás totales).
        realized_unreliable = realized_incomplete or any(
            b.get("over_sell") or b.get("cost_unknown") or b.get("cancelled_lot") for b in realized
        )

        total_dividends = sum(
            # nosemgrep: gerarai-money-none-to-zero -- los totales se publican como None si algun componente es incompleto o hay over_sell (realized_unreliable/dividend_incomplete)
            (Decimal(str(b["dividends_base"] or 0)) for b in dividends), Decimal("0")
        )
        total_withholding = sum(
            # nosemgrep: gerarai-money-none-to-zero -- los totales se publican como None si algun componente es incompleto o hay over_sell (realized_unreliable/dividend_incomplete)
            (Decimal(str(b["withholding_base"] or 0)) for b in dividends), Decimal("0")
        )
        total_gain = sum(
            # nosemgrep: gerarai-money-none-to-zero -- los totales se publican como None si algun componente es incompleto o hay over_sell (realized_unreliable/dividend_incomplete)
            (Decimal(str(b["gain_base"] or 0)) for b in realized), Decimal("0")
        )
        total_blocked = sum(
            # nosemgrep: gerarai-money-none-to-zero -- los totales se publican como None si algun componente es incompleto o hay over_sell (realized_unreliable/dividend_incomplete)
            (Decimal(str(b["blocked_loss_base"] or 0)) for b in realized), Decimal("0")
        )

        currency_ledger = self._currency_ledger(
            db, tx_rows, resolve_rate, base_currency, start, end, fx_conversions, fx_opening_complete,
            income_by_analogy=fx_income_by_analogy,
        )

        summary = {
            "fiscal_year": fiscal_year,
            "base_currency": base_currency,
            # Totals stay None when any component could not be converted:
            # a partial total would look authoritative and be wrong.
            "total_dividends_base": None if dividend_incomplete else _money(total_dividends),
            "total_withholding_base": None if dividend_incomplete else _money(total_withholding),
            "total_realized_gain_base": None if realized_unreliable else _money(total_gain),
            "total_blocked_loss_base": None if realized_incomplete else _money(total_blocked),
            "wash_sale_rule": WASH_SALE_RULE_ID,
            "wash_sale_basis": WASH_SALE_BASIS,
            "fiscal_disclaimer": FISCAL_DISCLAIMER,
            "wash_sale_window_open": sorted(
                b["ticker"] for b in realized if b["wash_sale_window_open"]
            ),
            # Base del ahorro del ejercicio: art. 49.1 LIRPF, la pérdida
            # patrimonial solo compensa dividendos hasta el 25 %. Antes era la
            # suma directa (1.000 de dividendos y -10.000 de pérdidas daban
            # -9.000; la base real es 750 y el resto se arrastra).
            # El saldo de RCM son dividendos MÁS intereses cobrados (art. 25.2
            # y 46.b LIRPF), igual que en la compensación de pérdidas.
            "net_taxable_base": None if (incomplete_fx or dividend_ambiguous or realized_unreliable or interest_received is None) else _money(integrate_savings_base(total_dividends + interest_received, total_gain)),
            "dividend_count": len(dividends),
            "unattributed_tickers": sorted(
                b["ticker"] for b in dividends if b.get("unattributed")
            ),
            # Subtotal diagnóstico: si un bloque no atribuido carece de FX o
            # lleva cash ambiguo sin resolver, la suma quedaria por debajo
            # sin avisar. None, nunca un parcial con pinta de exacto (misma
            # regla que los totales).
            "unattributed_dividends_base": (
                None
                if any(
                    b.get("unattributed") and (b["missing_fx"] or b["ambiguous_cash"])
                    for b in dividends
                )
                else _money(
                    sum(
                        (
                            # nosemgrep: gerarai-money-none-to-zero -- los totales se publican como None si algun componente es incompleto o hay over_sell (realized_unreliable/dividend_incomplete)
                            Decimal(str(b["dividends_base"] or 0))
                            for b in dividends
                            if b.get("unattributed")
                        ),
                        Decimal("0"),
                    )
                )
            ),
            "sell_count": sum(b["sale_count"] for b in realized),
            "over_sell": sorted(
                b["ticker"] for b in realized if b.get("over_sell")
            ),
            "cost_unknown": sorted(
                b["ticker"] for b in realized if b.get("cost_unknown")
            ),
            "cancelled_lot": sorted(
                b["ticker"] for b in realized if b.get("cancelled_lot")
            ),
            "method": FIFO_METHOD,
            "securities_fx_criterion": SECURITIES_FX_CRITERION,
            "currency_ledger_criterion": currency_ledger["criterion"],
            "currency_ledger_status": currency_ledger["status"],
            "currency_ledger_gain_base": currency_ledger["gain_base"],
            "currency_ledger_blocked_loss_base": currency_ledger.get("blocked_loss_base"),
            "currency_ledger_by_currency": currency_ledger.get("by_currency") or {},
            "currency_ledger_note": currency_ledger.get("analogy"),
            "currency_ledger_reason": currency_ledger["reason"],
            "incomplete_fx": incomplete_fx,
            "missing_fx": sorted(
                {b["ticker"] for b in dividends if b["missing_fx"]}
                | {b["ticker"] for b in realized if b["missing_fx"]}
            ),
            # Movimientos de caja con `quantity` fuera de {0, 1}: el importe
            # declarado sale de `price` (la convencion del ledger) pero la fila
            # es ambigua y se lista para revision en vez de declararse en
            # silencio. La creacion por API rechaza estas filas con un 400.
            "inconsistent_cash_rows": inconsistent_cash,
            # Filas de caja ambiguas (quantity fuera de {0,1}): bloquean los
            # agregados y las casillas afectadas hasta resolverse.
            "ambiguous_cash": sorted(
                b["ticker"] for b in dividends if b["ambiguous_cash"]
            ),
            "manual_review": dividend_ambiguous or any(b.get("cancelled_lot") for b in realized),
            # Compras a precio 0 (regalo, spin-off, acciones liberadas...): se
            # aceptan y entran al FIFO con coste 0 como siempre, pero se listan
            # para revisión. Solo aviso visible: no cambia ningún cálculo.
            "zero_cost_buys": zero_cost_buys,
        }

        data = {
            "summary": summary,
            "dividends": sorted(dividends, key=lambda d: d["ticker"]),
            "realized": sorted(realized, key=lambda d: d["ticker"]),
            "misc": sorted(misc_rows, key=lambda d: d["date"]),
        }
        if include_filing:
            data["filing"] = self._build_filing(db, fiscal_year, data, tme=tme)
        return data

    def _currency_ledger(
        self, db, tx_rows, resolve_rate, base_currency, start, end, fx_conversions, opening_complete,
        income_by_analogy: bool = False,
    ) -> dict:
        """Libro de divisas por divisa (DGT V2466-08, V0234-07, V0282-22).

        Conversiones: argumento explicito o tabla ``fx_conversions`` (Flex
        Trades CASH). Sin ellas, "no calculado". Flujos de divisa que el libro
        aun no modela (compras de valores, dividendos, intereses y comisiones
        en esa divisa) hacen el resultado ``incomplete``, no un numero.
        """
        if fx_conversions is None:
            stored = db.scalars(
                select(FxConversion)
                .where(FxConversion.trade_date <= end)
                .order_by(FxConversion.trade_date, FxConversion.id)
            ).all()
            raw = [
                (c.trade_date, c.disposed_currency, c.disposed_amount, c.acquired_currency, f"fx#{c.id}", c.acquired_amount, _fx_time(c))
                for c in stored
            ]
        else:
            raw = [(c.converted_on, "USD", c.amount, base_currency, c.ref, None, c.time) for c in fx_conversions]
            explicit_rates = {c.converted_on: c.ecb_rate for c in fx_conversions}
        if not raw:
            return compute_currency_ledger([], [], start, end)
        # Tabla BCE propia: las conversiones pueden ser posteriores a la ultima
        # operacion del ejercicio y la tabla del informe se corta ahi.
        _table = self.fx.fx_table(
            db,
            currencies={(r[1] or "").upper() for r in raw} | {(r[3] or "").upper() for r in raw},
            base_currency=base_currency,
            as_of_max=max(r[0] for r in raw),
        )

        def conv_rate(currency: str, as_of: date):
            return _rate_not_older_than(
                _table, quote_currency=currency, base_currency=base_currency,
                as_of=as_of, max_age_days=MAX_FX_AGE_DAYS,
            )

        by_currency: dict[str, list] = {}
        unsupported: list[str] = []
        bought_with_base: dict[str, list[CurrencyLot]] = {}
        for day, disposed, amount, acquired, ref, acquired_amount, when in raw:
            disposed = (disposed or "").upper()
            if disposed == base_currency:
                # Comprar divisa con EUR: entrada de lote cuyo valor de adquisicion
                # es el EUR pagado (art. 35 LIRPF, coste real). No es transmision
                # de divisa extranjera. Añadido propio, pendiente de Auditor 2.
                if acquired_amount is not None:
                    bought_with_base.setdefault((acquired or "").upper(), []).append(
                        CurrencyLot(day, Decimal(str(acquired_amount)), Decimal(str(amount)), f"cambio {ref}", when)
                    )
                continue
            if (acquired or "").upper() != base_currency:
                unsupported.append(f"{disposed}->{(acquired or '?').upper()} {day}")
                by_currency.setdefault(disposed, [])
                continue
            rate = (
                explicit_rates.get(day)
                if fx_conversions is not None
                else conv_rate(disposed, day)
            )
            by_currency.setdefault(disposed, []).append(Conversion(day, Decimal(str(amount)), rate, ref, when))
        results = []
        all_events = {}
        for transaction, company in tx_rows:
            if company is not None:
                all_events.setdefault(company.ticker, []).append(transaction)
        for currency, conversions in sorted(by_currency.items()):
            sales = []
            for events in all_events.values():
                if not any((t.currency or "").upper() == currency for t in events):
                    continue
                _, hist = replay_tax_fifo(events, resolve_rate, date.min, end)
                sales += [
                    {
                        "date": e["transaction"].trade_date,
                        "proceeds_native": e["proceeds_native"],
                        "proceeds_base": e["proceeds_base"],
                        "ref": f"sale#{e['transaction'].id}",
                        "time": _execution_time(e["transaction"]),
                    }
                    for e in hist
                    if (e["transaction"].currency or "").upper() == currency
                ]
            outflows: list[Outflow] = []
            extra_lots: list[CurrencyLot] = []
            unmodeled: list[str] = []
            fund_like = 0
            for transaction, company in tx_rows:
                if (transaction.currency or "").upper() != currency:
                    continue
                action = (transaction.action or "").lower()
                day = transaction.trade_date
                payload = transaction.raw_payload if isinstance(transaction.raw_payload, dict) else {}
                if (
                    str(payload.get("assetCategory") or "").upper() == "FUND"
                    or str(payload.get("subCategory") or "").upper() in {"ETF", "ETN"}
                ) and (action in BUY_ACTIONS or action in SELL_ACTIONS):
                    fund_like += 1
                if action in BUY_ACTIONS:
                    # V0282-22 / V0706-22: la compra (con su comision) consume divisa sin resultado.
                    outflows.append(
                        Outflow(day, transaction.quantity * transaction.price + transaction.fees, "compra", f"buy#{transaction.id}")
                    )
                elif action in SELL_ACTIONS:
                    continue  # entrada: ya esta en los lotes de ventas
                elif "fee" in action and "dividend" not in action:
                    outflows.append(Outflow(day, abs(cash_amount(transaction)), "comision", f"fee#{transaction.id}"))
                elif "withholding" in action or "dividend" in action or "interest" in action:
                    if not income_by_analogy:
                        unmodeled.append(action)
                        continue
                    amount = (
                        -withholding_cost(transaction)
                        if "withholding" in action
                        else cash_amount(transaction)
                    )
                    if amount > 0:
                        rate = resolve_rate(currency, day)
                        extra_lots.append(
                            CurrencyLot(day, amount, None if rate is None else amount * rate, f"{action}#{transaction.id}", _execution_time(transaction))
                        )
                    elif amount < 0:
                        outflows.append(Outflow(day, -amount, action, f"{action}#{transaction.id}"))
                else:
                    unmodeled.append(action or "?")
            data_through = max(
                [t.trade_date for t, _ in tx_rows] + [c.converted_on for c in conversions]
            )
            result = compute_currency_ledger(
                lots_from_sales(sales) + extra_lots + bought_with_base.get(currency, []), conversions, start, end,
                opening_complete=opening_complete, outflows=outflows, data_through=data_through,
            )
            notes = []
            if unmodeled:
                notes.append(
                    f"{len(unmodeled)} movimientos en {currency} sin modelar (dividendos, intereses, retenciones u otros; "
                    "activar fx_income_by_analogy para tratarlos por analogia)"
                )
            if fund_like:
                notes.append(
                    f"{fund_like} operaciones con fondos/ETF en {currency} (V0775-21, diferencia imputada al reembolsar): fuera de alcance"
                )
            if income_by_analogy and any(
                k in (t.action or "").lower() for t, _ in tx_rows for k in ("dividend", "interest", "withholding")
            ):
                result["analogy"] = ANALOGY_LABEL
                notes.append(f"dividendos/intereses como entradas: {ANALOGY_LABEL}")
            if unmodeled or fund_like:
                result["status"], result["gain_base"], result["blocked_loss_base"] = INCOMPLETE, None, None
            result["reason"] = "; ".join(filter(None, [result["reason"], *notes])) or None
            result["currency"] = currency
            for row in result["rows"]:
                row["currency"] = currency
            results.append(result)
        if unsupported:
            for r in results:
                r["status"], r["gain_base"] = INCOMPLETE, None
                r["reason"] = "; ".join(filter(None, [r["reason"], "cambios a otra divisa distinta de EUR no soportados: " + ", ".join(unsupported)]))
        if not results:
            return compute_currency_ledger([], [], start, end)
        worst = (
            COMPUTED
            if all(r["status"] == COMPUTED for r in results)
            else INCOMPLETE
        )
        # Igual que el resto de importes del informe, las cifras del libro de
        # divisas se publican en centimos (ROUND_HALF_UP): un float con diez
        # decimales de precision de calculo no es un dato fiscal y la UI lo
        # mostraba en crudo. ``unconverted`` son unidades de la propia divisa
        # y siguen la misma regla.
        def _ledger_money(value) -> float | None:
            return _money(Decimal(str(value))) if value is not None else None

        return {
            "criterion": CRITERION,
            "status": worst,
            "gain_base": (
                _money(sum(Decimal(str(r["gain_base"])) for r in results))
                if worst == COMPUTED else None
            ),
            "reason": "; ".join(dict.fromkeys(r["reason"] for r in results if r["reason"])) or None,
            "rows": [row for r in results for row in r["rows"]],
            # Por divisa: cada una con su estado, ganancia en EUR y divisa sin convertir
            # (en unidades de esa divisa). El total EUR (gain_base) va aparte y solo
            # existe si todas las divisas estan calculadas.
            "by_currency": {
                r["currency"]: {
                    "status": r["status"],
                    "gain_base": _ledger_money(r["gain_base"]),
                    "blocked_loss_base": _ledger_money(r["blocked_loss_base"]),
                    "unconverted": _ledger_money(r["unconverted"]),
                    "reason": r["reason"],
                }
                for r in results
            },
            "unconverted": {r["currency"]: _ledger_money(r["unconverted"]) for r in results},
            "blocked_loss_base": (
                _money(sum(Decimal(str(r["blocked_loss_base"])) for r in results))
                if worst == COMPUTED
                else None
            ),
            "analogy": next((r["analogy"] for r in results if r.get("analogy")), None),
            "sources": list(SOURCES),
        }

    def _build_filing(self, db: Session, fiscal_year: int, data: dict, tme: Decimal | None = None) -> dict:
        """Capa de declaracion IRPF (casillas Modelo 100 + doble imposicion).

        Deriva de los agregados del informe; nunca inventa cifras: si falta
        FX o el pais del emisor, el bloque afectado queda en None o en
        ``manual_review``. El pais de retencion se aproxima con
        ``Company.domicile_country`` (limitacion documentada en
        ``tax_irpf_filing``).
        """
        summary0 = data.get("summary") or {}
        if (summary0.get("base_currency") or "EUR") != "EUR":
            # Las casillas del Modelo 100 son importes en EUR: con la cartera
            # en otra divisa base no se publican cifras bajo rótulos IRPF.
            return {
                "available": False,
                "reason": (
                    "La cartera no usa EUR como divisa base: las casillas del "
                    "Modelo 100 y la deducción 0588 son importes en euros y "
                    "no se publican cifras en otra divisa. Cambia la divisa "
                    "base de la cartera a EUR para obtener la capa de "
                    "declaración."
                ),
            }
        tickers = {
            b["ticker"]
            for b in (data.get("dividends") or []) + (data.get("realized") or [])
            if not str(b.get("ticker", "")).startswith("UNATTRIBUTED:")
        }
        country_by_ticker: dict[str, str | None] = {}
        if tickers:
            for company in db.scalars(
                select(Company).where(Company.ticker.in_(sorted(tickers)))
            ):
                country_by_ticker[company.ticker] = company.domicile_country
        summary = data.get("summary") or {}
        # Saldos netos de los ejercicios anteriores, recalculados en
        # memoria sin la capa filing (evita recursion y dobles calculos).
        # 8 y no 4: una perdida de fiscal_year-8 sigue viva en fiscal_year-4
        # y consume ganancias de la ventana (art. 49.1.b LIRPF).
        prior_year_nets = []
        for prior_year in range(fiscal_year - 2 * CARRYFORWARD_WINDOW_YEARS, fiscal_year):
            prior_data = self.compute_report(db, prior_year, include_filing=False)
            prior_summary = prior_data["summary"]
            # Rendimientos del ahorro del ejercicio previo (dividendos +
            # intereses): fijan el 25 % que ya absorbió saldos negativos.
            prior_interest = build_interest(prior_data.get("misc") or [], prior_year)
            prior_rcm = None
            if prior_summary.get("total_dividends_base") is not None and not prior_interest["incomplete"]:
                prior_rcm = Decimal(str(prior_summary["total_dividends_base"])) + Decimal(
                    # nosemgrep: gerarai-money-none-to-zero -- solo se suma con interest["incomplete"] False; un interes sin convertir marca incomplete y rcm_net_base queda None
                    str(prior_interest["received"]["amount_base"] or 0)
                )
            prior_year_nets.append({
                "year": prior_year,
                "net_gyp_base": prior_summary.get("total_realized_gain_base"),
                "net_rcm_base": prior_rcm,
                "incomplete": prior_summary.get("incomplete_fx", False),
            })
        # Saldos pendientes declarados (anexo C.3 de la última declaración):
        # fuente autoritativa para los saldos de ejercicios anteriores. Son
        # datos fiscales PERSONALES: se leen del tenant del portfolio activo
        # (Tenant.metadata["tax_prior_losses_pending"], JSON {"2022": 300.0}),
        # NUNCA de configuración global del proceso — en un despliegue
        # multiusuario una variable global filtraría los saldos de una
        # persona a las declaraciones de otra. Sin dato del tenant, los
        # saldos se derivan del libro y se etiquetan como estimación NO
        # trasladable a casillas (ver build_loss_compensation).
        declared_pending = None
        portfolio = self.fx.portfolio(db)
        tenant = (
            db.get(Tenant, portfolio.tenant_id)
            if portfolio is not None and portfolio.tenant_id is not None
            else None
        )
        raw_declared = (tenant.metadata_ or {}).get("tax_prior_losses_pending") if tenant else None
        if isinstance(raw_declared, dict):
            try:
                declared_pending = {
                    int(year): Decimal(str(amount))
                    for year, amount in raw_declared.items()
                    if Decimal(str(amount)) > 0
                }
            except (ValueError, TypeError, ArithmeticError):
                declared_pending = None
        interest = build_interest(data.get("misc") or [], fiscal_year)
        # Saldo neto de rendimientos del capital mobiliario del ahorro: los
        # dividendos MÁS los intereses cobrados (fija el 25 % de compensación).
        rcm_net_base: Decimal | None = None
        if summary.get("total_dividends_base") is not None and not interest["incomplete"]:
            rcm_net_base = Decimal(str(summary["total_dividends_base"])) + Decimal(
                # nosemgrep: gerarai-money-none-to-zero -- solo se suma con interest["incomplete"] False; un interes sin convertir marca incomplete y rcm_net_base queda None
                str(interest["received"]["amount_base"] or 0)
            )
        return {
            "available": True,
            "tme_percent_manual": float(tme * 100) if tme is not None else None,
            "intereses": interest,
            "casillas": build_casillas(
                data.get("dividends") or [], data.get("realized") or [], fiscal_year
            ),
            "double_taxation": build_double_taxation(
                data.get("dividends") or [],
                country_by_ticker,
                fiscal_year,
                tme=tme,
            ),
            "loss_compensation": build_loss_compensation(
                prior_year_nets,
                None if summary.get("total_realized_gain_base") is None
                else Decimal(str(summary["total_realized_gain_base"])),
                rcm_net_base,
                fiscal_year,
                declared_pending=declared_pending,
            ),
        }

    def get_report(self, db: Session, fiscal_year: int, tme: Decimal | None = None) -> dict:
        """Informe de un ejercicio. SOLO LECTURA: nunca escribe en la base.

        Si existe un informe persistido lo devuelve; si no, lo calcula en
        memoria y lo marca con ``persisted=False`` y ``generated_at=None``
        (honesto: no esta guardado; un GET repetido no cambia el estado).
        La persistencia vive en ``regenerate_report`` (POST).
        """
        report = db.scalar(
            select(TaxReport).where(
                TaxReport.fiscal_year == fiscal_year
            ).order_by(TaxReport.updated_at.desc())
        )
        if report is not None:
            data = {
                "summary": sanitize_summary_over_sells(report.summary, report.realized),
                "dividends": report.dividends,
                "realized": sanitize_realized_over_sells(report.realized),
                "misc": report.misc,
                "generated_at": report.generated_at.isoformat() if report.generated_at else None,
                "persisted": True,
            }
            # La capa de declaracion se calcula al leer (no se persiste): es
            # presentacion derivada de los mismos agregados, siempre al dia
            # con el mapeo normativo vigente en el codigo.
            data["filing"] = self._build_filing(db, fiscal_year, data, tme=tme)
            data["versioning"] = report_versioning(data["summary"], persisted=True)
            return data
        data = self.compute_report(db, fiscal_year, tme=tme)
        data["generated_at"] = None
        data["persisted"] = False
        data["versioning"] = report_versioning(data["summary"], persisted=False)
        return data

    def regenerate_report(
        self, db: Session, fiscal_year: int, fx_opening_complete: bool = False,
        fx_income_by_analogy: bool = False,
    ) -> dict:
        """Recalcula y PERSISTE el informe del ejercicio (camino POST)."""
        data = self.compute_report(
            db, fiscal_year, fx_opening_complete=fx_opening_complete,
            fx_income_by_analogy=fx_income_by_analogy,
        )
        portfolio = self.fx.ensure_portfolio(db)
        report = db.scalar(
            select(TaxReport).where(TaxReport.fiscal_year == fiscal_year)
        )
        if report is None:
            report = TaxReport(
                portfolio_id=portfolio.id if portfolio else None,
                fiscal_year=fiscal_year,
                base_currency=data["summary"]["base_currency"],
            )
            db.add(report)
        report.base_currency = data["summary"]["base_currency"]
        report.summary = data["summary"]
        report.dividends = data["dividends"]
        report.realized = data["realized"]
        report.misc = data["misc"]
        report.generated_at = datetime.now(UTC)
        db.commit()
        db.refresh(report)
        data["generated_at"] = report.generated_at.isoformat()
        data["persisted"] = True
        data["versioning"] = report_versioning(data["summary"], persisted=True)
        return data



def build_tax_summary_rows(db: Session, fiscal_year: int | None = None) -> list[dict]:
    """Position-derived holdings summary used by the tax page.

    ``fiscal_year`` queda reservado para scoping por ano (ventas del ejercicio);
    las posiciones actuales no dependen del ano, asi que es opcional - la ruta
    ``GET /api/taxes/holdings`` lo llama sin ano.
    """
    rows = db.execute(
        select(Position, Company).join(Company, Position.company_id == Company.id)
    ).all()
    result = []
    for position, company in rows:
        # F240: las claves son las que lista /taxes (cost_basis, market_value,
        # unrealized_pnl, currency) - antes se devolvian cost_basis_base y
        # unrealized_pnl_base y toda la fila salia «-». None es «sin dato»
        # (la UI lo pinta NA): nunca 0 inventado desde un null.
        result.append(
            {
                "ticker": company.ticker,
                "quantity": float(position.quantity),
                "cost_basis": (
                    float(position.cost_basis_base)
                    if position.cost_basis_base is not None
                    else None
                ),
                "market_value": (
                    float(position.market_value_base)
                    if position.market_value_base is not None
                    else None
                ),
                "unrealized_pnl": (
                    float(position.unrealized_pnl_base)
                    if position.unrealized_pnl_base is not None
                    else None
                ),
                "currency": position.base_currency,
                "as_of": position.as_of.isoformat(),
            }
        )
    return result