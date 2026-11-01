"""Preguntas del cerebro sobre la CUENTA del usuario (solo lectura, por tenant).

Cada respuesta sale de tablas que la app ya guarda para el usuario que
pregunta (``db.info["tenant_id"]``; además del filtro global de tenant, cada
consulta lleva su filtro explícito). Nada se escribe, nada se pide a un
proveedor en directo y nunca se ejecutan órdenes: si algo se cambia en la app,
se dice dónde.

«Hoy» del usuario es ``local_today()`` (Europe/Madrid); los datos de mercado
van por día UTC y se citan con su fecha.
"""
from __future__ import annotations

import re
import unicodedata
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.local_date import local_today
from app.models import PortfolioDailySnapshot
from app.schemas import ChatResponse
from app.services.display_es import fecha_es
from app.services.user_context import money_es, num_es, pct_es

_MONTHS_EN = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _english() -> bool:
    from app.core.i18n import current_language

    return current_language() == "en"


def _tenant(db: Session) -> int | None:
    tenant = db.info.get("tenant_id")
    if type(tenant) is not int or tenant <= 0:
        return None
    return tenant


def _fold(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", (text or "").lower()) if unicodedata.category(c) != "Mn"
    )


def _date_en(value) -> str:
    return f"{_MONTHS_EN[value.month - 1]} {value.day}, {value.year}"


def _num_en(value: float, digits: int = 2) -> str:
    return f"{value:,.{digits}f}"


def _money(value: float | None, currency: str | None, *, signed: bool = False, english: bool = False) -> str:
    if value is None:
        return "N/A" if english else "N/D"
    if not english:
        return money_es(value, _symbol(currency), signed=signed)
    text = _num_en(value)
    if signed and value > 0:
        text = "+" + text
    return f"{text} {_symbol(currency)}"


def _pct(fraction: float, *, signed: bool = False, english: bool = False) -> str:
    if not english:
        return pct_es(fraction, signed=signed)
    text = _num_en(fraction * 100, 1)
    if signed and fraction > 0:
        text = "+" + text
    return f"{text}%"


def _symbol(currency: str | None) -> str:
    return "€" if (currency or "").upper() == "EUR" else (currency or "¿divisa?")


def _response(text: str, sources: list[dict], path: str) -> ChatResponse:
    return ChatResponse(
        answer=text, sources=sources, model="deterministic", prompt_version="brain-account-v1",
        confidence=0.9, llm_trace={"path": path, "provider_calls": 0, "generated": False},
    )


def _source(kind: str, ident, title: str, url: str) -> dict:
    return {"type": kind, "id": ident, "title": title, "url": url}


# ------------------------------------------------------------ cambio del día

_TODAY = r"(?:hoy|today|del dia|de hoy|diari[ao]|daily)"
_DAILY_CHANGE_ES = re.compile(
    r"\b(?:(?:cuanto|como|que tal)\s+(?:ha\s+)?(?:subido|bajado|cambiado|variado|movido|ido|va|esta|lleva)"
    r"(?:\s+\w+){0,3}\s+hoy"
    r"|(?:he|hemos)\s+(?:ganado|perdido)\s+hoy"
    r"|(?:gano|pierdo|ganado|perdido)\s+hoy"
    r"|variacion\s+(?:diaria|de hoy|del dia)"
    r"|cambio\s+(?:diario|de hoy|del dia))\b"
)
_DAILY_CHANGE_EN = re.compile(
    r"\b(?:(?:up|down)\s+today|today'?s\s+(?:change|move|return|performance)"
    r"|daily\s+(?:change|move|return|performance)|(?:do|doing|did)\s+today"
    r"|(?:gain|gained|lose|lost|made)\s+today)\b"
)
_PORTFOLIO_WORD = re.compile(r"\b(?:cartera|portfolio|patrimonio|inversiones|he ganado|he perdido|gane|perdi|"
                             r"i (?:gain|gained|lose|lost|made))\b")


def _asks_daily_change(text: str) -> bool:
    if not (_DAILY_CHANGE_ES.search(text) or _DAILY_CHANGE_EN.search(text)):
        return False
    # «¿cuánto ha subido UBER hoy?» es la cotización de una empresa, no tu cartera.
    return bool(_PORTFOLIO_WORD.search(text)) or bool(re.search(r"\b(?:he|hemos)\s+(?:ganado|perdido)\b", text))


def _daily_change_answer(db: Session, tenant: int) -> ChatResponse:
    english = _english()
    latest = db.scalar(
        select(PortfolioDailySnapshot)
        .where(PortfolioDailySnapshot.tenant_id == tenant)
        .order_by(PortfolioDailySnapshot.snapshot_date.desc(), PortfolioDailySnapshot.id.desc())
        .limit(1)
    )
    if latest is None:
        text = (
            "There is no daily history of your portfolio yet (a snapshot is saved each day when prices "
            "refresh). Your current value is in Portfolio."
            if english else
            "Aún no hay histórico diario de tu cartera (se guarda una foto cada día al actualizar precios). "
            "El valor actual está en Cartera."
        )
        return _response(text, [], "portfolio_daily_change")
    previous = db.scalar(
        select(PortfolioDailySnapshot)
        .where(
            PortfolioDailySnapshot.tenant_id == tenant,
            PortfolioDailySnapshot.portfolio_id == latest.portfolio_id,
            PortfolioDailySnapshot.snapshot_date < latest.snapshot_date,
        )
        .order_by(PortfolioDailySnapshot.snapshot_date.desc())
        .limit(1)
    )
    currency = latest.base_currency
    total = float(latest.total_value_base) if latest.total_value_base is not None else None
    day = latest.snapshot_date
    is_today = day == local_today()
    when = (_date_en(day) if english else fecha_es(day))
    sources = [_source("portfolio_snapshot", latest.id, f"Cartera {fecha_es(day)}", "/portfolio")]
    ret = latest.daily_return
    if total is None or ret is None or previous is None or not previous.total_value_base:
        if english:
            lead = f"Today ({when})" if is_today else f"There is no snapshot of your portfolio for today yet. Last saved day ({when})"
            text = (f"{lead}: value {_money(total, currency, english=True)}, but I can't calculate the change: "
                    "there is no comparable previous day (missing prices, a deposit on a day without a snapshot "
                    "or the start of the series).")
        else:
            lead = f"Hoy ({when})" if is_today else f"Aún no hay foto de hoy de tu cartera. El último día guardado ({when})"
            text = (f"{lead}: valor {_money(total, currency)}, pero no puedo calcular la variación: no hay un día "
                    "anterior comparable (faltan precios, una aportación en un día sin foto o es el inicio de la serie).")
        return _response(text, sources, "portfolio_daily_change")
    fraction = float(ret)
    amount = float(Decimal(ret) * previous.total_value_base)
    prev_when = _date_en(previous.snapshot_date) if english else fecha_es(previous.snapshot_date)
    flow = float(latest.net_external_flow_base or 0)
    if english:
        verb = "is up" if fraction > 0 else ("is down" if fraction < 0 else "is flat")
        if is_today:
            head = f"Today ({when}) your portfolio {verb}"
        else:
            head = f"There is no snapshot of your portfolio for today yet. On the last saved day ({when}) it {verb.split()[-1]}"
        text = (f"{head} {_pct(fraction, signed=True, english=True)} "
                f"({_money(amount, currency, signed=True, english=True)}) versus {prev_when}: "
                f"value {_money(total, currency, english=True)}.")
        if flow:
            text += f" Deposits/withdrawals of {_money(flow, currency, signed=True, english=True)} are excluded."
        text += " Saved snapshot, not a live quote."
    else:
        verb = "sube" if fraction > 0 else ("baja" if fraction < 0 else "se queda igual")
        if is_today:
            head = f"Hoy ({when}) tu cartera {verb}"
        else:
            past = {"sube": "subió", "baja": "bajó"}.get(verb, "se quedó igual")
            head = f"Aún no hay foto de hoy de tu cartera. El último día guardado ({when}) {past}"
        text = (f"{head} {_pct(fraction, signed=True)} ({_money(amount, currency, signed=True)}) "
                f"frente al {prev_when}: valor {_money(total, currency)}.")
        if flow:
            text += f" No cuenta aportaciones/retiradas de {_money(flow, currency, signed=True)}."
        text += " Foto guardada, no cotización en directo."
    coverage = float(latest.pricing_coverage or 0)
    if coverage < 1:
        text += (f" Only {_num_en(coverage * 100, 0)}% of positions had a price." if english
                 else f" Solo el {num_es(coverage * 100, 0)} % de las posiciones tenía precio.")
    return _response(text, sources, "portfolio_daily_change")


