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


def _money(value: float, currency: str | None, *, signed: bool = False, english: bool = False) -> str:
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
    total = float(latest.total_value_base or 0)
    day = latest.snapshot_date
    is_today = day == local_today()
    when = (_date_en(day) if english else fecha_es(day))
    sources = [_source("portfolio_snapshot", latest.id, f"Cartera {fecha_es(day)}", "/portfolio")]
    ret = latest.daily_return
    if ret is None or previous is None or not previous.total_value_base:
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


# ------------------------------------------------------------------ router


def answer_account_question(db: Session, question: str) -> ChatResponse | None:
    """Respuesta de datos de la cuenta, o None si la pregunta no es de este módulo."""
    tenant = _tenant(db)
    if tenant is None:
        return None
    text = _fold(question)
    if _asks_daily_change(text):
        return _daily_change_answer(db, tenant)
    return None


__all__ = ["answer_account_question"]
