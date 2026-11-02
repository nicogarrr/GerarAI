"""Cerebro: respuestas deterministas sobre avisos, riesgo de cartera y diario.

Completa ``brain_data_tools``: el chat ya leía posiciones, tesis, insider,
noticias y plan, pero no los avisos (ResearchAlert/AlertRule), el panel de
riesgo (RiskService + PortfolioDailySnapshot) ni el diario de decisiones
(DecisionJournalEntry). Solo lectura, por tenant, sin LLM ni proveedores, con
fecha y enlace a la página de origen en cada cifra.
"""
from __future__ import annotations

import math
import re
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.local_date import local_today
from app.models import (
    AlertRule,
    Company,
    DecisionJournalEntry,
    PortfolioDailySnapshot,
    ResearchAlert,
)
from app.schemas import ChatResponse
from app.services.display_es import fecha_es

_ORDER_RE = re.compile(r"(?i)\b(?:compra|comprar|vende|vender|ejecuta|buy|sell)\b")
# Crear o cambiar un aviso es una acción, no una consulta: no se contesta aquí.
_ALERT_ACTION_RE = re.compile(
    r"(?i)\b(?:crea|crear|creame|cr[eé]ame|pon|ponme|configura\w*|a[nñ]ade|activa\w*|desactiva\w*|"
    r"borra\w*|elimina\w*|silencia\w*|posp[oó]n\w*|"
    r"create|add|set\s+(?:up\s+)?an?|alert\s+me|notify|delete|remove|disable|enable|mute|snooze|pause)\b"
)
# «my alerts», «show my alerts», «which alerts are set?»: en inglés iban al modelo general.
_ALERTS_RE = re.compile(r"(?i)\b(?:avisos?|alertas?)\b|\b(?:my|any|open|which|what|show|list)\s+(?:\w+\s+)?alerts\b")
_RISK_METRIC_RE = re.compile(
    r"(?i)\b(?:drawdown|ca[ií]da\s+m[aá]xima|volatilidad|twr|panel\s+de\s+riesgo|"
    r"(?:avisos?|alertas?|reglas?|l[ií]mites?)\s+de\s+riesgo)\b"
)
_JOURNAL_RE = re.compile(
    r"(?i)\bdiario\b|\b(?:mis|[uú]ltimas|qu[eé])\s+decisiones\b|\bdecisiones\s+(?:que\s+)?(?:he|tom[eé]|registr\w*)"
    # En inglés («my decision journal», «what decisions have I logged?») iba al modelo general.
    r"|\b(?:decision|investment|trading)\s+(?:journal|log|diary)\b|\bmy\s+(?:journal|(?:recent\s+|last\s+)?decisions)\b"
    r"|\bdecisions\s+(?:have\s+)?i\s+(?:made|logged|recorded|taken)\b"
)

_SEVERITY_ES = {"critical": "crítica", "high": "alta", "medium": "media", "low": "baja", "info": "info"}
_DECISION_ES = {
    "buy": "comprar", "add": "ampliar", "hold": "mantener", "trim": "recortar",
    "sell": "vender", "watch": "vigilar", "pass": "descartar", "avoid": "evitar",
}


def _response(lines: list[str], sources: list[dict], path: str) -> ChatResponse:
    return ChatResponse(answer="\n\n".join(lines), sources=sources, model="deterministic",
                        prompt_version="brain-context-v1", confidence=0.9,
                        llm_trace={"path": path, "provider_calls": 0, "generated": False})


def _source(kind: str, ident, title: str, url: str) -> dict:
    return {"type": kind, "id": ident, "title": title, "url": url}


def _pct(value: float, digits: int = 1) -> str:
    text = f"{value * 100:,.{digits}f}".replace(",", "\x07").replace(".", ",").replace("\x07", ".")
    return f"{text} %"


def _day(value: datetime | date | None) -> str:
    if value is None:
        return "sin fecha"
    return fecha_es(value.date() if isinstance(value, datetime) else value)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


# ---------------------------------------------------------------- avisos


