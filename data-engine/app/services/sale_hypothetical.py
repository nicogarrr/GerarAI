"""Venta hipotética para el IRPF del Cerebro, con los lotes que da el usuario.

Revisión de Nico: «¿cuánto IRPF pagaría si vendo AAPL?» sin AAPL en cartera
cambiaba a la información de la empresa sin decir que no calculaba el
impuesto. Ahora el Cerebro dice que no puede calcular el IRPF real y ofrece
una estimación: si el usuario da cuántas acciones, a qué precio y cuándo las
compró, se calcula aquí con el mismo núcleo FIFO que la posición guardada
(``sale_simulation.consume_fifo``) y la misma escala del ahorro.

Solo se interpreta texto con forma clara de lote («10 acciones a 150 $ el 3
de marzo de 2024», «otras 10 a 200 €»); lo que no se entiende no se inventa.
"""

from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.local_date import local_today
from app.models.entities import Company, MarketPrice
from app.services.price_units import price_in_currency
from app.services.sale_simulation import FifoSale, apply_backward_repurchase, consume_fifo
from app.services.tax_irpf_filing import calculate_savings_tax
from app.services.tax_report_service import MAX_FX_AGE_DAYS, _rate_not_older_than
from app.valuation.currency import listing_currency

TAX_CURRENCY = "EUR"

# «1,234.56» (miles con coma y punto decimal, formato US) va primero: sin él la
# cifra se cortaba en «1,234» y el precio del lote era 1,234.
_NUM = r"\d{1,3}(?:,\d{3})+\.\d+|\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:[.,]\d+)?"
_CUR = r"€|euros?\b|eur\b|us\$|\$|d[oó]lares\b|usd\b|£|libras\b|gbp\b"
_CURRENCY_MAP = {
    "€": "EUR", "euro": "EUR", "euros": "EUR", "eur": "EUR",
    "$": "USD", "us$": "USD", "dolares": "USD", "dólares": "USD", "usd": "USD",
    "£": "GBP", "libras": "GBP", "gbp": "GBP",
}
_LOT_RE = re.compile(
    rf"(?i)(?<![\d.,])(?P<qty>{_NUM})\s*(?:acciones|t[ií]tulos|participaciones)?"
    rf"(?:\s+(?:de\s+|en\s+)?[A-Za-z][\w.]*)?\s+(?:a|por|@)\s+(?:(?P<pre>{_CUR})\s*)?"
    rf"(?P<price>{_NUM})\s*(?P<cur>{_CUR})?"
)
_SALE_PRICE_RE = re.compile(
    rf"(?i)\bvend\w*\s+(?:(?:las|los|todas|todo|todos|hoy|ahora|mis)\s+)*"
    # «vendo la mitad (de mis AAPL) a 150 €»: la mitad es una cantidad como «vendo 5»;
    # antes el precio no se reconocía y se usaba la cotización en su lugar.
    # «si vendo SHEL.L a 30 £» / «vendo mis acciones de AAPL a 200 $»: el ticker
    # sin cantidad delante tambien vale (antes solo tras un numero o «la mitad»,
    # y sin el se usaba EN SILENCIO la cotizacion en lugar del precio dado).
    rf"(?:(?:{_NUM}|(?:la\s+)?mitad)\s*)?(?:(?:acciones|t[ií]tulos|participaciones)\s*)?(?:de\s+)?"
    rf"(?:[A-Za-z][\w.]*\s+){{0,2}}(?:a|por)\s+"
    rf"(?:(?P<pre>{_CUR})\s*)?(?P<price>{_NUM})\s*(?P<cur>{_CUR})?"
    rf"|\bprecio\s+de\s+venta\s+(?:de\s+|es\s+|ser[ií]a\s+)?(?:(?P<pre2>{_CUR})\s*)?"
    rf"(?P<price2>{_NUM})\s*(?P<cur2>{_CUR})?"
)
# «… que compré a 150 $» sin cantidad: el lote es lo que se vende.
_BOUGHT_AT_RE = re.compile(
    rf"(?i)\bcompr\w*\s+(?:(?:las|los|todas|todo|todos)\s+)?(?:a|por)\s+(?:(?P<pre>{_CUR})\s*)?"
    rf"(?P<price>{_NUM})\s*(?P<cur>{_CUR})?"
)
# «vendo mis 10», «las 10», «hoy 10», «unas 10»: sin estas palabras entre el
# verbo y la cifra la cantidad no se leía y se simulaba la venta de TODO.
_SALE_QTY_RE = re.compile(
    rf"(?i)\bvend\w*\s+(?:(?:solo|s[oó]lo|mis|las|los|unas|unos|hoy|ahora)\s+)*(?P<qty>-?(?:{_NUM}))\b"
    # «vendo 15 %» es un porcentaje, no 15 acciones.
    r"(?![\d.,]*\s*(?:%|por\s*ciento))"
)
# «vendo el 50 %», «un 20 por ciento»: parte de la posición, no una cantidad.
_SALE_PCT_RE = re.compile(
    rf"(?i)\bvend\w*\s+(?:(?:solo|s[oó]lo|el|un|hoy|ahora)\s+)*(?P<pct>{_NUM})\s*(?:%|por\s*ciento)"
)
# «vendo un tercio», «tres cuartos»: antes se simulaba la venta de TODO.
_SALE_FRACTIONS = {
    "un tercio": (1, 3), "dos tercios": (2, 3), "un cuarto": (1, 4), "tres cuartos": (3, 4),
}
_SALE_FRACTION_RE = re.compile(
    r"(?i)\bvend\w*\s+(?:(?:solo|s[oó]lo|hoy|ahora)\s+)*(?P<frac>un\s+tercio|dos\s+tercios|un\s+cuarto|tres\s+cuartos)\b"
)
_SALE_HALF_RE = re.compile(r"(?i)\bvend\w*\s+(?:la\s+)?mitad\b")