# ------------------------------------------------------ ganado / vendido en el año

_YEAR_EXPR = r"(?:este\s+ano|en\s+lo\s+que\s+va\s+de\s+ano|este\s+ejercicio|(?:en|de|del?\s+ano)\s+(?:19|20)\d\d|this\s+year|so\s+far\s+this\s+year|year\s+to\s+date|ytd|in\s+(?:19|20)\d\d)"
_YEAR_GAINS = re.compile(
    r"\b(?:cuanto\s+(?:he|hemos|llevo|llevamos)\s+(?:ganado|perdido)|cuanto\s+(?:gane|perdi)"
    r"|how\s+much\s+(?:have\s+i|did\s+i)\s+(?:made|make|earned|earn|gained|gain|lost|lose))\b"
)
_SALES = re.compile(
    r"\b(?:que\s+(?:he\s+|hemos\s+)?(?:vendido|vendi|vendimos)|mis\s+ventas|ventas\s+(?:de|del)\s+(?:este|mi)"
    r"|plusvalias?\s+(?:he\s+)?realizadas?|(?:he|hemos)\s+realizado|ganancias?\s+realizadas?"
    r"|what\s+(?:did\s+i\s+sell|have\s+i\s+sold)|my\s+sales|realized\s+gains?)\b"
)
_TICKER_TOKEN = re.compile(r"\b[A-Z][A-Z0-9.]{0,5}\b")
_NOT_TICKERS = {"IRPF", "EUR", "USD", "DCA", "ETF", "YTD", "I", "A", "Y", "O"}


def _asked_year(text: str) -> int | None:
    """Año pedido: «en 2025» o «este año» (Madrid). None si la frase no habla de un año."""
    if not re.search(_YEAR_EXPR, text):
        return None
    explicit = re.search(r"\b((?:19|20)\d\d)\b", text)
    return int(explicit.group(1)) if explicit else local_today().year


def _tickers_in(question: str) -> set[str]:
    return {t for t in _TICKER_TOKEN.findall(question or "") if t not in _NOT_TICKERS}


def _tax_data(db: Session, year: int) -> dict | None:
    from app.services.tax_report_service import TaxReportService

    try:
        # En memoria: el mismo FIFO del informe fiscal con tus operaciones de
        # ahora (un informe guardado hace días no llevaría la última venta).
        return TaxReportService().compute_report(db, year, include_filing=False)
    except Exception:  # noqa: BLE001 - el informe nunca rompe el chat
        db.rollback()
        return None


def _fdate(value: str, english: bool) -> str:
    from datetime import date

    day = date.fromisoformat(value)
    return _date_en(day) if english else fecha_es(day)


def _qty(value: float, english: bool) -> str:
    if float(value).is_integer():
        return _num_en(value, 0) if english else num_es(value, 0)
    return f"{value:,.4f}".rstrip("0").rstrip(".") if english else num_es(value, 4).rstrip("0").rstrip(",")


def _unrealized(db: Session, tenant: int) -> tuple[float, float, str, object] | None:
    """(ganancia latente, coste, divisa, fecha) de las posiciones abiertas, en su divisa base."""
    from app.models import Position

    rows = list(db.scalars(select(Position).where(Position.tenant_id == tenant, Position.quantity > 0)))
    known = [p for p in rows if p.market_value_base is not None and p.cost_basis_base is not None]
    currencies = {p.base_currency or "EUR" for p in known}
    if not known or len(currencies) != 1:
        return None
    cost = sum(float(p.cost_basis_base) for p in known)
    value = sum(float(p.market_value_base) for p in known)
    if cost <= 0:
        return None
    return value - cost, cost, currencies.pop(), max(p.as_of for p in known)


def _year_gains_answer(db: Session, tenant: int, year: int) -> ChatResponse:
    english = _english()
    today = local_today()
    data = _tax_data(db, year)
    sources = [_source("tax_report", year, f"Informe fiscal {year}", "/taxes")]
    if year > today.year:
        text = (f"{year} hasn't started yet: there are no gains to report." if english
                else f"{year} aún no ha empezado: no hay ganancias que contar.")
        return _response(text, [], "account_year_gains")
    if english:
        head = f"In {year} (to {_date_en(today)}):" if year == today.year else f"In {year}:"
    else:
        head = f"En {year} (hasta el {fecha_es(today)}):" if year == today.year else f"En {year}:"
    lines = [head]
    if data is None:
        lines.append("- I couldn't calculate your sales and dividends right now (tax report)." if english
                     else "- No he podido calcular ahora tus ventas y dividendos (informe fiscal).")
    else:
        summary = data.get("summary") or {}
        realized = [b for b in data.get("realized") or [] if b.get("sale_count")]
        gain = summary.get("total_realized_gain_base")
        names = ", ".join(b["ticker"] for b in realized[:8]) + ("…" if len(realized) > 8 else "")
        count = sum(b["sale_count"] for b in realized)
        if not realized:
            lines.append("- Realized from sales: nothing, no sales recorded." if english
                         else "- Realizado con ventas: nada, no hay ventas guardadas.")
        elif gain is None:
            lines.append(f"- Realized from sales ({names}): no reliable figure (see Taxes for the warning)." if english
                         else f"- Realizado con ventas ({names}): sin dato fiable (el aviso está en Impuestos).")
        else:
            noun = ("sale" if count == 1 else "sales") if english else ("venta" if count == 1 else "ventas")
            lines.append(f"- Realized from sales: {_money(gain, 'EUR', signed=True, english=english)} ({count} {noun}: {names})."
                         if english else
                         f"- Realizado con ventas: {_money(gain, 'EUR', signed=True)} ({count} {noun}: {names}).")
        gross = summary.get("total_dividends_base")
        withheld = summary.get("total_withholding_base")
        if gross is None:
            lines.append("- Dividends received: no reliable figure." if english
                         else "- Dividendos cobrados: sin dato fiable.")
        elif gross:
            lines.append(
                f"- Dividends received: {_money(gross, 'EUR', english=True)} gross, "
                f"{_money(withheld, 'EUR', english=True)} withheld at source." if english else
                f"- Dividendos cobrados: {_money(gross, 'EUR')} brutos, "
                f"{_money(withheld, 'EUR')} de retención en origen.")
    if year == today.year:
        latent = _unrealized(db, tenant)
        if latent is not None:
            amount, cost, currency, as_of = latent
            day = _date_en(as_of) if english else fecha_es(as_of)
            lines.append(
                f"- Unrealized (still open, not sold): {_money(amount, currency, signed=True, english=True)} "
                f"({_pct(amount / cost, signed=True, english=True)}) on a cost of {_money(cost, currency, english=True)}, "
                f"data as of {day}; this is the total since purchase, not just this year." if english else
                f"- Latente (lo que sigue abierto, no vendido): {_money(amount, currency, signed=True)} "
                f"({_pct(amount / cost, signed=True)}) sobre un coste de {_money(cost, currency)}, "
                f"con datos a {day}; es desde la compra, no solo de este año.")
            sources.append(_source("position", None, "Posiciones abiertas", "/portfolio"))
            lines.append("They are not added up: the unrealized part isn't a gain until you sell." if english
                         else "No se suman: lo latente no es ganancia hasta que vendes.")
    lines.append("Realized and dividends in euros, as in the tax report (draft, not tax advice)." if english
                 else "Realizado y dividendos en euros, como en el informe fiscal (borrador, no asesoría fiscal).")
    return _response("\n".join(lines), sources, "account_year_gains")