def alerts_answer(
    db: Session, tenant: int, company: Company | None = None, *, now: datetime | None = None
) -> ChatResponse:
    """Avisos abiertos (no pospuestos) y reglas activas del tenant."""
    now = now or datetime.now(UTC)
    query = (
        select(ResearchAlert, Company)
        .outerjoin(Company, Company.id == ResearchAlert.company_id)
        .where(ResearchAlert.tenant_id == tenant, ResearchAlert.status == "open")
    )
    if company is not None:
        query = query.where(ResearchAlert.company_id == company.id)
    rows = db.execute(query).all()
    visible = [
        (alert, comp) for alert, comp in rows
        if (_aware(alert.snoozed_until) is None or _aware(alert.snoozed_until) <= now)
    ]
    snoozed = len(rows) - len(visible)
    visible.sort(key=lambda row: _aware(row[0].last_triggered_at or row[0].created_at) or now, reverse=True)

    rule_query = select(AlertRule, Company).join(Company, Company.id == AlertRule.company_id).where(
        AlertRule.tenant_id == tenant, AlertRule.active.is_(True)
    )
    if company is not None:
        rule_query = rule_query.where(AlertRule.company_id == company.id)
    rules = db.execute(rule_query).all()

    from app.services.brain_account_tools import _date_en, _english, _rule_text

    english = _english()
    if english:
        scope = f" for {company.ticker}" if company is not None else ""
    else:
        scope = f" de {company.ticker}" if company is not None else ""
    lines: list[str] = []
    sources: list[dict] = []
    if visible:
        lines.append(f"Open alerts{scope}: {len(visible)} (most recent first)." if english
                     else f"Avisos abiertos{scope}: {len(visible)} (los más recientes primero).")
        for alert, comp in visible[:8]:
            ticker = f"{comp.ticker}: " if comp is not None else ""
            stamp = alert.last_triggered_at or alert.created_at
            if english:
                when = _date_en(stamp.date() if isinstance(stamp, datetime) else stamp) if stamp else "no date"
                lines.append(f"- {ticker}{alert.title} (severity {alert.severity}, {when}).")
            else:
                severity = _SEVERITY_ES.get(alert.severity, alert.severity)
                lines.append(f"- {ticker}{alert.title} (gravedad {severity}, {_day(stamp)}).")
            sources.append(_source("research_alert", alert.id, f"{'Alert' if english else 'Aviso'}: {alert.title}",
                                   "/alerts"))
        if len(visible) > 8:
            lines.append(f"And {len(visible) - 8} more on the alerts page." if english
                         else f"Y {len(visible) - 8} más en la página de avisos.")
    else:
        lines.append(f"No open alerts{scope}." if english else f"No hay avisos abiertos{scope}.")
    if snoozed:
        lines.append(f"Snoozed right now: {snoozed}." if english else f"Pospuestos ahora mismo: {snoozed}.")
    if rules:
        # Cada regla en lenguaje normal («MSFT: precio por debajo de 300 USD»);
        # antes salía el tipo interno y un recuento («price_below 1»).
        lines.append(f"Active alert rules{scope}: {len(rules)}." if english
                     else f"Reglas de aviso activas{scope}: {len(rules)}.")
        rules = sorted(rules, key=lambda row: (_aware(row[0].last_triggered_at) is None, row[0].id))
        for rule, comp in rules[:8]:
            condition = rule.condition or {}
            text = (_rule_text(rule.rule_type or "", condition, comp.currency, english)
                    if condition.get("value") is not None else rule.name)
            line = f"- {comp.ticker}: {text}"
            if rule.last_triggered_at is not None:
                fired = local_today(rule.last_triggered_at)
                line += (f" (last triggered {_date_en(fired)})" if english
                         else f" (saltó por última vez el {fecha_es(fired)})")
                sources.append(_source("alert_rule", rule.id, f"{'Rule' if english else 'Regla'}: {rule.name}",
                                       "/alerts"))
            lines.append(line)
        if len(rules) > 8:
            lines.append(f"And {len(rules) - 8} more in Alerts." if english else f"Y {len(rules) - 8} más en Alertas.")
    else:
        lines.append(f"No active alert rules{scope}." if english else f"No hay reglas de aviso activas{scope}.")
    return _response(lines, sources, "alerts")


# ---------------------------------------------------------------- riesgo


def _snapshot_metrics(
    db: Session, tenant: int, *, today: date | None = None, portfolio_id: int | None = None
) -> dict | None:
    """TWR, caída máxima y volatilidad de los últimos 12 meses de snapshots diarios.

    ``portfolio_id``: las fotos de esa cartera; sin él, la de la foto más reciente.
    """
    today = today or date.today()
    start = today - timedelta(days=365)
    latest_query = select(PortfolioDailySnapshot).where(PortfolioDailySnapshot.tenant_id == tenant)
    if portfolio_id is not None:
        latest_query = latest_query.where(PortfolioDailySnapshot.portfolio_id == portfolio_id)
    latest = db.scalar(latest_query.order_by(PortfolioDailySnapshot.snapshot_date.desc()).limit(1))
    if latest is None:
        return None
    rows = db.scalars(
        select(PortfolioDailySnapshot)
        .where(
            PortfolioDailySnapshot.tenant_id == tenant,
            PortfolioDailySnapshot.portfolio_id == latest.portfolio_id,
            PortfolioDailySnapshot.snapshot_date > start,
            PortfolioDailySnapshot.snapshot_date <= today,
        )
        .order_by(PortfolioDailySnapshot.snapshot_date)
    ).all()
    returns = [(row.snapshot_date, float(row.daily_return)) for row in rows if row.daily_return is not None]
    if not returns:
        return {"latest": latest, "count": 0}
    index, peak, max_dd = 1.0, 1.0, 0.0
    for _day_, ret in returns:
        index *= 1.0 + ret
        peak = max(peak, index)
        max_dd = min(max_dd, index / peak - 1.0)
    out: dict = {
        "latest": latest,
        "count": len(returns),
        "first": returns[0][0],
        "last": returns[-1][0],
        "twr": index - 1.0,
        "max_drawdown": max_dd,
        "volatility": None,
    }
    if len(returns) >= 20:
        values = [ret for _d, ret in returns]
        mean = sum(values) / len(values)
        var = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
        span_days = max((returns[-1][0] - returns[0][0]).days, 1)
        # Se anualiza con la frecuencia REAL de la serie (snapshots por año),
        # no con 252 supuestas: la serie puede incluir o no fines de semana.
        periods_per_year = len(values) / span_days * 365.25
        out["volatility"] = math.sqrt(var) * math.sqrt(periods_per_year)
    return out


