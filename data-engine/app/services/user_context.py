"""Contexto personal del Cerebro: TODO lo del usuario, compacto y con procedencia.

Prueba real 2026-10-27: «¿qué está barato de mi watchlist?» → «no tengo acceso a
tu watchlist»; «¿qué riesgo tengo?» → preguntaba si era riesgo de salud. El
Cerebro tenía respuestas sueltas para la cartera, pero ninguna pieza le daba
una foto única de los datos del usuario.

``build_user_context`` reúne, por tenant y SOLO de la base de GerarAI:

* ``cartera``: posiciones (peso, valor, P&L, divisa base) y nivel DCA;
* ``watchlist``: valor justo único (``fair_value_service``), último cierre,
  margen de seguridad (V − P) / V (Graham) y nivel DCA 1X–4X / recorte;
* ``tesis``: última versión por empresa con criterios de invalidación;
* ``avisos``: avisos abiertos y reglas activas;
* ``diario``: últimas decisiones registradas;
* ``plan``: aportación mensual y asignación objetivo;
* ``fiscal``: resumen del ejercicio, solo si se pide.

Cada línea dice de qué página sale (``/portfolio``, ``/watchlist``…), así el
LLM puede citarla y la comprobación de cifras puede verificarla. Sin dato no
hay línea inventada: se escribe «sin dato». El texto queda acotado
(``max_chars``) para no disparar tokens.

Degradación: si el motor DCA (tabla ``dca_signal_states``) o el lector
``dca_level_reader`` no están aún en ``main``, cada valor dice «nivel DCA no
disponible» en vez de inventar uno.
"""

from __future__ import annotations

import importlib
import math
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.local_date import local_today
from app.core.tenancy import session_tenant_id as _tenant
from app.models import (
    AlertRule,
    Company,
    DecisionJournalEntry,
    InvestmentPlan,
    MarketPrice,
    Portfolio,
    Position,
    ResearchAlert,
    ThesisVersion,
    WatchItem,
)
from app.services.portfolio_ledger_service import trade_price_fallbacks
from app.services.price_units import listing_price
from app.valuation.currency import normalize_currency

SECTIONS: tuple[str, ...] = ("cartera", "watchlist", "tesis", "avisos", "diario", "plan", "fiscal")
DEFAULT_SECTIONS: tuple[str, ...] = ("cartera", "watchlist", "tesis", "avisos", "diario", "plan")
SECTION_PAGES: dict[str, str] = {
    "cartera": "/portfolio",
    "watchlist": "/watchlist",
    "tesis": "/research/TICKER",
    "avisos": "/alerts",
    "diario": "/research/TICKER/decision-lessons",
    "plan": "/plan",
    "fiscal": "/taxes",
}
SECTION_TITLES: dict[str, str] = {
    "cartera": "Cartera",
    "watchlist": "Watchlist",
    "tesis": "Tesis",
    "avisos": "Avisos",
    "diario": "Diario de decisiones",
    "plan": "Plan de aportación",
    "fiscal": "Resumen fiscal",
}
# Límites por bloque: el contexto entero cabe en ~2.000 tokens.
MAX_POSITIONS = 20
MAX_WATCH = 30
MAX_THESES = 12
MAX_ALERTS = 8
MAX_JOURNAL = 6
MAX_ALLOCATIONS = 12
DEFAULT_MAX_CHARS = 9000
# Un V/P fuera de [0,1; 10] es casi siempre un desajuste de unidades (GBX vs
# GBP, ADR vs acción ordinaria): el margen no se calcula y se dice por qué.
_MOS_SANE_RATIO = 10.0
_NO_DCA = "nivel DCA no disponible (el motor DCA aún no ha evaluado)"
_DCA_LABELS = {
    4: "4X DCA",
    3: "3X DCA",
    2: "2X DCA",
    1: "1X DCA",
    -1: "RECORTE LIGERO",
    -2: "RECORTE FUERTE",
}
_INACTIVE_THESIS = {"archived", "rejected", "draft_failed_audit"}
_THESIS_STATUS_ES = {
    "draft": "borrador",
    "final": "final",
    "published": "publicada",
    "approved": "aprobada",
    "active": "activa",
    "review": "en revisión",
    "stale": "desactualizada",
    "changes_requested": "cambios solicitados",
}
_THESIS_RATING_ES = {
    "buy": "compra",
    "accumulate": "acumular",
    "add": "añadir",
    "hold": "mantener",
    "watch": "vigilar",
    "sell": "venta",
    "exit": "salir",
    "overweight": "sobreponderar",
    "underweight": "infraponderar",
}
_DECISION_ES = {
    "buy": "compra",
    "add": "ampliación",
    "sell": "venta",
    "trim": "recorte",
    "hold": "mantener",
    "watch": "vigilar",
    "pass": "descartar",
}
_ENTRY_STATUS_ES = {"open": "abierta", "closed": "cerrada", "reviewed": "revisada"}