_MONTHS = {
    "enero": 1, "ene": 1, "febrero": 2, "feb": 2, "marzo": 3, "mar": 3, "abril": 4, "abr": 4,
    "mayo": 5, "may": 5, "junio": 6, "jun": 6, "julio": 7, "jul": 7, "agosto": 8, "ago": 8,
    "septiembre": 9, "setiembre": 9, "sep": 9, "sept": 9, "octubre": 10, "oct": 10,
    "noviembre": 11, "nov": 11, "diciembre": 12, "dic": 12,
}
_MONTH = "|".join(sorted(_MONTHS, key=len, reverse=True))
_DATE_DMY_WORDS = re.compile(rf"(?i)\b(\d{{1,2}})\s+de\s+({_MONTH})\.?\s+(?:de|del)\s+(\d{{4}})\b")
_DATE_MY_WORDS = re.compile(rf"(?i)\b({_MONTH})\.?\s+(?:de|del)\s+(\d{{4}})\b")
_DATE_NUMERIC = re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b")
_DATE_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")


@dataclass
class HypoLot:
    quantity: Decimal
    price: Decimal
    currency: str | None
    trade_date: date | None
    #: True si la fecha solo traía mes y año (se toma el día 1).
    approx_date: bool = False


@dataclass
class HypoSale:
    quantity: Decimal
    held: Decimal
    sale_price: Decimal | None
    sale_currency: str
    sale_price_source: str  # "usuario" | "cotización" | "falta"
    sale_price_date: date | None = None
    sale_price_ref: int | None = None
    fifo: FifoSale | None = None
    value_eur: Decimal | None = None
    cost_eur: Decimal | None = None
    gain_eur: Decimal | None = None
    tax_eur: Decimal | None = None
    native_gain: Decimal | None = None
    #: Cambio EUR por unidad de la divisa de venta, en la fecha de venta.
    sale_rate: Decimal | None = None
    missing: list[str] = field(default_factory=list)
    invalid: str | None = None
    undated: bool = False
    approx_dates: bool = False