_RISK_ALERT_EN = (
    (re.compile(r"^(?P<t>\S+) supera el 20 % de peso en la cartera$"), "{t} is over 20% of the portfolio"),
    (re.compile(r"^(?P<t>\S+) es pre-FCF y supera el 10 % de peso en la cartera$"),
     "{t} is pre-FCF (no free cash flow yet) and over 10% of the portfolio"),
    (re.compile(r"^El saldo neto de caja, convertido a (?P<c>\S+), es negativo(?: \(saldo negativo en (?P<n>.+)\))?$"),
     "The net cash balance, converted to {c}, is negative"),
    (re.compile(r"^El saldo de caja en (?P<c>\S+) es negativo$"), "The cash balance in {c} is negative"),
)
_SEVERITY_EN = {"critical": "critical", "high": "high", "medium": "medium", "low": "low", "info": "info"}


def _risk_alert_en(message: str) -> str:
    """Mensaje de una regla del panel de riesgo en inglés (las tres reglas fijas)."""
    for pattern, template in _RISK_ALERT_EN:
        match = pattern.match(message)
        if match:
            text = template.format(**{k: v for k, v in match.groupdict().items() if v is not None})
            if match.groupdict().get("n"):
                text += f" (negative balance in {match.group('n')})"
            return text
    return message


def _pct_en(value: float, digits: int = 1) -> str:
    return f"{value * 100:,.{digits}f}%"


def _date_en(value: date | datetime | None) -> str:
    if value is None:
        return "no date"
    return f"{value:%b} {value.day}, {value.year}"


def _history_lines(
    db: Session, tenant: int, today: date | None, english: bool, portfolio_id: int | None
) -> tuple[list[str], list[dict]]:
    """Líneas del histórico (TWR, caída máxima, volatilidad) de UNA cartera."""
    lines: list[str] = []
    sources: list[dict] = []
    metrics = _snapshot_metrics(db, tenant, today=today, portfolio_id=portfolio_id)
    if metrics and metrics.get("count") and english:
        part = (
            f"Portfolio history ({_date_en(metrics['first'])} to {_date_en(metrics['last'])}, "
            f"{metrics['count']} closes): TWR return {_pct_en(metrics['twr'])}, "
            f"max drawdown {_pct_en(metrics['max_drawdown'])}"
        )
        if metrics.get("volatility") is not None:
            part += f", annualized volatility {_pct_en(metrics['volatility'])}"
        lines.append(part + ".")
        coverage = float(metrics["latest"].pricing_coverage or 0)
        if coverage < 1:
            lines.append(f"The latest snapshot has a price for {_pct_en(coverage, 0)} of the portfolio.")
        sources.append(_source("portfolio_snapshot", metrics["latest"].id,
                               f"Portfolio snapshot {_date_en(metrics['latest'].snapshot_date)}", "/portfolio"))
    elif metrics and metrics.get("count"):
        part = (
            f"Histórico de la cartera ({fecha_es(metrics['first'])} a {fecha_es(metrics['last'])}, "
            f"{metrics['count']} cierres): rentabilidad TWR {_pct(metrics['twr'])}, "
            f"caída máxima {_pct(metrics['max_drawdown'])}"
        )
        if metrics.get("volatility") is not None:
            part += f", volatilidad anualizada {_pct(metrics['volatility'])}"
        lines.append(part + ".")
        coverage = float(metrics["latest"].pricing_coverage or 0)
        if coverage < 1:
            lines.append(f"El último snapshot tiene precio para el {_pct(coverage, 0)} de la cartera.")
        sources.append(_source("portfolio_snapshot", metrics["latest"].id,
                               f"Snapshot de cartera {fecha_es(metrics['latest'].snapshot_date)}", "/portfolio"))
    elif metrics is not None and english:
        lines.append("There are portfolio snapshots, but no daily returns: no TWR or max drawdown calculated.")
    elif metrics is not None:
        lines.append("Hay snapshots de la cartera, pero sin rentabilidades diarias: no calculo TWR ni caída máxima.")
    return lines, sources