def _sales_answer(db: Session, year: int, only: set[str]) -> ChatResponse:
    english = _english()
    data = _tax_data(db, year)
    sources = [_source("tax_report", year, f"Informe fiscal {year}", "/taxes")]
    if data is None:
        text = ("I couldn't read your sales right now; they're in Taxes." if english
                else "No he podido leer tus ventas ahora; están en Impuestos.")
        return _response(text, sources, "account_sales")
    realized = [b for b in data.get("realized") or [] if b.get("sale_count")]
    if only:
        realized = [b for b in realized if b["ticker"] in only] or realized
    if not realized:
        text = (f"In {year} there are no sales in your saved trades." if english
                else f"En {year} no hay ventas en tus operaciones guardadas.")
        return _response(text, sources, "account_sales")
    lines = [f"In {year} you sold:" if english else f"En {year} vendiste:"]
    shown = 0
    for bucket in realized:
        for sale in bucket.get("sales") or []:
            if shown >= 20:
                break
            shown += 1
            qty = _qty(float(sale["quantity"]), english)
            proceeds = sale.get("proceeds_base")
            gain = sale.get("gain_base")
            if english:
                line = f"- {bucket['ticker']}: {qty} shares on {_fdate(sale['date'], True)}"
                line += f", for {_money(proceeds, 'EUR', english=True)}" if proceeds is not None else ""
                line += f"; gain {_money(gain, 'EUR', signed=True, english=True)}" if gain is not None else "; gain: no reliable figure"
            else:
                line = f"- {bucket['ticker']}: {qty} acciones el {_fdate(sale['date'], False)}"
                line += f", por {_money(proceeds, 'EUR')}" if proceeds is not None else ""
                line += f"; ganancia {_money(gain, 'EUR', signed=True)}" if gain is not None else "; ganancia: sin dato fiable"
            lines.append(line + ".")
    total = sum(float(b["gain_base"]) for b in realized if b.get("gain_base") is not None)
    reliable = all(b.get("gain_base") is not None for b in realized)
    if reliable:
        lines.append(f"Total realized: {_money(total, 'EUR', signed=True, english=True)}." if english
                     else f"Total realizado: {_money(total, 'EUR', signed=True)}.")
    lines.append("FIFO in euros, as in Taxes (draft, not tax advice)." if english
                 else "FIFO en euros, como en Impuestos (borrador, no asesoría fiscal).")
    return _response("\n".join(lines), sources, "account_sales")


# ------------------------------------------------------------ IRPF si vendo todo

_SELL_ALL_ES = re.compile(
    r"\b(?:vend\w*|liquid\w*)\s+(?:lo\s+|la\s+)?(?:todo|toda\s+(?:mi|la)\s+cartera|todas?\s+(?:mis|las)\s+(?:posiciones|acciones)"
    r"|(?:mi|la)\s+cartera\s+entera|la\s+cartera|mi\s+cartera)\b"
    r"|\blo\s+vend\w*\s+todo\b"
)
_SELL_ALL_EN = re.compile(r"\b(?:sell|sold|selling)\s+(?:everything|it\s+all|all\s+(?:of\s+)?my|my\s+(?:whole|entire)\s+portfolio)\b")
_TAX_WORD = re.compile(r"\b(?:irpf|impuestos?|hacienda|tributar\w*|tax(?:es)?)\b")


def _asks_sell_all_tax(text: str, question: str) -> bool:
    return bool(_TAX_WORD.search(text) and (_SELL_ALL_ES.search(text) or _SELL_ALL_EN.search(text))
                and not _tickers_in(question))


def _sell_all_answer(db: Session, tenant: int) -> ChatResponse:
    from app.models import Company, Position
    from app.services.chat_service import _savings_scale_label
    from app.services.sale_simulation import simulate_fifo_sale
    from app.services.tax_irpf_filing import calculate_savings_tax
    from app.valuation.currency import canonical_currency_code

    english = _english()
    today = local_today()
    rows = list(db.execute(
        select(Position, Company).join(Company, Company.id == Position.company_id)
        .where(Position.tenant_id == tenant, Position.quantity > 0)
        .order_by(Company.ticker)
    ).all())
    if not rows:
        text = ("You have no open positions saved, so there is nothing to sell." if english
                else "No tienes posiciones abiertas guardadas: no hay nada que vender.")
        return _response(text, [], "account_sell_all_tax")
    items: list[tuple[str, Decimal, Decimal]] = []
    missing: list[str] = []
    average: list[str] = []
    for pos, company in rows:
        held = Decimal(pos.quantity)
        value = pos.market_value_base if (pos.base_currency or "EUR") == "EUR" else None
        currency = canonical_currency_code(pos.currency or company.currency or "EUR")
        native = pos.market_value_native if pos.market_value_native is not None else pos.market_value
        rate: Decimal | None = None
        if currency == "EUR":
            rate = Decimal("1")
        elif value is not None and native:
            rate = Decimal(value) / Decimal(native)
        fifo = simulate_fifo_sale(db, tenant_id=tenant, company_id=company.id, quantity=held,
                                  held_quantity=held, sale_date=today)
        cost = fifo.cost_eur_dgt(currency, rate) if fifo is not None else None
        if cost is None and (pos.base_currency or "EUR") == "EUR" and pos.cost_basis_base is not None:
            cost = Decimal(pos.cost_basis_base)
            average.append(company.ticker)
        if value is None or cost is None:
            missing.append(company.ticker)
            continue
        items.append((company.ticker, Decimal(value), Decimal(cost)))
    if not items:
        text = ("I can't estimate it: your positions have no value or cost in euros saved (Hacienda works in euros)."
                if english else
                "No puedo estimarlo: tus posiciones no tienen valor o coste en euros guardado (Hacienda calcula en euros).")
        return _response(text, [_source("position", None, "Posiciones abiertas", "/portfolio")], "account_sell_all_tax")
    value = sum((v for _t, v, _c in items), Decimal("0"))
    cost = sum((c for _t, _v, c in items), Decimal("0"))
    gain = value - cost
    as_of = max(pos.as_of for pos, _c in rows)
    day = _date_en(as_of) if english else fecha_es(as_of)

    def eur(amount, signed=False):
        return _money(float(amount), "EUR", signed=signed, english=english)

    if english:
        lines = [f"If you sold all {len(items)} positions today (data as of {day}): value {eur(value)}, "
                 f"cost {eur(cost)} (FIFO), net {'gain' if gain >= 0 else 'loss'} {eur(abs(gain))}."]
    else:
        lines = [f"Si vendieras hoy tus {len(items)} posiciones (datos a {day}): valor {eur(value)}, "
                 f"coste {eur(cost)} (FIFO), {'ganancia' if gain >= 0 else 'pérdida'} neta de {eur(abs(gain))}."]
    ranked = sorted(items, key=lambda item: item[1] - item[2], reverse=True)
    for ticker, v, c in ranked[:12]:
        lines.append(f"- {ticker}: {eur(v - c, signed=True)}")
    if len(ranked) > 12:
        lines.append(f"- … and {len(ranked) - 12} more" if english else f"- … y {len(ranked) - 12} más")
    year = today.year
    if gain > 0:
        tax = calculate_savings_tax(gain, year)
        pct = _pct(float(tax / gain), english=english)
        lines.append(
            f"Estimated IRPF (Spanish income tax): {eur(tax)} ({pct} of the gain), "
            f"{min(year, 2025)} savings scale{' (latest verified)' if year > 2025 else ''}, "
            "as if it were your only sale this year. Gains and losses offset each other."
            if english else
            f"IRPF estimado: {eur(tax)} (un {pct} de la ganancia), {_savings_scale_label(year)}, "
            "como si fuera tu única operación del año. Ganancias y pérdidas se compensan entre sí.")
    else:
        lines.append("You would pay no IRPF on it: the net result is a loss, which offsets other gains this year."
                     if english else
                     "No pagarías IRPF por ello: el resultado neto es pérdida, que compensa otras ganancias del año.")
    data = _tax_data(db, year)
    realized = ((data or {}).get("summary") or {}).get("total_realized_gain_base")
    if realized:
        base = gain + Decimal(str(realized))
        both = calculate_savings_tax(base, year)
        lines.append(
            f"You've already realized {eur(realized, signed=True)} in {year}: adding it, the base would be "
            f"{eur(base, signed=True)} and the IRPF {eur(both)}." if english else
            f"En {year} ya llevas {eur(realized, signed=True)} realizado: sumándolo, la base sería "
            f"{eur(base, signed=True)} y el IRPF {eur(both)}.")
    if average:
        lines.append(("Average cost, no FIFO lots: " if english else "Con coste medio, sin lotes FIFO: ")
                     + ", ".join(average[:10]) + ".")
    if missing:
        lines.append(("Left out (no value or cost in euros): " if english else "Fuera del cálculo (sin valor o coste en euros): ")
                     + ", ".join(missing[:10]) + ".")
    lines.append("I don't place orders: you sell at your broker and record it in Portfolio. Draft, not tax advice."
                 if english else
                 "No ejecuto ventas: se vende en tu bróker y se registra en Cartera. Borrador, no asesoría fiscal.")
    sources = [_source("position", None, "Posiciones abiertas", "/portfolio"),
               _source("tax_report", year, f"Informe fiscal {year}", "/taxes")]
    return _response("\n".join(lines), sources, "account_sell_all_tax")