def parse_number(text: str) -> Decimal | None:
    """«1.234,5» → 1234.5; «1,234.5» → 1234.5; «150.5» → 150.5; «1.500» → 1500; «0.125» → 0.125."""
    raw = text.strip()
    if "," in raw and "." in raw:
        # El último separador es el decimal: «1.234,5» (es) y «1,234.5» (US).
        if raw.rfind(".") > raw.rfind(","):
            raw = raw.replace(",", "")
        else:
            raw = raw.replace(".", "").replace(",", ".")
    elif "," in raw:
        raw = raw.replace(",", ".")
    elif re.fullmatch(r"[1-9]\d{0,2}(?:\.\d{3})+", raw):
        # Un grupo de miles nunca empieza por 0: «0.125» es 0,125, no 125.
        raw = raw.replace(".", "")
    try:
        return Decimal(raw)
    except InvalidOperation:
        return None


def _currency(*tokens: str | None) -> str | None:
    for token in tokens:
        if token:
            code = _CURRENCY_MAP.get(token.strip().lower())
            if code:
                return code
    return None


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _find_date(segment: str) -> tuple[date | None, bool]:
    """Primera fecha del fragmento y si es aproximada (solo mes y año)."""
    candidates: list[tuple[int, date | None, bool]] = []
    for m in _DATE_DMY_WORDS.finditer(segment):
        candidates.append((m.start(), _safe_date(int(m.group(3)), _MONTHS[m.group(2).lower()], int(m.group(1))), False))
    for m in _DATE_ISO.finditer(segment):
        candidates.append((m.start(), _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3))), False))
    for m in _DATE_NUMERIC.finditer(segment):
        candidates.append((m.start(), _safe_date(int(m.group(3)), int(m.group(2)), int(m.group(1))), False))
    if not candidates:
        for m in _DATE_MY_WORDS.finditer(segment):
            candidates.append((m.start(), _safe_date(int(m.group(2)), _MONTHS[m.group(1).lower()], 1), True))
    candidates = [c for c in candidates if c[1] is not None]
    if not candidates:
        return None, False
    _, found, approx = min(candidates, key=lambda c: c[0])
    return found, approx


def _is_sale_clause(text: str, start: int) -> bool:
    before = text[max(0, start - 30):start].lower()
    sale_at = max(before.rfind("vend"), before.rfind("venta"))
    buy_at = before.rfind("compr")
    return sale_at >= 0 and sale_at > buy_at


def parse_purchase_lots(text: str) -> list[HypoLot]:
    """Lotes de compra escritos en la pregunta («10 acciones a 150 $ el 3 de marzo de 2024»)."""
    lots: list[HypoLot] = []
    matches = [m for m in _LOT_RE.finditer(text or "") if not _is_sale_clause(text, m.start())]
    for i, m in enumerate(matches):
        qty = parse_number(m.group("qty"))
        price = parse_number(m.group("price"))
        if qty is None or price is None or qty <= 0 or price <= 0:
            continue
        # La fecha va detrás del lote (hasta el siguiente) o justo delante.
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        after = text[m.end():min(end, m.end() + 60)]
        trade_date, approx = _find_date(after)
        if trade_date is None:
            prev_end = matches[i - 1].end() if i > 0 else 0
            trade_date, approx = _find_date(text[max(prev_end, m.start() - 45):m.start()])
        lots.append(HypoLot(qty, price, _currency(m.group("pre"), m.group("cur")), trade_date, approx))
    if not lots:
        bought = _BOUGHT_AT_RE.search(text or "")
        sold = _SALE_QTY_RE.search(text or "")
        qty = parse_number(sold.group("qty")) if sold else None
        price = parse_number(bought.group("price")) if bought else None
        if bought and qty and price and qty > 0 and price > 0:
            trade_date, approx = _find_date(text[bought.end():bought.end() + 60])
            lots.append(HypoLot(qty, price, _currency(bought.group("pre"), bought.group("cur")), trade_date, approx))
    return lots