def portfolio_risk_lines(
    db: Session, tenant: int, *, today: date | None = None, english: bool = False
) -> tuple[list[str], list[dict]]:
    """Reglas del panel de riesgo y métricas del histórico; vacío si no hay datos.

    ``english``: las mismas cifras en inglés (Ajustes → Idioma = English).
    """
    from app.services.risk_service import RiskService

    lines: list[str] = []
    sources: list[dict] = []
    try:
        dashboard = RiskService().dashboard(db)
    except Exception:  # noqa: BLE001 - sin panel se responde con el histórico
        dashboard = None
    if dashboard and dashboard.get("positions"):
        alerts = dashboard.get("alerts") or []
        if alerts and english:
            lines.append("Risk panel rules currently broken:")
            for alert in alerts[:6]:
                severity = _SEVERITY_EN.get(str(alert.get("severity")), str(alert.get("severity")))
                lines.append(f"- {_risk_alert_en(str(alert.get('message')))} (severity {severity}).")
        elif english:
            lines.append("Risk panel: no rule broken (weight > 20%, pre-FCF > 10%, margin).")
        elif alerts:
            lines.append("Reglas del panel de riesgo que se incumplen ahora:")
            for alert in alerts[:6]:
                severity = _SEVERITY_ES.get(str(alert.get("severity")), str(alert.get("severity")))
                lines.append(f"- {alert.get('message')} (gravedad {severity}).")
        else:
            lines.append("Panel de riesgo: ninguna regla incumplida (peso > 20 %, pre-FCF > 10 %, margen).")
        if english:
            lines.append(
                # nosemgrep: gerarai-money-none-to-zero -- texto; dashboard trae siempre los pesos cuando hay posiciones (risk_service)
                f"Concentration: the largest position weighs {_pct_en(float(dashboard.get('top_1_weight') or 0))} "
                # nosemgrep: gerarai-money-none-to-zero -- texto; dashboard trae siempre los pesos cuando hay posiciones (risk_service)
                f"and the top 5 {_pct_en(float(dashboard.get('top_5_weight') or 0))}."
            )
        else:
            lines.append(
                # nosemgrep: gerarai-money-none-to-zero -- contexto de texto para el LLM; dashboard trae siempre los pesos cuando hay posiciones (risk_service)
                f"Concentración: la mayor posición pesa {_pct(float(dashboard.get('top_1_weight') or 0))} "
                # nosemgrep: gerarai-money-none-to-zero -- contexto de texto para el LLM; dashboard trae siempre los pesos cuando hay posiciones (risk_service)
                f"y las 5 mayores {_pct(float(dashboard.get('top_5_weight') or 0))}."
            )
        if dashboard.get("status") not in (None, "ok") and english:
            lines.append("Note: the panel is incomplete (missing exchange rate or suspended valuations).")
        elif dashboard.get("status") not in (None, "ok"):
            lines.append("Ojo: el panel está incompleto (falta tipo de cambio o hay valoraciones en suspenso).")
        sources.append(_source("risk_dashboard", "dashboard",
                               f"Risk panel (data as of {dashboard.get('data_as_of') or 'N/A'})" if english else
                               f"Panel de riesgo (datos a {dashboard.get('data_as_of') or 'N/D'})", "/risk"))
    # Cada cartera con su histórico: con varias, antes solo se describía la de
    # la foto más reciente de cualquiera, como si fuera toda tu cartera.
    portfolio_ids = sorted(db.scalars(
        select(PortfolioDailySnapshot.portfolio_id).where(PortfolioDailySnapshot.tenant_id == tenant).distinct()
    ).all())
    if len(portfolio_ids) <= 1:
        history, history_sources = _history_lines(db, tenant, today, english, None)
        lines.extend(history)
        sources.extend(history_sources)
        return lines, sources
    from app.models import Portfolio

    names = dict(db.execute(
        select(Portfolio.id, Portfolio.name).where(Portfolio.tenant_id == tenant, Portfolio.id.in_(portfolio_ids))
    ).all())
    lines.append(f"You have {len(portfolio_ids)} portfolios with daily snapshots; each one separately:" if english
                 else f"Tienes {len(portfolio_ids)} carteras con fotos diarias; cada una por separado:")
    for portfolio_id in portfolio_ids:
        history, history_sources = _history_lines(db, tenant, today, english, portfolio_id)
        if history:
            lines.append(f"- «{names.get(portfolio_id) or portfolio_id}»: " + " ".join(history))
        sources.extend(history_sources)
    return lines, sources


def portfolio_risk_answer(db: Session, tenant: int, *, today: date | None = None) -> ChatResponse:
    lines, sources = portfolio_risk_lines(db, tenant, today=today)
    if not lines:
        return _response(["No tengo posiciones valoradas ni snapshots de tu cartera: no hay riesgo que calcular."],
                         [], "portfolio_risk")
    lines.append("Son cifras calculadas sobre lo guardado; no son una recomendación.")
    return _response(lines, sources, "portfolio_risk")


# ---------------------------------------------------------------- diario