def num_es(value: float, digits: int = 2) -> str:
    """Número en formato es-ES (1.234,56)."""
    text = f"{value:,.{digits}f}"
    return text.replace(",", "\u2009").replace(".", ",").replace("\u2009", ".")


def pct_es(fraction: float, digits: int = 1, *, signed: bool = False) -> str:
    text = num_es(fraction * 100, digits)
    if signed and fraction > 0:
        text = "+" + text
    return f"{text} %"


def money_es(value: float, currency: str | None, *, signed: bool = False) -> str:
    text = num_es(value, 2)
    if signed and value > 0:
        text = "+" + text
    return f"{text} {currency or '¿divisa?'}"


def margin_of_safety(value: float | None, price: float | None) -> float | None:
    """(V − P) / V, estándar de Graham. None sin dato o con V ≤ 0."""
    if value is None or price is None:
        return None
    # NaN/inf no son cifras: N/D, nunca un margen NaN (mismo criterio que el motor).
    if not (math.isfinite(value) and math.isfinite(price)) or value <= 0 or price <= 0:
        return None
    return (value - price) / value


@dataclass
class ContextBlock:
    key: str
    lines: list[str] = field(default_factory=list)
    rows: list[dict] = field(default_factory=list)
    sources: list[dict] = field(default_factory=list)

    @property
    def title(self) -> str:
        return f"{SECTION_TITLES[self.key]} ({SECTION_PAGES[self.key]})"


@dataclass
class UserContext:
    tenant_id: int
    blocks: dict[str, ContextBlock]
    as_of: date
    truncated: bool = False

    def block(self, key: str) -> ContextBlock | None:
        return self.blocks.get(key)

    @property
    def sources(self) -> list[dict]:
        return [source for block in self.blocks.values() for source in block.sources]

    def render(self, max_chars: int = DEFAULT_MAX_CHARS) -> str:
        """Texto compacto para el LLM, bloque a bloque, acotado a ``max_chars``."""
        out: list[str] = [f"Datos del usuario en GerarAI a {self.as_of.isoformat()} (única fuente válida):"]
        used = len(out[0])
        truncated = False
        for key in SECTIONS:
            block = self.blocks.get(key)
            if block is None:
                continue
            chunk = [f"## {block.title}", *block.lines]
            for line in chunk:
                if used + len(line) + 1 > max_chars:
                    truncated = True
                    break
                out.append(line)
                used += len(line) + 1
            if truncated:
                out.append("(contexto recortado por longitud; el resto está en la página citada)")
                break
        self.truncated = truncated
        return "\n".join(out)