def parse_sale_price(text: str) -> tuple[Decimal, str | None] | None:
    m = _SALE_PRICE_RE.search(text or "")
    if m is None:
        return None
    raw = m.group("price") or m.group("price2")
    price = parse_number(raw) if raw else None
    if price is None or price <= 0:
        return None
    return price, _currency(m.group("pre"), m.group("cur"), m.group("pre2"), m.group("cur2"))


def _sale_quantity(text: str, held: Decimal) -> Decimal:
    if _SALE_HALF_RE.search(text):
        return held / 2
    pct = _SALE_PCT_RE.search(text)
    if pct:
        share = parse_number(pct.group("pct"))
        if share is not None:
            return held * share / 100
    frac = _SALE_FRACTION_RE.search(text)
    if frac:
        num, den = _SALE_FRACTIONS[" ".join(frac.group("frac").lower().split())]
        return held * num / den
    m = _SALE_QTY_RE.search(text)
    if m:
        asked = parse_number(m.group("qty"))
        if asked is not None:
            return asked
    return held


def latest_quote(db: Session, company: Company) -> tuple[Decimal, date, int] | None:
    row = db.execute(
        select(MarketPrice.close, MarketPrice.date, MarketPrice.id, MarketPrice.quote_currency)
        .where(MarketPrice.company_id == company.id, MarketPrice.source != "seed", MarketPrice.close > 0)
        .order_by(desc(MarketPrice.date))
        .limit(1)
    ).first()
    if row is None:
        return None
    price = price_in_currency(Decimal(row[0]), quote_currency=row[3],
                              target_currency=listing_currency(company.ticker, company.currency), company=company)
    return (price, row[1], row[2]) if price is not None else None