def journal_answer(db: Session, tenant: int, company: Company | None = None) -> ChatResponse:
    """Últimas entradas del diario de decisiones (abiertas primero)."""
    from app.services.brain_account_tools import _date_en, _english

    english = _english()
    query = (
        select(DecisionJournalEntry, Company)
        .join(Company, Company.id == DecisionJournalEntry.company_id)
        .where(DecisionJournalEntry.tenant_id == tenant)
    )
    if company is not None:
        query = query.where(DecisionJournalEntry.company_id == company.id)
    rows = db.execute(
        query.order_by(DecisionJournalEntry.decision_date.desc(), DecisionJournalEntry.id.desc()).limit(40)
    ).all()
    if english:
        scope = f" for {company.ticker}" if company is not None else ""
    else:
        scope = f" de {company.ticker}" if company is not None else ""
    if not rows:
        return _response([f"There are no entries in your decision journal{scope}." if english
                          else f"No hay entradas en tu diario de decisiones{scope}."], [], "decision_journal")
    open_rows = [row for row in rows if row[0].status == "open"]
    opened, total = len(open_rows), len(rows)
    if english:
        latest = "the only one recorded" if total == 1 else f"the last {total} recorded"
        lines = [f"Decision journal{scope}: {opened} open of {latest}."]
    else:
        latest = "la única registrada" if total == 1 else f"las últimas {total} registradas"
        lines = [f"Diario de decisiones{scope}: {opened} abierta{'' if opened == 1 else 's'} de {latest}."]
    sources: list[dict] = []
    for entry, comp in (open_rows + [row for row in rows if row[0].status != "open"])[:6]:
        rationale = " ".join((entry.rationale or "").split())
        if len(rationale) > 140:
            rationale = rationale[:137].rstrip() + "…"
        must = [item for item in (entry.what_must_be_true or []) if str(item).strip()]
        if english:
            price = f" at {float(entry.price):,.2f}" if entry.price is not None else ""
            line = (f"- {comp.ticker}, {_date_en(entry.decision_date)}: {entry.decision.lower()}{price} "
                    f"({entry.status}).")
            if rationale:
                line += f" Reason: {rationale}"
            if must:
                line += f" Must hold true: {len(must)} condition{'' if len(must) == 1 else 's'}."
        else:
            decision = _DECISION_ES.get(entry.decision.lower(), entry.decision)
            price = f" a {float(entry.price):.2f}".replace(".", ",") if entry.price is not None else ""
            status = "abierta" if entry.status == "open" else entry.status
            line = f"- {comp.ticker}, {fecha_es(entry.decision_date)}: {decision}{price} ({status})."
            if rationale:
                line += f" Motivo: {rationale}"
            if must:
                line += f" Debe cumplirse: {len(must)} condición(es)."
        lines.append(line)
        sources.append(_source(
            "decision_journal_entry", entry.id,
            f"{'Journal' if english else 'Diario'} {comp.ticker} "
            f"{_date_en(entry.decision_date) if english else fecha_es(entry.decision_date)}",
            f"/research/{quote(comp.ticker, safe='')}/decision-lessons",
        ))
    return _response(lines, sources, "decision_journal")


# ---------------------------------------------------------------- nivel DCA

_DCA_RE = re.compile(r"(?i)\bdca\b|\bniveles?\s+de\s+(?:compra|entrada)\b|\bzona\s+de\s+compra\b")


def _fmt_close(value: float | None, currency: str | None) -> str:
    if value is None:
        return "N/D"
    text = f"{value:,.2f}".replace(",", "\x07").replace(".", ",").replace("\x07", ".")
    return f"{text} {currency}".strip() if currency else text


def _dca_stale_age(signal_date: date | None, today: date) -> int | None:
    """Días del último cierre si pasa el mismo límite que la watchlist (``dca_max_data_age_days``)."""
    from app.core.config import get_settings

    if signal_date is None:
        return None
    age = max((today - signal_date).days, 0)
    return age if age > int(get_settings().dca_max_data_age_days) else None


def _dca_max_age_days() -> int:
    from app.core.config import get_settings

    return int(get_settings().dca_max_data_age_days)


def dca_answer(db: Session, tenant: int, company: Company | None, *, today: date | None = None) -> ChatResponse:
    """Nivel DCA guardado (último veredicto del motor); «sin nivel» si no hay.

    Un nivel con el último cierre demasiado viejo (motor parado, ticker que ya
    no se evalúa) se dice como tal: la watchlist lo marca «desactualizado» y el
    Cerebro no puede darlo como el nivel de hoy.
    """
    from zoneinfo import ZoneInfo

    from app.services.dca_level_reader import read_dca_levels

    today = today or datetime.now(ZoneInfo("America/New_York")).date()

    symbols = [company.ticker] if company is not None else None
    levels = read_dca_levels(db, tenant, symbols)
    if levels is None:
        return _response([
            "Sin nivel DCA: el motor de niveles DCA todavía no está activo en esta instalación, "
            "así que no tengo ningún nivel guardado que darte. No lo calculo a ojo."
        ], [], "dca_level")
    if company is not None:
        reading = levels.get(company.ticker.upper())
        if reading is None:
            return _response([f"{company.ticker}: sin nivel DCA guardado todavía (no está evaluado)."], [], "dca_level")
        state = "mes en formación, se confirma al cierre" if reading.forming else "mes cerrado"
        lines = [
            f"**{reading.symbol}: {reading.label}** ({reading.zone}).",
            f"Cierre usado {_fmt_close(reading.close, reading.currency)} del {_day(reading.signal_date)}; {state}.",
            "Es la lectura de tu fórmula DCA, no una orden de compra.",
        ]
        stale_age = _dca_stale_age(reading.signal_date, today)
        if stale_age is not None:
            lines.insert(1, f"Ojo: desactualizado, el último cierre es de hace {stale_age} días; "
                            "puede no ser el nivel de hoy.")
        return _response(lines, [_source("dca_signal", reading.symbol, f"Nivel DCA {reading.symbol}",
                                         "/watchlist")], "dca_level")
    if not levels:
        return _response(["Sin nivel DCA: todavía no hay ningún ticker evaluado."], [], "dca_level")
    by_level: dict[int, list[str]] = {}
    labels: dict[int, str] = {}
    for reading in levels.values():
        by_level.setdefault(reading.level, []).append(reading.symbol)
        labels[reading.level] = reading.label
    lines = ["Niveles DCA guardados (último veredicto de tu fórmula):"]
    for level in sorted(by_level, key=lambda lv: (lv < 0, -lv)):
        lines.append(f"- {labels[level]}: {', '.join(sorted(by_level[level]))}.")
    forming = sum(1 for reading in levels.values() if reading.forming)
    if forming:
        lines.append(f"{forming} con el mes aún en formación: se confirman al cierre del mes.")
    stale = sorted(r.symbol for r in levels.values() if _dca_stale_age(r.signal_date, today) is not None)
    if stale:
        lines.append(f"Desactualizados (último cierre de hace más de "
                     f"{_dca_max_age_days()} días, pueden no ser el nivel de hoy): {', '.join(stale)}.")
    lines.append("Es la lectura de tu fórmula DCA, no una orden de compra.")
    return _response(lines, [_source("dca_signal", "all", "Niveles DCA", "/watchlist")], "dca_level")