def _f(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _day(value: datetime | date | None) -> str:
    if value is None:
        return "sin fecha"
    if isinstance(value, datetime):
        value = value.date()
    return value.isoformat()


def _short(text: str | None, limit: int = 140) -> str:
    clean = " ".join((text or "").split())
    return clean if len(clean) <= limit else clean[: limit - 1].rstrip() + "…"


def _source(kind: str, ident: Any, title: str, url: str) -> dict:
    return {"type": kind, "id": str(ident), "title": title, "url": url}


# ------------------------------------------------------------------ DCA


DcaReader = Callable[[Session, int, list[str]], "dict[str, Any] | None"]


def default_dca_reader(db: Session, tenant: int, symbols: list[str]) -> dict[str, Any] | None:
    """Lee el nivel DCA con ``dca_level_reader`` si existe; si no, None."""
    try:
        reader = importlib.import_module("app.services.dca_level_reader")
    except ImportError:
        return None
    read = getattr(reader, "read_dca_levels", None)
    if read is None:
        return None
    try:
        return read(db, tenant, symbols)
    except SQLAlchemyError:
        db.rollback()
        return None


def _dca_text(
    levels: dict[str, Any] | None, symbol: str, today: date | None = None
) -> tuple[str, int | None]:
    if levels is None:
        return _NO_DCA, None
    reading = levels.get(symbol.upper())
    if reading is None:
        return "sin nivel DCA evaluado", None
    level = int(getattr(reading, "level", 0) or 0)
    label = getattr(reading, "label", None) or _DCA_LABELS.get(level, f"{level}X DCA")
    status = getattr(reading, "status", "") or ""
    when = getattr(reading, "signal_date", None)
    extra = " (en formación)" if status == "forming" else ""
    stale = ""
    if today is not None and isinstance(when, date):
        from app.core.config import get_settings

        age = (today - when).days
        if age > int(get_settings().dca_max_data_age_days):
            # Mismo límite que la watchlist («desactualizado»): no es el nivel de hoy.
            stale = f" [desactualizado: último cierre de hace {age} días]"
    return f"nivel DCA {label}{extra} ({_day(when)}){stale}", level


# ------------------------------------------------------------------ bloques


def _latest_closes(db: Session, company_ids: Iterable[int]) -> dict[int, tuple[float, date, str | None]]:
    ids = sorted({int(i) for i in company_ids})
    if not ids:
        return {}
    latest = (
        select(MarketPrice.company_id, func.max(MarketPrice.date).label("d"))
        .where(MarketPrice.company_id.in_(ids))
        .group_by(MarketPrice.company_id)
        .subquery()
    )
    rows = db.execute(
        select(MarketPrice.company_id, MarketPrice.close, MarketPrice.date, MarketPrice.quote_currency).join(
            latest, (latest.c.company_id == MarketPrice.company_id) & (latest.c.d == MarketPrice.date)
        )
    ).all()
    out: dict[int, tuple[float, date, str | None]] = {}
    for company_id, close, day, quote_currency in rows:
        value = _f(close)
        if value is not None and value > 0:
            out[int(company_id)] = (value, day, quote_currency)
    return out


def _fair_values(db: Session, companies: list[Company], today: date) -> dict[int, dict]:
    if not companies:
        return {}
    from app.services.fair_value_service import resolve_fair_values

    try:
        return resolve_fair_values(db, companies, today=today)
    except SQLAlchemyError:
        db.rollback()
        return {}


def _portfolio_block(
    db: Session, tenant: int, levels: dict[str, Any] | None, today: date | None = None
) -> ContextBlock:
    block = ContextBlock("cartera")
    rows = db.execute(
        select(Position, Company)
        .join(Company, Company.id == Position.company_id)
        .where(Position.tenant_id == tenant, Position.quantity > 0)
    ).all()
    portfolio = db.scalar(
        select(Portfolio).where(Portfolio.tenant_id == tenant).order_by(Portfolio.is_default.desc(), Portfolio.id)
    )
    if not rows:
        block.lines.append("- Sin posiciones guardadas.")
        return block

    def value_of(pos: Position) -> float:
        base = _f(pos.market_value_base)
        return base if base is not None else (_f(pos.market_value) or 0.0)

    bases = {(pos.base_currency or "").upper() for pos, _ in rows}
    base = portfolio.base_currency.upper() if portfolio and portfolio.base_currency else None
    if len(bases) == 1:
        base = next(iter(bases)) or base
    single_base = len(bases) == 1
    # Sin cotización real el precio es el de la última operación (auditoría A3):
    # su P&L latente no está medido, ni por posición ni en el total.
    quote_missing = trade_price_fallbacks(db, [pos for pos, _ in rows], tenant_id=tenant)
    total = sum(value_of(pos) for pos, _ in rows)
    known = [pos for pos, _ in rows if pos.company_id not in quote_missing]
    total_cost = sum(_f(pos.cost_basis_base) or 0.0 for pos in known)
    total_pnl = sum(_f(pos.unrealized_pnl_base) or 0.0 for pos in known)
    ordered = sorted(rows, key=lambda row: value_of(row[0]), reverse=True)
    as_of = min(pos.as_of for pos, _ in rows)
    header = f"- {len(rows)} posiciones; divisa base {base or 'sin fijar'}; datos a {_day(as_of)}."
    if single_base and total > 0:
        header += f" Valor total {money_es(total, base)}."
        if total_cost > 0:
            header += f" P&L latente {money_es(total_pnl, base, signed=True)} ({pct_es(total_pnl / total_cost, signed=True)} sobre coste)."
    elif not single_base:
        header += " Divisas base mezcladas: sin total ni pesos."
    block.lines.append(header)
    for pos, comp in ordered[:MAX_POSITIONS]:
        value = value_of(pos)
        weight = value / total if single_base and total > 0 else None
        cost = _f(pos.cost_basis_base)
        pnl = _f(pos.unrealized_pnl_base)
        if pnl is None:
            pnl = _f(pos.unrealized_pnl)
        if pos.company_id in quote_missing:
            pnl = None
        pnl_pct = pnl / cost if pnl is not None and cost else None
        dca, level = _dca_text(levels, comp.ticker, today)
        parts = [f"- {comp.ticker} ({_short(comp.name, 40)})"]
        if weight is not None:
            parts.append(f"peso {pct_es(weight)}")
        parts.append(f"valor {money_es(value, pos.base_currency or base)}")
        if pnl is not None:
            pnl_text = f"P&L {money_es(pnl, pos.base_currency or base, signed=True)}"
            if pnl_pct is not None:
                pnl_text += f" ({pct_es(pnl_pct, signed=True)})"
            parts.append(pnl_text)
        price = _f(pos.market_price)
        if price:
            parts.append(f"precio {num_es(price)} {pos.currency}")
        if pos.company_id in quote_missing:
            parts.append("sin cotización real (precio de su última operación)")
        if pos.valuation_hold_reason:
            parts.append("valoración en suspenso")
        parts.append(dca)
        block.lines.append(", ".join(parts) + ".")
        block.rows.append({
            "ticker": comp.ticker, "weight": weight, "value": value, "currency": pos.base_currency or base,
            "pnl": pnl, "pnl_pct": pnl_pct, "dca_level": level, "sector": comp.sector,
        })
        block.sources.append(_source("position", pos.id, f"Posición {comp.ticker}", "/portfolio"))
    if len(ordered) > MAX_POSITIONS:
        block.lines.append(f"- Y {len(ordered) - MAX_POSITIONS} posiciones pequeñas más en /portfolio.")
    if single_base and total > 0:
        sectors: dict[str, float] = {}
        for pos, comp in rows:
            sectors[comp.sector or "Sin sector"] = sectors.get(comp.sector or "Sin sector", 0.0) + value_of(pos)
        top = sorted(sectors.items(), key=lambda kv: kv[1], reverse=True)[:4]
        block.lines.append("- Peso por sector: " + "; ".join(f"{name} {pct_es(v / total)}" for name, v in top) + ".")
    return block


def _watchlist_block(
    db: Session, tenant: int, levels: dict[str, Any] | None, today: date
) -> ContextBlock:
    block = ContextBlock("watchlist")
    items = db.scalars(
        select(WatchItem).where(WatchItem.tenant_id == tenant).order_by(WatchItem.id)
    ).all()
    if not items:
        block.lines.append("- Watchlist vacía.")
        return block
    symbols = [str(item.symbol).upper() for item in items]
    companies = {
        str(c.ticker).upper(): c
        for c in db.scalars(select(Company).where(Company.ticker.in_(symbols))).all()
    }
    fair = _fair_values(db, list(companies.values()), today)
    closes = _latest_closes(db, [c.id for c in companies.values()])
    block.lines.append(
        f"- {len(items)} valores. Margen de seguridad = (valor justo − precio) / valor justo; "
        "positivo = cotiza por debajo del valor justo."
    )
    for item in items[:MAX_WATCH]:
        symbol = str(item.symbol).upper()
        comp = companies.get(symbol)
        dca, level = _dca_text(levels, symbol, today)
        row: dict[str, Any] = {"ticker": symbol, "dca_level": level, "mos": None, "fair_value": None, "price": None}
        if comp is None:
            block.lines.append(f"- {symbol}: aún sin ficha en GerarAI (sin precio ni valor justo); {dca}.")
            block.rows.append(row)
            continue
        parts = [f"- {symbol} ({_short(comp.name, 40)})"]
        reading = fair.get(int(comp.id)) or {}
        value = _f(reading.get("value"))
        raw_close = closes.get(int(comp.id))
        currency = comp.currency
        # El cierre guardado va en la unidad de SU cotizacion (Londres: GBp).
        # Se pasa a la unidad mayor antes de rotularlo y compararlo con el
        # valor justo; sin unidad verificable no hay precio (antes: «1200 GBP»).
        close = None
        listed = (
            listing_price(Decimal(str(raw_close[0])), quote_currency=raw_close[2], company=comp)
            if raw_close is not None
            else None
        )
        if raw_close is not None and listed is not None:
            close = (float(listed[0]), raw_close[1])
            parts.append(f"cierre {num_es(close[0])} {listed[1]} ({_day(close[1])})")
            row["price"] = close[0]
        elif raw_close is not None:
            parts.append("precio guardado sin unidad verificable")
        else:
            parts.append("sin precio guardado")
        fair_major = normalize_currency(currency)[0]
        if close is not None and listed is not None and (fair_major is None or listed[1] != fair_major):
            close_for_mos = None
        else:
            close_for_mos = close
        if value is not None:
            label = reading.get("label") or "valor justo"
            parts.append(f"valor justo {num_es(value)} {normalize_currency(currency)[0] or currency} ({label})")
            row["fair_value"] = value
        else:
            parts.append("sin valor justo (ni tesis publicada ni motor)")
        mos = margin_of_safety(value, close_for_mos[0] if close_for_mos else None)
        if mos is not None and value is not None and close_for_mos is not None:
            ratio = value / close_for_mos[0]
            if ratio > _MOS_SANE_RATIO or ratio < 1 / _MOS_SANE_RATIO:
                parts.append("margen no calculado: posible desajuste de unidades o divisa entre precio y valor")
            else:
                parts.append(f"margen de seguridad {pct_es(mos, signed=True)}")
                row["mos"] = mos
        parts.append(dca)
        block.lines.append(", ".join(parts) + ".")
        block.rows.append(row)
        block.sources.append(_source("watch_item", item.id, f"Watchlist {symbol}", "/watchlist"))
    if len(items) > MAX_WATCH:
        block.lines.append(f"- Y {len(items) - MAX_WATCH} valores más en /watchlist.")
    return block


def _criteria_text(raw: Any) -> list[str]:
    out: list[str] = []
    for item in raw or []:
        if isinstance(item, str):
            text = item
        elif isinstance(item, dict):
            text = str(item.get("text") or item.get("criterion") or item.get("description") or item.get("label") or "")
        else:
            text = str(item)
        if text.strip():
            out.append(_short(text, 120))
    return out


def _theses_block(db: Session, tenant: int) -> ContextBlock:
    block = ContextBlock("tesis")
    latest = (
        select(ThesisVersion.company_id, func.max(ThesisVersion.version).label("v"))
        .where(ThesisVersion.tenant_id == tenant)
        .group_by(ThesisVersion.company_id)
        .subquery()
    )
    rows = db.execute(
        select(ThesisVersion, Company)
        .join(latest, (latest.c.company_id == ThesisVersion.company_id) & (latest.c.v == ThesisVersion.version))
        .join(Company, Company.id == ThesisVersion.company_id)
        .where(ThesisVersion.tenant_id == tenant)
        .order_by(ThesisVersion.updated_at.desc(), ThesisVersion.id.desc())
    ).all()
    active = [(t, c) for t, c in rows if (t.status or "") not in _INACTIVE_THESIS]
    if not active:
        block.lines.append("- Sin tesis activas.")
        return block
    block.lines.append(f"- {len(active)} tesis activas (última versión de cada empresa).")
    for thesis, comp in active[:MAX_THESES]:
        status = _THESIS_STATUS_ES.get(thesis.status or "", thesis.status)
        rating = _THESIS_RATING_ES.get(thesis.rating or "", thesis.rating)
        parts = [f"- {comp.ticker} v{thesis.version}: estado {status}, rating {rating}"]
        expected = _f(thesis.expected_value) or _f(thesis.base_value)
        if expected is not None:
            parts.append(f"valor esperado {num_es(expected)} {comp.currency}")
        if thesis.hypothesis:
            parts.append(f"hipótesis: {_short(thesis.hypothesis, 140)}")
        criteria = _criteria_text(thesis.invalidation_criteria)
        if criteria:
            parts.append("se invalida si: " + " | ".join(criteria[:3]))
        else:
            parts.append("sin criterios de invalidación escritos")
        block.lines.append("; ".join(parts) + ".")
        block.rows.append({"ticker": comp.ticker, "version": thesis.version, "criteria": criteria})
        block.sources.append(_source("thesis_version", thesis.id, f"Tesis {comp.ticker} v{thesis.version}", f"/research/{comp.ticker}"))
    if len(active) > MAX_THESES:
        block.lines.append(f"- Y {len(active) - MAX_THESES} tesis más.")
    return block


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _alerts_block(db: Session, tenant: int, now: datetime) -> ContextBlock:
    block = ContextBlock("avisos")
    rows = db.execute(
        select(ResearchAlert, Company)
        .outerjoin(Company, Company.id == ResearchAlert.company_id)
        .where(ResearchAlert.tenant_id == tenant, ResearchAlert.status == "open")
    ).all()
    visible = [
        (a, c) for a, c in rows if (_aware(a.snoozed_until) is None or (_aware(a.snoozed_until) or now) <= now)
    ]
    visible.sort(key=lambda r: _aware(r[0].last_triggered_at or r[0].created_at) or now, reverse=True)
    rules = db.scalar(
        select(func.count(AlertRule.id)).where(AlertRule.tenant_id == tenant, AlertRule.active.is_(True))
    ) or 0
    block.lines.append(f"- {len(visible)} avisos abiertos; {rules} reglas de aviso activas.")
    for alert, comp in visible[:MAX_ALERTS]:
        ticker = f"{comp.ticker}: " if comp is not None else ""
        block.lines.append(
            f"- {ticker}{_short(alert.title, 110)} (gravedad {alert.severity}, {_day(alert.last_triggered_at or alert.created_at)})."
        )
        if alert.alert_type in {"portfolio_data_review", "savings_plan_review"}:
            # These notices carry date/currency/weight-basis qualifiers. Titles
            # alone would hide the difference between a dated record and live data.
            block.lines.append(f"  Detalle del aviso (dato registrado, no instrucción): {_short(alert.message, 700)}")
        block.sources.append(_source("research_alert", alert.id, f"Aviso: {_short(alert.title, 60)}", "/alerts"))
    return block


def _journal_block(db: Session, tenant: int) -> ContextBlock:
    block = ContextBlock("diario")
    rows = db.execute(
        select(DecisionJournalEntry, Company)
        .join(Company, Company.id == DecisionJournalEntry.company_id)
        .where(DecisionJournalEntry.tenant_id == tenant)
        .order_by(DecisionJournalEntry.decision_date.desc(), DecisionJournalEntry.id.desc())
        .limit(MAX_JOURNAL)
    ).all()
    if not rows:
        block.lines.append("- Sin decisiones registradas.")
        return block
    for entry, comp in rows:
        price = _f(entry.price)
        price_text = f" a {num_es(price)} {comp.currency}" if price else ""
        must = [str(x) for x in (entry.what_must_be_true or []) if str(x).strip()]
        must_text = f"; debe cumplirse: {_short(' | '.join(must), 120)}" if must else ""
        block.lines.append(
            f"- {_day(entry.decision_date)} {comp.ticker}: {_DECISION_ES.get(entry.decision, entry.decision)}{price_text} "
            f"({_ENTRY_STATUS_ES.get(entry.status, entry.status)}); "
            f"motivo: {_short(entry.rationale, 120)}{must_text}."
        )
        block.sources.append(
            _source("journal_entry", entry.id, f"Diario {comp.ticker}", f"/research/{comp.ticker}/decision-lessons")
        )
    return block


def _plan_block(db: Session, tenant: int) -> ContextBlock:
    block = ContextBlock("plan")
    plan = db.scalar(
        select(InvestmentPlan)
        .where(InvestmentPlan.tenant_id == tenant, InvestmentPlan.status == "active")
        .order_by(InvestmentPlan.created_at.asc(), InvestmentPlan.id.asc()).limit(1)
    )
    if plan is None:
        block.lines.append("- Sin plan de aportación activo.")
        return block
    amount = _f(plan.monthly_contribution) or 0.0
    currency = plan.monthly_contribution_currency or "divisa no registrada"
    block.lines.append(
        f"- Aportación mensual {num_es(amount)} {currency}; horizonte {plan.horizon_years} años; desde {_day(plan.start_date)}."
    )
    allocations = [a for a in (plan.target_allocations or []) if isinstance(a, dict)]
    if allocations:
        rendered = []
        for alloc in allocations[:MAX_ALLOCATIONS]:
            name = alloc.get("ticker") or alloc.get("symbol") or alloc.get("name") or alloc.get("asset") or "?"
            weight = _f(alloc.get("weight") if alloc.get("weight") is not None else alloc.get("target_weight"))
            if weight is not None:
                fraction = weight / 100 if weight > 1 else weight
                rendered.append(f"{name} {pct_es(fraction)}")
            else:
                rendered.append(str(name))
        block.lines.append("- Asignación objetivo: " + "; ".join(rendered) + ".")
    from app.services.savings_projection import savings_contract
    projection = savings_contract(db)
    if projection['status'] == 'ok':
        block.lines.append('- Ahorro futuro: simulación solo de aportaciones, capital inicial 0; '
            'rentabilidad total incluye reinversión. No es previsión de cartera ni promesa.')
        for scenario in projection['scenarios']:
            block.lines.append(f"- Hipótesis {num_es(scenario['annual_total_return'] * 100)} % anual total: "
                f"{num_es(scenario['terminal_value'])} {projection['currency']} en "
                f"{projection['horizon_years']} años; aportado {num_es(scenario['contributed'])}. "
                'Sin impuestos/costes; dividendo neto N/D. DCA reparte la cuota, no mejora esta hipótesis.')
        block.sources.append(_source("savings_projection", plan.id, "Simulación de ahorro", "/portfolio?tab=prevision"))
    else:
        block.lines.append('- Simulación de ahorro no disponible: falta divisa registrada; no asumir EUR.')
    block.sources.append(_source("investment_plan", plan.id, "Plan de aportación", "/plan"))
    return block


_FISCAL_LABELS_EN = {
    "total_dividends_base": "gross dividends",
    "total_withholding_base": "withholding at source",
    "total_realized_gain_base": "realized gain/loss",
    "total_blocked_loss_base": "blocked losses (two-month rule)",
    "net_taxable_base": "estimated savings income base",
}


def _fiscal_block(db: Session, year: int, *, english: bool = False) -> ContextBlock:
    block = ContextBlock("fiscal")
    try:
        from app.services.tax_report_service import TaxReportService

        summary = (TaxReportService().get_report(db, year) or {}).get("summary") or {}
    except Exception:  # noqa: BLE001 - el resumen fiscal nunca rompe el chat
        db.rollback()
        block.lines.append(
            f"- Tax year {year}: the tax report couldn't be calculated right now." if english
            else f"- Ejercicio {year}: no se pudo calcular el informe fiscal ahora."
        )
        return block
    base = summary.get("base_currency") or "EUR"
    if english:
        # Ajustes → Idioma = English: las mismas cifras, en inglés.
        parts_en = []
        for key, label in _FISCAL_LABELS_EN.items():
            value = _f(summary.get(key))
            parts_en.append(f"{label} {value:,.2f} {base}" if value is not None else f"{label}: no reliable data")
        block.lines.append(f"- Tax year {year}: " + "; ".join(parts_en) + ". Draft, not tax advice.")
        block.sources.append(_source("tax_report", year, f"Tax report {year}", "/taxes"))
        return block
    labels = (
        ("total_dividends_base", "dividendos brutos"),
        ("total_withholding_base", "retenciones en origen"),
        ("total_realized_gain_base", "ganancia/pérdida realizada"),
        ("total_blocked_loss_base", "pérdidas bloqueadas (regla de 2 meses)"),
        ("net_taxable_base", "base del ahorro estimada"),
    )
    parts = []
    for key, label in labels:
        value = _f(summary.get(key))
        parts.append(f"{label} {money_es(value, base)}" if value is not None else f"{label}: sin dato fiable")
    block.lines.append(f"- Ejercicio {year}: " + "; ".join(parts) + ". Borrador, no asesoría fiscal.")
    block.sources.append(_source("tax_report", year, f"Informe fiscal {year}", "/taxes"))
    return block


def build_user_context(
    db: Session,
    *,
    sections: Iterable[str] | None = None,
    today: date | None = None,
    now: datetime | None = None,
    dca_reader: DcaReader | None = None,
    fiscal_year: int | None = None,
    english: bool = False,
) -> UserContext | None:
    """Foto compacta de los datos del usuario. None sin tenant (nunca datos ajenos)."""
    tenant = _tenant(db)
    if tenant is None:
        return None
    # «Hoy» del usuario (Europe/Madrid): el 1 de enero a las 00:30 el día UTC
    # aún es 31 de diciembre y el año fiscal por defecto salía uno antes.
    today = today or local_today()
    now = now or datetime.now(UTC)
    wanted = [key for key in (sections or DEFAULT_SECTIONS) if key in SECTIONS]
    blocks: dict[str, ContextBlock] = {}
    levels: dict[str, Any] | None = None
    if "cartera" in wanted or "watchlist" in wanted:
        held = db.scalars(
            select(Company.ticker).join(Position, Position.company_id == Company.id)
            .where(Position.tenant_id == tenant, Position.quantity > 0)
        ).all()
        watched = db.scalars(select(WatchItem.symbol).where(WatchItem.tenant_id == tenant)).all()
        symbols = sorted({str(s).upper() for s in [*held, *watched]})
        levels = (dca_reader or default_dca_reader)(db, tenant, symbols)
    builders: dict[str, Callable[[], ContextBlock]] = {
        "cartera": lambda: _portfolio_block(db, tenant, levels, today),
        "watchlist": lambda: _watchlist_block(db, tenant, levels, today),
        "tesis": lambda: _theses_block(db, tenant),
        "avisos": lambda: _alerts_block(db, tenant, now),
        "diario": lambda: _journal_block(db, tenant),
        "plan": lambda: _plan_block(db, tenant),
        "fiscal": lambda: (
            _fiscal_block(db, fiscal_year or (today.year - 1), english=True) if english
            else _fiscal_block(db, fiscal_year or (today.year - 1))
        ),
    }
    for key in wanted:
        try:
            blocks[key] = builders[key]()
        except SQLAlchemyError:
            # Una tabla sin migrar degrada a «sin dato», no a error del chat.
            db.rollback()
            block = ContextBlock(key)
            block.lines.append("- No disponible ahora mismo.")
            blocks[key] = block
    return UserContext(tenant_id=tenant, blocks=blocks, as_of=today)