def simulate_hypothetical_sale(
    db: Session,
    *,
    lots: list[HypoLot],
    question: str,
    company: Company | None,
    today: date | None = None,
) -> HypoSale:
    """Ganancia FIFO en euros e IRPF de vender los lotes dados (o parte)."""
    today = today or local_today()
    from app.services.tax_sale_intent import sale_intent_issue

    issue = sale_intent_issue(question)
    if issue:
        return HypoSale(
            quantity=Decimal("0"), held=sum((lot.quantity for lot in lots), Decimal("0")),
            sale_price=None, sale_currency=TAX_CURRENCY, sale_price_source="falta", missing=[issue],
        )
    explicit = next((lot.currency for lot in lots if lot.currency), None)
    sale = parse_sale_price(question)
    company_ccy = (company.currency or None) if company is not None else None
    default_ccy = (sale[1] if sale and sale[1] else None) or explicit or company_ccy or TAX_CURRENCY
    for lot in lots:
        lot.currency = lot.currency or default_ccy
    held = sum((lot.quantity for lot in lots), Decimal("0"))
    result = HypoSale(
        quantity=_sale_quantity(question, held), held=held, sale_price=None,
        sale_currency=default_ccy, sale_price_source="falta",
    )
    if not 0 < result.quantity <= held:
        result.invalid = "La cantidad que quieres vender debe ser positiva y no superar las acciones compradas. No he cambiado la cantidad solicitada."
        return result
    if any(lot.trade_date is not None and lot.trade_date > today for lot in lots):
        result.invalid = "Hay una fecha de compra futura respecto a la venta de hoy. Confirma las fechas antes de calcular el IRPF."
        return result
    if re.search(r"(?i)comisi[oó]n|comisiones|gastos|fees?\b", question):
        result.invalid = "Has indicado comisiones o gastos. Necesito separar los de compra y los de venta y su divisa; no los he ignorado ni he calculado una cuota sin ellos."
        return result
    if sale is not None:
        result.sale_price, result.sale_price_source = sale[0], "usuario"
        result.sale_currency = sale[1] or default_ccy
    elif company is not None:
        quote = latest_quote(db, company)
        if quote is not None:
            result.sale_price, result.sale_price_date, result.sale_price_ref = quote
            result.sale_currency = listing_currency(company.ticker, company.currency)
            result.sale_price_source = "cotización"
    if result.sale_price is None:
        result.missing.append("el precio al que venderías")
        return result

    # FIFO: fechadas por fecha; sin fecha, en el orden en que las das.
    result.undated = any(lot.trade_date is None for lot in lots)
    result.approx_dates = any(lot.approx_date for lot in lots)
    ordered = lots if result.undated else sorted(lots, key=lambda lot: lot.trade_date or date.min)
    currencies = {lot.currency or TAX_CURRENCY for lot in ordered} | {result.sale_currency}
    from app.services.portfolio_fx_service import PortfolioFXService

    fx_table = PortfolioFXService().fx_table(
        db, currencies=currencies - {TAX_CURRENCY}, base_currency=TAX_CURRENCY, as_of_max=today,
    ) if currencies - {TAX_CURRENCY} else {}
    queue: deque[dict] = deque()
    for lot in ordered:
        ccy = lot.currency or TAX_CURRENCY
        rate: Decimal | None
        if ccy == TAX_CURRENCY:
            rate = Decimal("1")
        elif lot.trade_date is None:
            rate = None
        else:
            rate = _rate_not_older_than(
                fx_table, quote_currency=ccy, base_currency=TAX_CURRENCY,
                as_of=lot.trade_date, max_age_days=MAX_FX_AGE_DAYS,
            )
        queue.append({
            "qty": lot.quantity, "unit": lot.price, "unit_eur": lot.price * rate if rate is not None else None,
            "date": lot.trade_date, "currency": ccy,
        })
    result.fifo = consume_fifo(queue, result.quantity)
    if not result.undated:
        apply_backward_repurchase(
            result.fifo, queue,
            [(lot.trade_date, lot.quantity) for lot in ordered], [], today,
        )
    sale_rate = (
        Decimal("1") if result.sale_currency == TAX_CURRENCY
        else _rate_not_older_than(
            fx_table, quote_currency=result.sale_currency, base_currency=TAX_CURRENCY,
            as_of=today, max_age_days=MAX_FX_AGE_DAYS,
        )
    )
    result.sale_rate = sale_rate
    same_ccy = all(lot.currency == result.sale_currency for lot in result.fifo.lots)
    if same_ccy:
        native_cost = sum((lot.unit_cost_native * lot.quantity for lot in result.fifo.lots), Decimal("0"))
        result.native_gain = result.sale_price * result.quantity - native_cost
    # Criterio del informe fiscal (DGT V0152-26): coste nativo al cambio de
    # la venta; solo un lote en otra divisa necesita el cambio de su compra.
    cost_eur = result.fifo.cost_eur_dgt(result.sale_currency, sale_rate) if sale_rate is not None else None
    if cost_eur is None and sale_rate is not None:
        result.missing.append(
            "la fecha de compra de cada lote (para pasar el coste a euros al tipo de ese día)"
            if any(lot.trade_date is None for lot in result.fifo.lots)
            else "el tipo de cambio de la fecha de compra"
        )
    if sale_rate is None:
        result.missing.append("el tipo de cambio de hoy")
    if result.missing:
        return result
    assert cost_eur is not None and sale_rate is not None
    result.cost_eur = cost_eur
    result.value_eur = result.sale_price * result.quantity * sale_rate
    result.gain_eur = result.value_eur - cost_eur
    if result.gain_eur > 0:
        result.tax_eur = calculate_savings_tax(result.gain_eur, today.year)
    return result