# ---------------------------------------------------------------- valoración del motor

_ENGINE_RE = re.compile(
    r"(?i)\b(?:valor\s+(?:justo|intr[ií]nseco|razonable)|valoraci[oó]n\s+del\s+motor|motor\s+de\s+valoraci[oó]n|"
    r"dcf|infravalorad\w*|sobrevalorad\w*)\b"
)


def engine_valuation_answer(db: Session, company: Company) -> ChatResponse:
    """Salida del motor de valoración (escenarios, margen, publicable) sin LLM."""
    from app.services.valuation_service import ValuationService

    try:
        result = ValuationService().value_company(db, company)
    except Exception:  # noqa: BLE001 - un motor caído se dice, no se inventa
        return _response([f"El motor de valoración no ha podido valorar {company.ticker} ahora mismo."],
                         [], "engine_valuation")
    ccy = company.currency
    link = f"/research/{quote(company.ticker, safe='')}?view=valuation"
    # Los motores valoran por accion ORDINARIA; el precio de un ADR es por ADR
    # (N ordinarias). Junto al «Precio usado» del ADR van los escenarios por
    # ADR (listed_share_values); antes salia base 25 USD frente a un precio de
    # 160 USD con margen +25 % (BABA 8:1), cifras imposibles de cuadrar.
    ratio = result.get("adr_ratio")
    listed = result.get("listed_share_values") if isinstance(result.get("listed_share_values"), dict) else None
    keys = (("bajista", "bear_value", "bear"), ("base", "base_value", "base"),
            ("alcista", "bull_value", "bull"), ("esperado", "expected_value", "expected"))
    if ratio and listed:
        values = [(label, listed.get(short)) for label, _key, short in keys]
        basis = f"Escenarios por ADR (1 ADR = {f"{float(ratio):g}".replace(".", ",")} acciones ordinarias): "
    else:
        values = [(label, result.get(key)) for label, key, _short in keys]
        basis = ("Escenarios por acción ordinaria (el precio cotizado es por ADR): " if ratio
                 else "Escenarios por acción: ")
    values = [(label, value) for label, value in values if value is not None]
    if not values:
        missing = ", ".join(result.get("missing_inputs") or []) or "datos suficientes"
        return _response([f"El motor no tiene valoración de {company.ticker}: faltan {missing}."],
                         [_source("valuation", company.ticker, f"Valoración {company.ticker}", link)],
                         "engine_valuation")
    publishable = bool(result.get("publishable"))
    head = (f"**Motor de valoración · {company.ticker}** ({result.get('model_type') or 'modelo'}"
            f"{'' if publishable else ', orientativo: algún input no tiene fuente datada'}).")
    lines = [head, basis + ", ".join(f"{label} {_fmt_close(float(value), ccy)}"
                                                        for label, value in values) + "."]
    price = result.get("current_price")
    as_of = (result.get("trace") or {}).get("price_as_of")
    if price is not None:
        lines.append(f"Precio usado {_fmt_close(float(price), ccy)}"
                     f"{f' (cierre del {as_of})' if as_of else ''}; no es una cotización en directo.")
    mos = result.get("margin_of_safety")
    if mos is not None:
        lines.append(f"Margen de seguridad del motor: {_pct(float(mos))}.")
    blockers = result.get("publication_blockers") or []
    if blockers and not publishable:
        lines.append("Por qué no es publicable: " + "; ".join(str(b) for b in blockers[:3]) + ".")
    lines.append("Es la salida del modelo, no una recomendación.")
    return _response(lines, [_source("valuation", company.ticker, f"Valoración {company.ticker}", link)],
                     "engine_valuation")


# ------------------------------------------------------- propicks / radar / salud