# ------------------------------------------------------------ comisiones y efectivo

_FEES = re.compile(
    r"\b(?:comision\w*|gastos\s+de\s+(?:compraventa|corretaje|broker)|corretaje)\b"
    r"|\b(?:fees|commissions?)\b"
)
_FEES_ASK = re.compile(r"\b(?:cuant\w*|cuales|mis|pagad\w*|pago|pague|total|how\s+much|my|paid|pay)\b")
_CASH = re.compile(r"\b(?:efectivo|liquidez|caja|saldo|cash)\b")
_CASH_ASK = re.compile(r"\b(?:cuant\w*|tengo|mi|mis|how\s+much|my|do\s+i\s+have)\b")
_CASH_NOT = re.compile(r"flujo\s+de\s+caja|caja\s+libre|cash\s*flow|fcf|caja\s+neta\s+de|cash\s+per\s+share")


def _asks_fees(text: str) -> bool:
    return bool(_FEES.search(text) and _FEES_ASK.search(text)
                and not re.search(r"\bsi\b|\bif\b|\bcobra\w*|\bcharges?\b|\bter\b", text))


def _asks_cash(text: str, question: str) -> bool:
    return bool(_CASH.search(text) and _CASH_ASK.search(text) and not _CASH_NOT.search(text)
                and not _tickers_in(question))


def _fees_answer(db: Session, tenant: int, year: int | None, only: set[str]) -> ChatResponse:
    from datetime import date

    from app.models import Company, Transaction

    english = _english()
    query = (select(Transaction, Company.ticker).outerjoin(Company, Company.id == Transaction.company_id)
             .where(Transaction.tenant_id == tenant))
    if year is not None:
        query = query.where(Transaction.trade_date >= date(year, 1, 1), Transaction.trade_date <= date(year, 12, 31))
    trade: dict[str, Decimal] = {}
    other: dict[str, Decimal] = {}
    by_ticker: dict[str, Decimal] = {}
    count = 0
    for tx, ticker in db.execute(query).all():
        if only and (ticker or "") not in only:
            continue
        action = (tx.action or "").lower()
        currency = (tx.currency or "EUR").upper()
        if action in {"buy", "sell"} and tx.fees:
            amount = abs(Decimal(tx.fees))
            trade[currency] = trade.get(currency, Decimal("0")) + amount
            key = f"{ticker or '?'}|{currency}"
            by_ticker[key] = by_ticker.get(key, Decimal("0")) + amount
            count += 1
        elif action == "fee":
            from app.services.tax_report_service import cash_amount

            other[currency] = other.get(currency, Decimal("0")) + abs(cash_amount(tx))

    def amounts(totals: dict[str, Decimal]) -> str:
        return " + ".join(_money(float(v), c, english=english) for c, v in sorted(totals.items()))

    period = (f"in {year}" if english else f"en {year}") if year is not None else (
        "in total" if english else "en total")
    sources = [_source("transactions", None, "Operaciones", "/portfolio")]
    if not trade and not other:
        text = (f"No commissions recorded {period} in your saved trades." if english
                else f"No hay comisiones {period} en tus operaciones guardadas.")
        return _response(text, sources, "account_fees")
    lines: list[str] = []
    if trade:
        noun = ("trade" if count == 1 else "trades") if english else ("operación" if count == 1 else "operaciones")
        lines.append(f"Commissions on buys and sells {period}: {amounts(trade)} ({count} {noun})." if english
                     else f"Comisiones de compraventa {period}: {amounts(trade)} ({count} {noun}).")
        top = sorted(by_ticker.items(), key=lambda kv: kv[1], reverse=True)[:5]
        if len(by_ticker) > 1:
            lines.append(("Most: " if english else "Más: ") + ", ".join(
                f"{key.split('|')[0]} {_money(float(v), key.split('|')[1], english=english)}" for key, v in top) + ".")
    if other:
        lines.append(f"Other broker fees (fee rows): {amounts(other)}." if english
                     else f"Otros cargos del bróker (filas de comisión): {amounts(other)}.")
    lines.append("In each trade's currency, from your saved trades." if english
                 else "En la divisa de cada operación, de tus operaciones guardadas.")
    return _response("\n".join(lines), sources, "account_fees")


def _cash_answer(db: Session, tenant: int) -> ChatResponse:
    from app.models import CashBalance

    english = _english()
    rows = list(db.scalars(select(CashBalance).where(CashBalance.tenant_id == tenant)
                           .order_by(CashBalance.currency)))
    if not rows:
        text = ("You have no cash balance saved. You can add it in Portfolio." if english
                else "No tienes efectivo guardado. Puedes añadirlo en Cartera.")
        return _response(text, [], "account_cash")
    totals: dict[str, Decimal | None] = {}
    for row in rows:
        known = totals.get(row.currency, Decimal("0"))
        totals[row.currency] = None if known is None or row.balance is None else known + Decimal(row.balance)
    as_of = max(row.as_of for row in rows)
    day = _date_en(as_of) if english else fecha_es(as_of)
    parts = [_money(float(v) if v is not None else None, c, english=english) for c, v in sorted(totals.items())]
    text = (f"Your saved cash (as of {day}): " if english else f"Tu efectivo guardado (a {day}): ") + ", ".join(parts) + "."
    if any(v is not None and v < 0 for v in totals.values()):
        text += (" A negative balance is margin debt." if english else " Un saldo negativo es deuda de margen.")
    if len(totals) > 1:
        text += (" Each currency is shown as is, not converted." if english
                 else " Cada divisa va tal cual, sin convertir.")
    return _response(text, [_source("cash_balance", rows[0].id, "Efectivo", "/portfolio")], "account_cash")


# ------------------------------------------------------------ ranking por rentabilidad

