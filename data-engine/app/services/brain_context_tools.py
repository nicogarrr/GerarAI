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
    r"borra\w*|elimina\w*|silencia\w*|posp[oó]n\w*)\b"
)
_ALERTS_RE = re.compile(r"(?i)\b(?:avisos?|alertas?)\b")
_RISK_METRIC_RE = re.compile(
    r"(?i)\b(?:drawdown|ca[ií]da\s+m[aá]xima|volatilidad|twr|panel\s+de\s+riesgo|"
    r"(?:avisos?|alertas?|reglas?|l[ií]mites?)\s+de\s+riesgo)\b"
)
_JOURNAL_RE = re.compile(
    r"(?i)\bdiario\b|\b(?:mis|[uú]ltimas|qu[eé])\s+decisiones\b|\bdecisiones\s+(?:que\s+)?(?:he|tom[eé]|registr\w*)"
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

    scope = f" de {company.ticker}" if company is not None else ""
    lines: list[str] = []
    sources: list[dict] = []
    if visible:
        lines.append(f"Avisos abiertos{scope}: {len(visible)} (los más recientes primero).")
        for alert, comp in visible[:8]:
            ticker = f"{comp.ticker}: " if comp is not None else ""
            when = _day(alert.last_triggered_at or alert.created_at)
            severity = _SEVERITY_ES.get(alert.severity, alert.severity)
            lines.append(f"- {ticker}{alert.title} (gravedad {severity}, {when}).")
            sources.append(_source("research_alert", alert.id, f"Aviso: {alert.title}", "/alerts"))
        if len(visible) > 8:
            lines.append(f"Y {len(visible) - 8} más en la página de avisos.")
    else:
        lines.append(f"No hay avisos abiertos{scope}.")
    if snoozed:
        lines.append(f"Pospuestos ahora mismo: {snoozed}.")
    if rules:
        by_type: dict[str, int] = {}
        for rule, _comp in rules:
            by_type[rule.rule_type] = by_type.get(rule.rule_type, 0) + 1
        detail = ", ".join(f"{kind} {count}" for kind, count in sorted(by_type.items()))
        lines.append(f"Reglas de aviso activas{scope}: {len(rules)} ({detail}).")
        triggered = [(rule, comp) for rule, comp in rules if rule.last_triggered_at is not None]
        triggered.sort(key=lambda row: _aware(row[0].last_triggered_at) or now, reverse=True)
        for rule, comp in triggered[:3]:
            lines.append(f"- Última vez que saltó «{rule.name}» ({comp.ticker}): {_day(rule.last_triggered_at)}.")
            sources.append(_source("alert_rule", rule.id, f"Regla: {rule.name}", "/alerts"))
    else:
        lines.append(f"No hay reglas de aviso activas{scope}.")
    return _response(lines, sources, "alerts")


# ---------------------------------------------------------------- riesgo


def _snapshot_metrics(db: Session, tenant: int, *, today: date | None = None) -> dict | None:
    """TWR, caída máxima y volatilidad de los últimos 12 meses de snapshots diarios."""
    today = today or date.today()
    start = today - timedelta(days=365)
    latest = db.scalar(
        select(PortfolioDailySnapshot)
        .where(PortfolioDailySnapshot.tenant_id == tenant)
        .order_by(PortfolioDailySnapshot.snapshot_date.desc())
        .limit(1)
    )
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


def portfolio_risk_lines(db: Session, tenant: int, *, today: date | None = None) -> tuple[list[str], list[dict]]:
    """Reglas del panel de riesgo y métricas del histórico; vacío si no hay datos."""
    from app.services.risk_service import RiskService

    lines: list[str] = []
    sources: list[dict] = []
    try:
        dashboard = RiskService().dashboard(db)
    except Exception:  # noqa: BLE001 - sin panel se responde con el histórico
        dashboard = None
    if dashboard and dashboard.get("positions"):
        alerts = dashboard.get("alerts") or []
        if alerts:
            lines.append("Reglas del panel de riesgo que se incumplen ahora:")
            for alert in alerts[:6]:
                severity = _SEVERITY_ES.get(str(alert.get("severity")), str(alert.get("severity")))
                lines.append(f"- {alert.get('message')} (gravedad {severity}).")
        else:
            lines.append("Panel de riesgo: ninguna regla incumplida (peso > 20 %, pre-FCF > 10 %, margen).")
        lines.append(
            # nosemgrep: gerarai-money-none-to-zero -- contexto de texto para el LLM; dashboard trae siempre los pesos cuando hay posiciones (risk_service)
            f"Concentración: la mayor posición pesa {_pct(float(dashboard.get('top_1_weight') or 0))} "
            # nosemgrep: gerarai-money-none-to-zero -- contexto de texto para el LLM; dashboard trae siempre los pesos cuando hay posiciones (risk_service)
            f"y las 5 mayores {_pct(float(dashboard.get('top_5_weight') or 0))}."
        )
        if dashboard.get("status") not in (None, "ok"):
            lines.append("Ojo: el panel está incompleto (falta tipo de cambio o hay valoraciones en suspenso).")
        sources.append(_source("risk_dashboard", "dashboard",
                               f"Panel de riesgo (datos a {dashboard.get('data_as_of') or 'N/D'})", "/risk"))
    metrics = _snapshot_metrics(db, tenant, today=today)
    if metrics and metrics.get("count"):
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
    elif metrics is not None:
        lines.append("Hay snapshots de la cartera, pero sin rentabilidades diarias: no calculo TWR ni caída máxima.")
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
    scope = f" de {company.ticker}" if company is not None else ""
    if not rows:
        return _response([f"No hay entradas en tu diario de decisiones{scope}."], [], "decision_journal")
    open_rows = [row for row in rows if row[0].status == "open"]
    lines = [f"Diario de decisiones{scope}: {len(open_rows)} abiertas de las últimas {len(rows)} registradas."]
    sources: list[dict] = []
    for entry, comp in (open_rows + [row for row in rows if row[0].status != "open"])[:6]:
        decision = _DECISION_ES.get(entry.decision.lower(), entry.decision)
        price = f" a {float(entry.price):.2f}".replace(".", ",") if entry.price is not None else ""
        rationale = " ".join((entry.rationale or "").split())
        if len(rationale) > 140:
            rationale = rationale[:137].rstrip() + "…"
        status = "abierta" if entry.status == "open" else entry.status
        line = f"- {comp.ticker}, {fecha_es(entry.decision_date)}: {decision}{price} ({status})."
        if rationale:
            line += f" Motivo: {rationale}"
        must = [item for item in (entry.what_must_be_true or []) if str(item).strip()]
        if must:
            line += f" Debe cumplirse: {len(must)} condición(es)."
        lines.append(line)
        sources.append(_source(
            "decision_journal_entry", entry.id, f"Diario {comp.ticker} {fecha_es(entry.decision_date)}",
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
    return None


__all__ = [
    "alerts_answer",
    "dca_answer",
    "engine_valuation_answer",
    "answer_context_question",
    "journal_answer",
    "portfolio_risk_answer",
    "portfolio_risk_lines",
]