_PROPICKS_RE = re.compile(r"(?i)\bpropicks?\b")
_RADAR_RE = re.compile(r"(?i)\bradar\b")
_SOURCE_HEALTH_RE = re.compile(
    r"(?i)salud\s+de\s+(?:las\s+)?fuentes|estado\s+de\s+(?:las\s+)?fuentes|"
    r"fuentes\s+de\s+datos|c[oó]mo\s+(?:van|est[aá]n)\s+las\s+fuentes"
)
_LAYER_STATUS_ES = {"available": "al día", "stale": "desactualizada", "empty": "vacía", "error": "error de lectura"}


def propicks_answer(db: Session, tenant: int) -> ChatResponse:
    """Último run guardado del funnel ProPicks: ganadores con score y fecha."""
    from app.models.entities import ProPickCandidate, ProPickRun

    # Solo runs COMPLETADOS: uno en curso todavia no tiene ganadores y decir
    # "ninguno paso" seria falso. Si el mas reciente esta en curso, se dice.
    run = db.scalars(
        select(ProPickRun)
        .where(ProPickRun.tenant_id == tenant, ProPickRun.status == "completed")
        .order_by(ProPickRun.as_of.desc())
        .limit(1)
    ).first()
    latest_any = db.scalars(
        select(ProPickRun)
        .where(ProPickRun.tenant_id == tenant)
        .order_by(ProPickRun.as_of.desc())
        .limit(1)
    ).first()
    in_progress_note = None
    if latest_any is not None and (run is None or latest_any.id != run.id):
        in_progress_note = (
            f"El run más reciente ({_day(latest_any.as_of)}) está en estado "
            f"«{latest_any.status}» y aún no tiene resultado; muestro el último completado."
        )
    if run is None:
        lines = ["Todavía no hay ningún run de ProPicks completado; no invento candidatos."]
        if in_progress_note:
            lines.append(in_progress_note)
        return _response(lines, [], "propicks")
    when = _day(run.as_of)
    sources = [_source("propick_run", run.id, f"Run ProPicks {when}", "/propicks")]
    rows = db.execute(
        select(ProPickCandidate, Company)
        .join(Company, Company.id == ProPickCandidate.company_id)
        .where(ProPickCandidate.run_id == run.id, ProPickCandidate.passed.is_(True))
        .order_by(ProPickCandidate.rank)
        .limit(8)
    ).all()
    if not rows:
        return _response([
            f"Último run de ProPicks ({when}): {run.universe_size} valores analizados "
            "y ninguno pasó todos los filtros.",
        ], sources, "propicks")
    lines = [
        f"Último run de ProPicks ({when}): {run.passed_count} de {run.universe_size} "
        "valores pasan el funnel. Mejor puntuados:",
    ]
    for cand, comp in rows:
        score = f"{float(cand.score):.1f}".replace(".", ",") if cand.score is not None else "s/p"
        lines.append(f"- {comp.ticker}: score {score}.")
        sources.append(_source("propick_candidate", cand.id, f"ProPick {comp.ticker}", "/propicks"))
    if in_progress_note:
        lines.append(in_progress_note)
    lines.append("Es la salida guardada de tu funnel determinista, no una recomendación de compra.")
    return _response(lines, sources, "propicks")


def radar_answer(db: Session) -> ChatResponse:
    """Señales claras del radar de precio (snapshots guardados, fórmula nico-v2)."""
    from app.services.propicks_radar_store import latest_public_signals

    # Misma fecha de corte que GET /radar/opportunities (date.today()).
    today = date.today()
    signals = latest_public_signals(db, as_of=today)
    if not signals:
        return _response([
            "El radar no tiene snapshots guardados todavía (el escaneo no ha corrido "
            "o no cubre ningún valor). No lo simulo en directo.",
        ], [], "radar")
    # Misma vigencia que GET /radar/opportunities: solo lecturas ok con
    # escaneo de como mucho STALE_SCAN_DAYS dias; lo viejo o invalido se
    # cuenta y se dice, nunca se anuncia como señal de hoy.
    from app.api.routes.propicks_radar import STALE_SCAN_DAYS

    valid: list[dict] = []
    stale_count = 0
    invalid_count = 0
    for sig in signals:
        payload = sig["payload"] or {}
        if payload.get("status") != "ok":
            invalid_count += 1
            continue
        try:
            scan_date = date.fromisoformat(sig["scan_date"])
        except ValueError:
            invalid_count += 1
            continue
        if (today - scan_date).days > STALE_SCAN_DAYS:
            stale_count += 1
            continue
        valid.append(sig)
    exclusions = []
    if stale_count:
        exclusions.append(
            f"{stale_count} con escaneo de más de {STALE_SCAN_DAYS} días (sin corrida nueva, no vigentes)"
        )
    if invalid_count:
        exclusions.append(f"{invalid_count} con lectura inválida")
    exclusion_line = "Descartados: " + "; ".join(exclusions) + "." if exclusions else None
    if not valid:
        lines = [
            f"Radar de precio: ninguna lectura vigente a día de hoy "
            f"({len(signals)} valores con snapshot guardado, todos descartados)."
        ]
        if exclusion_line:
            lines.append(exclusion_line)
        return _response(lines, [], "radar")
    clear = [s for s in valid if (s["payload"] or {}).get("clear_price_signal")]
    tickers = {
        row.id: row.ticker
        for row in db.scalars(select(Company).where(Company.id.in_({s["company_id"] for s in valid}))).all()
    }
    scan_day = max(s["scan_date"] for s in valid)
    sources = [_source("radar_snapshot", "latest", f"Radar {scan_day}", "/propicks")]
    if not clear:
        lines = [
            f"Radar de precio (escaneo guardado del {_day(scan_day)}, {len(valid)} valores vigentes): "
            "ninguno tiene señal clara (nivel 4 confirmado y verificado) ahora mismo.",
        ]
        if exclusion_line:
            lines.append(exclusion_line)
        return _response(lines, sources, "radar")
    lines = [
        f"Radar de precio (escaneo guardado del {_day(scan_day)}): "
        f"{len(clear)} valores con señal clara (nivel 4 confirmado):",
    ]
    if exclusion_line:
        lines.append(exclusion_line)
    for sig in clear[:8]:
        payload = sig["payload"] or {}
        ticker = tickers.get(sig["company_id"], str(sig["company_id"]))
        dd = payload.get("daily_close_drawdown")
        dd_txt = f", caída {float(dd) * 100:.1f} % desde el máximo".replace(".", ",") if dd is not None else ""
        lines.append(f"- {ticker}{dd_txt}.")
        sources.append(_source("radar_snapshot", sig["company_id"], f"Radar {ticker}", "/propicks"))
    lines.append("Es la lectura guardada del radar, no una orden de compra.")
    return _response(lines, sources, "radar")