_RANK_RETURN = re.compile(
    r"\b(?:mi|mis)\s+(?:mejor|peor)(?:es)?\s+(?:posicion|accion|inversion|valor)"
    r"|\b(?:posicion|accion|inversion|valor)(?:es)?\s+(?:de\s+mi\s+cartera\s+)?(?:que\s+)?(?:va|van|me\s+va|esta|estan|lleva|llevan)\s+(?:peor|mejor)"
    r"|\b(?:ranking|ordena\w*|clasifica\w*)\b.*\brentab"
    r"|\bme\s+da\w*\s+(?:mas|menos)\s+rentab|\b(?:mas|menos)\s+rentables?\s+de\s+(?:mi|la)\s+cartera"
    r"|\b(?:best|worst)[- ]performing\b|\bmy\s+(?:best|worst)\s+(?:position|stock|holding|investment)"
    r"|\bwhich\s+(?:position|stock|holding)\s+is\s+(?:doing\s+)?(?:best|worst)"
)


def _asks_return_ranking(text: str, question: str) -> bool:
    return bool(_RANK_RETURN.search(text)) and not _tickers_in(question)


def _ranking_answer(db: Session, tenant: int, text: str) -> ChatResponse:
    from app.models import Company, Position

    english = _english()
    rows = list(db.execute(
        select(Position, Company.ticker).join(Company, Company.id == Position.company_id)
        .where(Position.tenant_id == tenant, Position.quantity > 0)
    ).all())
    known = [(t, float(p.market_value_base), float(p.cost_basis_base), p.base_currency or "EUR", p.as_of)
             for p, t in rows
             if p.market_value_base is not None and p.cost_basis_base is not None and p.cost_basis_base > 0]
    unknown = sorted(t for p, t in rows if not any(k[0] == t for k in known))
    if not known:
        text_out = ("You have no open positions with a saved value and cost, so I can't rank them." if english
                    else "No tienes posiciones abiertas con valor y coste guardados: no puedo ordenarlas.")
        return _response(text_out, [], "account_return_ranking")
    ranked = sorted(known, key=lambda k: (k[1] - k[2]) / k[2], reverse=True)
    worst_first = bool(re.search(r"\b(?:peor|menos|worst)\b", text))

    def line(item) -> str:
        ticker, value, cost, currency, _as_of = item
        return (f"{ticker} {_pct((value - cost) / cost, signed=True, english=english)} "
                f"({_money(value - cost, currency, signed=True, english=english)})")

    lead = ranked[-1] if worst_first else ranked[0]
    as_of = max(k[4] for k in known)
    day = _date_en(as_of) if english else fecha_es(as_of)
    if english:
        head = f"{'Worst' if worst_first else 'Best'} return on cost: {line(lead)}."
        lines = [head, f"All your positions by return on purchase cost (data as of {day}):"]
    else:
        head = f"La que {'peor' if worst_first else 'mejor'} va sobre su coste: {line(lead)}."
        lines = [head, f"Todas tus posiciones por rentabilidad sobre el coste de compra (datos a {day}):"]
    order = list(reversed(ranked)) if worst_first else ranked
    lines += [f"{i}. {line(item)}" for i, item in enumerate(order[:15], 1)]
    if len(order) > 15:
        lines.append(f"… and {len(order) - 15} more" if english else f"… y {len(order) - 15} más")
    if unknown:
        lines.append(("No saved cost or value, left out: " if english else "Sin coste o valor guardado, fuera: ")
                     + ", ".join(unknown[:10]) + ".")
    lines.append("Simple return since purchase, without dividends." if english
                 else "Rentabilidad simple desde la compra, sin dividendos.")
    return _response("\n".join(lines), [_source("position", None, "Posiciones abiertas", "/portfolio")],
                     "account_return_ranking")


# ------------------------------------------------------------------ router


_WITHHOLD = re.compile(r"\b(?:retencion\w*|retenid\w*|retuvi\w*|retien\w*|withh\w+)\b")
_MINE = re.compile(r"\b(?:me|mis|mi|my|i)\b")


def _asks_withholding(text: str) -> bool:
    return bool(_WITHHOLD.search(text) and _MINE.search(text) and not re.search(r"\bsi\b|\bif\b", text))


def _withholding_years(db: Session, tenant: int, only: set[str]) -> list[int]:
    from app.models import Company, Transaction

    query = (select(Transaction.trade_date, Transaction.action, Company.ticker)
             .outerjoin(Company, Company.id == Transaction.company_id).where(Transaction.tenant_id == tenant))
    years: set[int] = set()
    for day, action, ticker in db.execute(query).all():
        action = (action or "").lower()
        if day is None or (only and (ticker or "") not in only):
            continue
        if "dividend" in action or "withholding" in action or action in {"div", "tax"}:
            years.add(day.year)
    return sorted(years, reverse=True)


def _withholding_answer(db: Session, tenant: int, year: int | None, only: set[str]) -> ChatResponse:
    english = _english()
    years = [year] if year is not None else _withholding_years(db, tenant, only)
    # (año o ticker, divisa) -> [retenido, bruto]
    rows: dict[tuple[str, str], list[Decimal | None]] = {}
    for current in years:
        report = _tax_data(db, current) or {}
        for item in report.get("dividends") or []:
            ticker = item.get("ticker") or "?"
            if only and ticker not in only:
                continue
            key = (ticker if year is not None else str(current), (item.get("currency") or "EUR").upper())
            bucket = rows.setdefault(key, [Decimal("0"), Decimal("0")])
            for index, field in enumerate(("withholding_native", "dividends_native")):
                value = item.get(field)
                known = bucket[index]
                bucket[index] = None if known is None or value is None else known + Decimal(str(value))
    sources = [_source("tax_report", None, "Impuestos", "/taxes")]

    names = ", ".join(sorted(only))
    if not rows:
        what = names or (str(year) if year is not None else "")
        if english:
            text = f"You have no saved dividends or withholding{' for ' + what if what else ''}."
        else:
            text = f"No tienes dividendos ni retenciones guardados{' de ' + what if names else (' en ' + what if what else '')}."
        return _response(text, sources, "account_withholding")
    totals: dict[str, list[Decimal | None]] = {}
    for (_, currency), (held, gross) in rows.items():
        total = totals.setdefault(currency, [Decimal("0"), Decimal("0")])
        for index, value in enumerate((held, gross)):
            known = total[index]
            total[index] = None if known is None or value is None else known + value

    def part(held: Decimal | None, gross: Decimal | None, currency: str) -> str:
        on = "on" if english else "sobre"
        return f"{_money(float(held) if held is not None else None, currency, english=english)} {on} {_money(float(gross) if gross is not None else None, currency, english=english)}"

    def rate(held: Decimal | None, gross: Decimal | None) -> str:
        return f" ({_pct(float(held / gross), english=english)})" if held is not None and gross is not None and gross > 0 else ""

    head = " + ".join(f"{part(h, g, c)} {'gross' if english else 'brutos'}{rate(h, g)}" for c, (h, g) in sorted(totals.items()))
    if names:
        scope = f"your {names} dividends" if english else f"tus dividendos de {names}"
        if year is not None:
            scope += f" in {year}" if english else f" en {year}"
    else:
        scope = (f"your dividends in {year}" if year is not None else "your dividends") if english else (
            f"tus dividendos en {year}" if year is not None else "tus dividendos")
    lines = [f"Tax withheld at source on {scope}: {head}." if english else f"Retención en origen en {scope}: {head}."]
    if len(rows) > 1:
        for (label, currency), (held, gross) in sorted(rows.items(), key=lambda kv: kv[0], reverse=year is None):
            lines.append(f"- {label}: {part(held, gross, currency)}{rate(held, gross)}")
    lines.append("From your saved dividends, as in Taxes (draft, not tax advice)." if english
                 else "De tus dividendos guardados, como en Impuestos (borrador, no asesoría fiscal).")
    return _response("\n".join(lines), sources, "account_withholding")