def source_health_answer(db: Session, tenant: int) -> ChatResponse:
    """Salud de las fuentes: estado por capa y conectores con problemas."""
    from app.services.data_health_service import read_inventory

    try:
        inv = read_inventory(db)
    except Exception:  # noqa: BLE001 - la lectura rota se dice, no se inventa
        db.rollback()
        return _response(["No se pudo leer el inventario de fuentes ahora mismo."], [], "source_health")
    by_layer: dict[str, list[dict]] = {}
    for row in inv["sources"]:
        by_layer.setdefault(row["layer"], []).append(row)
    lines = ["Salud de las fuentes de datos (última escritura guardada en cada capa):"]
    for layer, rows in by_layer.items():
        counts: dict[str, int] = {}
        for row in rows:
            counts[row["status"]] = counts.get(row["status"], 0) + 1
        detail = ", ".join(
            f"{_LAYER_STATUS_ES.get(status, status)} {count}" for status, count in sorted(counts.items())
        )
        line = f"- {layer}: {detail}."
        review = sorted({row["source"] or "sin fuente" for row in rows if row["status"] in ("stale", "empty", "error")})
        if review:
            line += f" Revisar: {', '.join(review[:4])}."
        lines.append(line)
    bad = [c for c in inv["connectors"] if c["status"] in ("degraded", "error")]
    if bad:
        lines.append("Conectores con problemas: " + ", ".join(c["source"] for c in bad[:5]) + ".")
    lines.append("Mide la última escritura en la BD, no si el proveedor sigue disponible.")
    return _response(lines, [], "source_health")


# ---------------------------------------------------------------- router


def answer_context_question(
    db: Session,
    question: str,
    tenant: int,
    resolve_company: Callable[[], Company | None],
) -> ChatResponse | None:
    """None si la pregunta no es de nivel DCA, valoración, avisos, riesgo o diario.

    ``resolve_company`` solo se llama cuando la pregunta es de este módulo
    (recorre el catálogo para acotar a la empresa nombrada).
    """
    # «nivel/zona de compra» nombra el nivel DCA, no es una orden de compra.
    if _ORDER_RE.search(_DCA_RE.sub(" ", question)):
        return None
    if _DCA_RE.search(question):
        return dca_answer(db, tenant, resolve_company())
    # La tesis tiene su propia respuesta (margen/escenarios PUBLICADOS).
    if _ENGINE_RE.search(question) and not re.search(r"(?i)\btesis\b", question):
        company = resolve_company()
        if company is not None:
            return engine_valuation_answer(db, company)
    if _RISK_METRIC_RE.search(question):
        return portfolio_risk_answer(db, tenant)
    if _JOURNAL_RE.search(question):
        return journal_answer(db, tenant, resolve_company())
    if _ALERTS_RE.search(question) and not _ALERT_ACTION_RE.search(question):
        return alerts_answer(db, tenant, resolve_company())
    if _PROPICKS_RE.search(question):
        return propicks_answer(db, tenant)
    if _RADAR_RE.search(question):
        return radar_answer(db)
    if _SOURCE_HEALTH_RE.search(question):
        return source_health_answer(db, tenant)
    return None


__all__ = [
    "alerts_answer",
    "dca_answer",
    "engine_valuation_answer",
    "answer_context_question",
    "journal_answer",
    "portfolio_risk_answer",
    "portfolio_risk_lines",
    "propicks_answer",
    "radar_answer",
    "source_health_answer",
]