_PLAN = re.compile(
    r"\bplan(?:es)?\s+(?:de\s+)?(?:aportacion\w*|inversion\w*|dca)\b|\bmis?\s+aportaciones\b"
    r"|\bcuanto\s+(?:he\s+)?aportado\b|\bvoy\s+al\s+dia\s+con\s+mi\s+plan\b|\b(?:cual|como)\s+(?:es|va)\s+mi\s+plan\b"
    r"|\b(?:investment|contribution|dca)\s+plans?\b|\bhow\s+much\s+have\s+i\s+contributed\b|\bmy\s+plan\b"
)
_PLAN_NOT = re.compile(r"\bpensiones\b|\bque\s+compro\b|\bsegun\s+mi\s+plan\b|\bwhat\s+(?:should\s+i|to)\s+buy\b")


def _asks_plan(text: str, question: str) -> bool:
    return bool(_PLAN.search(text) and not _PLAN_NOT.search(text) and re.search(r"\b(?:mi|mis|my)\b", text)
                and not _tickers_in(question))


def _plan_answer(db: Session, tenant: int, text: str) -> ChatResponse:
    from datetime import date

    from app.models import InvestmentPlan
    from app.services.investment_plan_service import InvestmentPlanService

    english = _english()
    sources = [_source("investment_plan", None, "Plan", "/plan")]
    has_plan = db.scalar(select(InvestmentPlan.id).where(InvestmentPlan.tenant_id == tenant).limit(1))
    metrics = InvestmentPlanService().plan_metrics(db, today=local_today()) if has_plan else {}
    if not metrics.get("plan_exists"):
        text_out = ("You have no saved contribution plan. You can create one in Plan." if english
                    else "No tienes un plan de aportación guardado. Puedes crearlo en Plan.")
        return _response(text_out, sources, "account_plan")
    base = metrics.get("base_currency")
    monthly = _money(float(metrics["monthly_contribution"]), metrics.get("monthly_contribution_currency") or base,
                     english=english)
    start = date.fromisoformat(metrics["start_date"])
    years = metrics.get("horizon_years")
    if english:
        lines = [f"Your contribution plan: {monthly} a month since {_date_en(start)}, over {years} years."]
    else:
        lines = [f"Tu plan de aportación: {monthly} al mes desde el {fecha_es(start)}, a {years} años."]
    actual, expected = metrics.get("actual_contributions_base"), metrics.get("expected_contributions_base")
    months = metrics.get("months_elapsed") or 0
    if actual is not None and expected is not None:
        gap = float(metrics.get("gap_base") or 0)
        done = _money(float(actual), base, english=english)
        due = _money(float(expected), base, english=english)
        if english:
            state = (f"{_money(gap, base, english=True)} behind" if gap > 0 else
                     f"{_money(-gap, base, english=True)} ahead" if gap < 0 else "on track")
            lines.append(f"Contributed: {done} of {due} expected so far ({months} months); {state}.")
        else:
            state = (f"vas {_money(gap, base)} por detrás" if gap > 0 else
                     f"vas {_money(-gap, base)} por delante" if gap < 0 else "vas al día")
            lines.append(f"Aportado: {done} de {due} previstos hasta hoy ({months} meses); {state}.")
    else:
        lines.append("Contributed vs expected: unknown (missing currency or FX), see Plan." if english
                     else "Aportado frente a previsto: sin dato (falta divisa o tipo de cambio), míralo en Plan.")
    targets = [t for t in metrics.get("target_allocations") or [] if str(t.get("label") or "").strip()]
    if targets:
        parts = ", ".join(
            f"{t['label']} {float(t.get('target_pct') or 0):g}%" if english
            else f"{t['label']} {float(t.get('target_pct') or 0):g} %".replace(".", ",") for t in targets)
        lines.append(f"Target split: {parts}." if english else f"Reparto objetivo: {parts}.")
    if re.search(r"\bdca\b", text):
        from app.services.brain_context_tools import dca_answer

        levels = dca_answer(db, tenant, None)
        lines.append(levels.answer)
        sources += levels.sources
    lines.append("To change it, go to Plan." if english else "Para cambiarlo, ve a Plan.")
    return _response("\n".join(lines), sources, "account_plan")


_N_WORDS = {"un": 1, "una": 1, "a": 1, "one": 1, "dos": 2, "two": 2, "tres": 3, "three": 3, "seis": 6, "six": 6}
_HIST_AGO = re.compile(
    r"\bhace\s+(un|una|dos|tres|seis|\d+)\s+(dias?|semanas?|mes|meses|anos?)\b"
    r"|\b(?:el|los|la|las)\s+ultim[oa]s?\s+(?:(\d+|dos|tres|seis)\s+)?(dias?|semanas?|mes|meses)\b"
    r"|\b(a|one|two|three|six|\d+)\s+(days?|weeks?|months?|years?)\s+ago\b"
    r"|\b(?:the\s+)?(?:last|past)\s+(?:(\d+|two|three|six)\s+)?(days?|weeks?|months?)\b"
)
_HIST_THIS = re.compile(r"\b(?:est[ae]|this)\s+(semana|mes|week|month)\b")
_HIST_VERB = re.compile(r"\b(?:valia|subido|bajado|ido|evolucion\w*|variado|cambiado|rentabilidad|ganado|perdido|"
                        r"worth|done|changed|gone|grown|evolved|return|gained|lost|up|down)\b")
_UNIT = {"dia": "d", "dias": "d", "day": "d", "days": "d", "semana": "w", "semanas": "w", "week": "w", "weeks": "w",
         "mes": "m", "meses": "m", "month": "m", "months": "m", "ano": "y", "anos": "y", "year": "y", "years": "y"}


def _months_back(day, months: int):
    from calendar import monthrange

    year, month = divmod(day.year * 12 + day.month - 1 - months, 12)
    return day.replace(year=year, month=month + 1, day=min(day.day, monthrange(year, month + 1)[1]))


def _history_target(text: str):
    """(fecha de comparación, es_este_periodo) o None si la frase no pide un pasado."""
    from datetime import timedelta

    today = local_today()
    this = _HIST_THIS.search(text)
    if this:
        if this.group(1) in {"semana", "week"}:
            return today - timedelta(days=today.weekday() + 1), True
        return today.replace(day=1) - timedelta(days=1), True
    match = _HIST_AGO.search(text)
    if not match:
        return None
    groups = [g for g in match.groups()]
    pairs = [(groups[i], groups[i + 1]) for i in range(0, len(groups), 2) if groups[i + 1]]
    raw, unit_word = pairs[0]
    count = int(raw) if raw and raw.isdigit() else _N_WORDS.get(raw or "", 1)
    unit = _UNIT.get(unit_word, "d")
    if unit == "d":
        return today - timedelta(days=count), False
    if unit == "w":
        return today - timedelta(days=7 * count), False
    return _months_back(today, count * (12 if unit == "y" else 1)), False


def _asks_history(text: str, question: str) -> bool:
    return bool((_HIST_AGO.search(text) or _HIST_THIS.search(text)) and _PORTFOLIO_WORD.search(text)
                and _HIST_VERB.search(text) and not _tickers_in(question) and not re.search(r"\bsi\b|\bif\b", text))


def _history_answer(db: Session, tenant: int, text: str) -> ChatResponse:
    english = _english()
    target, this_period = _history_target(text) or (local_today(), False)
    when = (lambda day: _date_en(day)) if english else (lambda day: fecha_es(day))
    base = select(PortfolioDailySnapshot).where(PortfolioDailySnapshot.tenant_id == tenant)
    latest = db.scalar(base.order_by(PortfolioDailySnapshot.snapshot_date.desc(),
                                     PortfolioDailySnapshot.id.desc()).limit(1))
    if latest is None:
        return _response(
            "There is no daily history of your portfolio yet (a snapshot is saved each day when prices refresh)."
            if english else
            "Aún no hay histórico diario de tu cartera (se guarda una foto cada día al actualizar precios).",
            [], "portfolio_history")
    same = base.where(PortfolioDailySnapshot.portfolio_id == latest.portfolio_id)
    past = db.scalar(same.where(PortfolioDailySnapshot.snapshot_date <= target)
                     .order_by(PortfolioDailySnapshot.snapshot_date.desc()).limit(1))
    sources = [_source("portfolio_snapshot", latest.id, f"Cartera {fecha_es(latest.snapshot_date)}", "/portfolio")]
    if past is None:
        first = db.scalar(same.order_by(PortfolioDailySnapshot.snapshot_date.asc()).limit(1))
        first_day = when(first.snapshot_date) if first else when(latest.snapshot_date)
        text_out = (f"I have no snapshot of your portfolio on or before {when(target)}: the first one is from {first_day}."
                    if english else
                    f"No tengo foto de tu cartera del {when(target)} ni anterior: la primera es del {first_day}.")
        return _response(text_out, sources, "portfolio_history")
    if past.id == latest.id or past.snapshot_date >= latest.snapshot_date:
        if this_period:
            text_out = (f"There is no snapshot of your portfolio for this period yet (the latest is from "
                        f"{when(latest.snapshot_date)})." if english else
                        f"Aún no hay ninguna foto de tu cartera de este {'mes' if 'mes' in text else 'periodo'} "
                        f"(la última es del {when(latest.snapshot_date)}).")
        else:
            text_out = (f"The latest snapshot of your portfolio is from {when(latest.snapshot_date)}; there is nothing "
                        "newer to compare." if english else
                        f"La última foto de tu cartera es del {when(latest.snapshot_date)}; no hay nada más nuevo con "
                        "que comparar.")
        return _response(text_out, sources, "portfolio_history")
    currency = latest.base_currency
    if latest.total_value_base is None or past.total_value_base is None:
        text_out = ("Portfolio comparison: N/A (a snapshot has an unknown total value)." if english else
                    "Comparación de cartera: N/D (una foto tiene el valor total desconocido).")
        return _response(text_out, sources, "portfolio_history")
    now_value, then_value = float(latest.total_value_base), float(past.total_value_base)
    flows = db.scalars(same.where(PortfolioDailySnapshot.snapshot_date > past.snapshot_date,
                                  PortfolioDailySnapshot.snapshot_date <= latest.snapshot_date)).all()
    flow = (None if any(s.net_external_flow_base is None for s in flows) else
            float(sum((Decimal(s.net_external_flow_base) for s in flows), Decimal("0"))))
    change = now_value - then_value
    m = (lambda value, signed=False: _money(value, currency, signed=signed, english=english))
    if english:
        lines = [f"On {when(past.snapshot_date)} your portfolio was worth {m(then_value)}; in the latest snapshot "
                 f"({when(latest.snapshot_date)}), {m(now_value)}: {m(change, True)}."]
    else:
        lines = [f"El {when(past.snapshot_date)} tu cartera valía {m(then_value)}; en la última foto "
                 f"({when(latest.snapshot_date)}), {m(now_value)}: {m(change, True)}."]
    if flow is None:
        lines.append("Net deposits/withdrawals: N/A; cannot separate cash flows from performance." if english else
                     "Aportaciones/retiradas netas: N/D; no se pueden separar los flujos de la rentabilidad.")
        lines.append("Saved daily snapshots, not live prices." if english else
                     "Fotos diarias guardadas, no cotización en directo.")
        return _response("\n".join(lines), sources, "portfolio_history")
    if latest.cumulative_twr is not None and past.cumulative_twr is not None:
        ret = (1 + float(latest.cumulative_twr)) / (1 + float(past.cumulative_twr)) - 1
        label = "TWR"
    else:
        ret = (change - flow) / then_value if then_value else None
        label = "approx." if english else "aprox."
    pct = f" ({_pct(ret, signed=True, english=english)} {label})" if ret is not None else ""
    if abs(flow) >= 0.005:
        lines.append(f"Net deposits/withdrawals in that time: {m(flow, True)}; without them, {m(change - flow, True)}{pct}."
                     if english else
                     f"Aportaciones/retiradas netas en ese tiempo: {m(flow, True)}; sin ellas, {m(change - flow, True)}{pct}.")
    elif pct:
        lines.append(f"No deposits or withdrawals in that time{pct}." if english
                     else f"Sin aportaciones ni retiradas en ese tiempo{pct}.")
    lines.append("Saved daily snapshots, not live prices." if english
                 else "Fotos diarias guardadas, no cotización en directo.")
    return _response("\n".join(lines), sources, "portfolio_history")


_RULES_ASK = re.compile(
    r"\b(?:que|cuales|cuantas)\s+(?:alertas|avisos)\s+tengo\s+(?:configurad|puest|activ|cread|programad)\w*"
    r"|\bmis\s+reglas\s+de\s+(?:aviso|alerta)s?\b|\blista\w*\s+(?:de\s+)?(?:mis\s+)?(?:alertas|avisos)\b"
    r"|\bmis\s+(?:alertas|avisos)\s+(?:configurad|puest|activ|cread|programad)\w*"
    r"|\bmy\s+alert\s+rules\b|\bwhat\s+alerts\s+(?:do\s+)?i\s+have\b|\blist\s+(?:all\s+)?my\s+alerts\b"
)


def _asks_alert_rules(text: str, question: str) -> bool:
    return bool(_RULES_ASK.search(text) and not _tickers_in(question))


def _rule_text(kind: str, condition: dict, currency: str | None, english: bool) -> str:
    op = str((condition or {}).get("operator") or "")
    raw = (condition or {}).get("value")
    try:
        value = float(str(raw))
        number = _num_en(value, 2).rstrip("0").rstrip(".") if english else num_es(value, 2).rstrip("0").rstrip(",")
    except (TypeError, ValueError):
        value, number = None, str(raw)
    cur = f" {currency}" if currency else ""
    if kind == "price_below" or (kind.startswith("price") and kind != "price_change" and op in {"<", "<="}):
        return f"price below {number}{cur}" if english else f"precio por debajo de {number}{cur}"
    if kind == "price_above" or (kind.startswith("price") and kind != "price_change" and op in {">", ">="}):
        return f"price above {number}{cur}" if english else f"precio por encima de {number}{cur}"
    if kind == "price_change":
        more = op in {">", ">="}
        if english:
            return f"daily change of {number}% or {'more' if more else 'less'}"
        return f"variación del día de {number} % o {'más' if more else 'menos'}"
    if kind in {"news", "news_event"}:
        return "new news" if english else "noticias nuevas"
    if kind in {"earnings", "earnings_run"}:
        return "new earnings" if english else "resultados nuevos"
    return f"{kind} {op} {number}".strip()


def _alert_rules_answer(db: Session, tenant: int) -> ChatResponse:
    from app.models import AlertRule, Company

    english = _english()
    rows = db.execute(
        select(AlertRule, Company.ticker, Company.currency)
        .outerjoin(Company, Company.id == AlertRule.company_id)
        .where(AlertRule.tenant_id == tenant, AlertRule.active.is_(True))
        .order_by(AlertRule.id)
    ).all()
    sources = [_source("alert_rule", None, "Alertas", "/alerts")]
    if not rows:
        return _response("You have no active alerts. You can create them in Alerts." if english
                         else "No tienes alertas activas. Puedes crearlas en Alertas.", sources, "account_alert_rules")
    count = len(rows)
    lines = [(f"You have {count} active alert{'s' if count != 1 else ''}:" if english
              else f"Tienes {count} alerta{'s' if count != 1 else ''} activa{'s' if count != 1 else ''}:")]
    for rule, ticker, currency in rows[:20]:
        line = f"- {ticker or '?'}: {_rule_text(rule.rule_type or '', rule.condition or {}, currency, english)}"
        if rule.last_triggered_at is not None:
            fired = rule.last_triggered_at.date()
            line += (f" (last triggered {_date_en(fired)})" if english
                     else f" (saltó por última vez el {fecha_es(fired)})")
        lines.append(line)
    if count > 20:
        lines.append(f"And {count - 20} more in Alerts." if english else f"Y {count - 20} más en Alertas.")
    lines.append("To create, pause or delete alerts, go to Alerts." if english
                 else "Para crear, pausar o borrar alertas, ve a Alertas.")
    return _response("\n".join(lines), sources, "account_alert_rules")


_SCREENS = re.compile(
    r"\b(?:pantallas|screens?|screeners?|filtros)\s+(?:que\s+tengo\s+)?(?:guardad\w*|del\s+screener|en\s+el\s+screener)"
    r"|\bmis\s+(?:pantallas|screens?|screeners?)\b|\btengo\s+guardad\w+\s+en\s+el\s+screener\b"
    r"|\bmy\s+(?:saved\s+)?screens?\b|\bsaved\s+screens?\b"
)


def _asks_saved_screens(text: str, question: str) -> bool:
    return bool(_SCREENS.search(text) and not _tickers_in(question)
                and (re.search(r"\b(?:mis|mi|tengo|my|i)\b", text)))


def _saved_screens_answer(db: Session, tenant: int) -> ChatResponse:
    from app.models import Company, SavedScreen, SavedScreenMatch

    english = _english()
    screens = db.scalars(select(SavedScreen).where(SavedScreen.tenant_id == tenant, SavedScreen.active.is_(True))
                         .order_by(SavedScreen.id)).all()
    sources = [_source("saved_screen", None, "Screeners", "/screeners")]
    if not screens:
        return _response("You have no saved screens. You can create them in Screeners." if english else
                         "No tienes pantallas guardadas en el screener. Puedes crearlas en Screeners.",
                         sources, "account_saved_screens")
    count = len(screens)
    lines = [f"You have {count} saved screen{'s' if count != 1 else ''}:" if english else
             f"Tienes {count} pantalla{'s' if count != 1 else ''} guardada{'s' if count != 1 else ''} en el screener:"]
    for screen in screens[:15]:
        tickers = list(db.scalars(
            select(Company.ticker).join(SavedScreenMatch, SavedScreenMatch.company_id == Company.id)
            .where(SavedScreenMatch.tenant_id == tenant, SavedScreenMatch.saved_screen_id == screen.id,
                   SavedScreenMatch.active.is_(True))
            .order_by(SavedScreenMatch.id)
        ).all())
        n = len(screen.criteria or [])
        if english:
            crit = f"{n} criteri{'a' if n != 1 else 'on'}"
            match = (f"{len(tickers)} compan{'ies' if len(tickers) != 1 else 'y'} match now ({', '.join(tickers[:8])}"
                     f"{', …' if len(tickers) > 8 else ''})" if tickers else "no company matches now")
            ran = f"; last run {_date_en(screen.last_run_at.date())}" if screen.last_run_at else ""
        else:
            crit = f"{n} criterio{'s' if n != 1 else ''}"
            match = (f"la cumple{'n' if len(tickers) != 1 else ''} ahora {len(tickers)} empresa"
                     f"{'s' if len(tickers) != 1 else ''} ({', '.join(tickers[:8])}{', …' if len(tickers) > 8 else ''})"
                     if tickers else "ninguna empresa la cumple ahora")
            ran = f"; última ejecución el {fecha_es(screen.last_run_at.date())}" if screen.last_run_at else ""
        lines.append(f"- «{screen.name}»: {crit}; {match}{ran}.")
    if count > 15:
        lines.append(f"And {count - 15} more in Screeners." if english else f"Y {count - 15} más en Screeners.")
    lines.append("To see or change them, go to Screeners." if english else "Para verlas o cambiarlas, ve a Screeners.")
    return _response("\n".join(lines), sources, "account_saved_screens")


_DOCS = re.compile(
    r"\b(?:que|cuantos)\s+documentos\s+tengo\b(?!\s+que)|\bmis\s+documentos\b"
    r"|\bdocumentos\s+(?:que\s+tengo\s+)?(?:en\s+(?:la|mi)\s+biblioteca|guardados|subidos)\b|\bque\s+hay\s+en\s+mi\s+biblioteca\b"
    r"|\bmy\s+(?:documents|library)\b|\bwhat\s+documents\s+do\s+i\s+have\b"
)


def _asks_documents(text: str, question: str) -> bool:
    return bool(_DOCS.search(text) and not _tickers_in(question)
                and not re.search(r"\b(?:necesito|hacienda|para\s+declarar|need)\b", text))


def _documents_answer(db: Session, tenant: int) -> ChatResponse:
    from sqlalchemy import func

    from app.models import KnowledgeDocument

    english = _english()
    ready = (KnowledgeDocument.tenant_id == tenant, KnowledgeDocument.status != "failed")
    by_type = db.execute(select(KnowledgeDocument.document_type, func.count()).where(*ready)
                         .group_by(KnowledgeDocument.document_type)).all()
    sources = [_source("knowledge_document", None, "Biblioteca", "/knowledge")]
    total = sum(int(n) for _, n in by_type)
    if not total:
        return _response("You have no documents in the library. You can upload them in Library." if english else
                         "No tienes documentos en la biblioteca. Puedes subirlos en Biblioteca.",
                         sources, "account_documents")
    kinds = ", ".join(f"{kind or '?'} {n}" for kind, n in sorted(by_type, key=lambda row: str(row[0])))
    latest = db.scalars(select(KnowledgeDocument).where(*ready)
                        .order_by(KnowledgeDocument.publication_date.desc().nulls_last(),
                                  KnowledgeDocument.id.desc()).limit(8)).all()
    noun = ("document" if total == 1 else "documents") if english else ("documento" if total == 1 else "documentos")
    lines = [f"You have {total} {noun} in the library ({kinds}). Latest:" if english else
             f"Tienes {total} {noun} en la biblioteca ({kinds}). Los últimos:"]
    for doc in latest:
        bits = [b for b in (doc.ticker, (_date_en(doc.publication_date) if english else fecha_es(doc.publication_date))
                            if doc.publication_date else None) if b]
        lines.append(f"- «{doc.title}»" + (f" ({', '.join(bits)})" if bits else ""))
    lines.append("To open them or upload more, go to Library." if english
                 else "Para abrirlos o subir más, ve a Biblioteca.")
    return _response("\n".join(lines), sources, "account_documents")


def answer_account_question(db: Session, question: str) -> ChatResponse | None:
    """Respuesta de datos de la cuenta, o None si la pregunta no es de este módulo."""
    tenant = _tenant(db)
    if tenant is None:
        return None
    text = _fold(question)
    if _asks_daily_change(text):
        return _daily_change_answer(db, tenant)
    if _asks_history(text, question):
        return _history_answer(db, tenant, text)
    if _asks_sell_all_tax(text, question):
        return _sell_all_answer(db, tenant)
    if _asks_documents(text, question):
        return _documents_answer(db, tenant)
    if _asks_saved_screens(text, question):
        return _saved_screens_answer(db, tenant)
    if _asks_alert_rules(text, question):
        return _alert_rules_answer(db, tenant)
    if _asks_plan(text, question):
        return _plan_answer(db, tenant, text)
    if _asks_return_ranking(text, question):
        return _ranking_answer(db, tenant, text)
    year = _asked_year(text)
    if _asks_withholding(text) and _tickers_in(question):
        return _withholding_answer(db, tenant, year, _tickers_in(question))
    if _asks_fees(text):
        return _fees_answer(db, tenant, year, _tickers_in(question))
    if _asks_cash(text, question):
        return _cash_answer(db, tenant)
    if year is not None and _SALES.search(text):
        return _sales_answer(db, year, _tickers_in(question))
    # Solo el año en curso: un ejercicio pasado ya lo responde el bloque fiscal (#3952).
    if (year == local_today().year and _YEAR_GAINS.search(text) and not _tickers_in(question)
            and not re.search(r"\bsi\b", text)):
        return _year_gains_answer(db, tenant, year)
    return None


__all__ = ["answer_account_question"]
