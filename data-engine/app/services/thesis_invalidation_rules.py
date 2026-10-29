"""Criterios de invalidacion ESTRUCTURADOS de una tesis (medibles).

Los criterios de ``ThesisVersion.invalidation_criteria`` son texto libre: nadie
los puede evaluar. Esta capa anade criterios opcionales ``{metric, operator,
threshold}`` en ``ThesisVersion.invalidation_rules`` y los sincroniza como
``AlertRule(rule_type="thesis_invalidation")``. Asi el evaluador de alertas
existente (``AlertRuleService.evaluate_all``: cooldown, entrega por los canales
de la regla, huella por ocurrencia) los comprueba en cada pasada y avisa cuando
uno salta. No hay un segundo evaluador.

Metricas soportadas:

- ``precio``: ultimo cierre de ``MarketPrice`` (caducado => no dispara).
- ``margen_seguridad_pct``: ``(valor_esperado_tesis / precio - 1) * 100``. Mismo
  benchmark que ``ThesisVersion.margin_of_safety`` (valor ESPERADO de la tesis),
  pero con el precio de hoy.
- ``variacion_desde_tesis_pct``: ``(precio / precio_en_la_tesis - 1) * 100``.
- ``metrica:<nombre>``: ultimo ``CalculatedMetric`` con ese nombre (ejercicio
  mas reciente) y, si no hay, ultimo ``FinancialFact``. El umbral va en la
  unidad de la metrica (p. ej. ROIC 0,08 = 8 %).

Sin dato no dispara nunca: la observacion queda como ``missing``.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import (
    AlertRule,
    CalculatedMetric,
    Company,
    FinancialFact,
    MarketPrice,
    ThesisVersion,
)
from app.services.claim_scope import latest_thesis_version

RULE_TYPE = "thesis_invalidation"
TARGET_KIND = "thesis_metric"
MAX_RULES = 20
# Un criterio de invalidacion se mueve despacio: como mucho un aviso al dia
# mientras siga cumpliendose (el cooldown del evaluador existente).
COOLDOWN_SECONDS = 86_400

PRICE = "precio"
MARGIN_OF_SAFETY_PCT = "margen_seguridad_pct"
CHANGE_SINCE_THESIS_PCT = "variacion_desde_tesis_pct"
METRIC_PREFIX = "metrica:"

METRIC_LABELS: dict[str, str] = {
    PRICE: "precio",
    MARGIN_OF_SAFETY_PCT: "margen de seguridad",
    CHANGE_SINCE_THESIS_PCT: "variación desde la tesis",
}
PERCENT_METRICS = frozenset({MARGIN_OF_SAFETY_PCT, CHANGE_SINCE_THESIS_PCT})
OPERATORS = frozenset({">", "<", ">=", "<=", "==", "!="})
_OPERATOR_TEXT = {">": ">", "<": "<", ">=": "≥", "<=": "≤", "==": "=", "!=": "≠"}


def _parse_threshold(value: Any) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = Decimal(str(value).strip().replace(",", "."))
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _valid_metric(metric: str) -> bool:
    if metric in METRIC_LABELS:
        return True
    if metric.startswith(METRIC_PREFIX):
        name = metric[len(METRIC_PREFIX):].strip()
        return 0 < len(name) <= 120
    return False


def normalize_rules(raw: Any) -> list[dict[str, Any]]:
    """Valida y normaliza criterios estructurados. ValueError con texto en espanol."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("Los criterios de invalidación deben ser una lista.")
    if len(raw) > MAX_RULES:
        raise ValueError(f"Máximo {MAX_RULES} criterios de invalidación por tesis.")
    rules: list[dict[str, Any]] = []
    seen: set[tuple[str, str, Decimal]] = set()
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Criterio {index}: formato no válido (métrica, operador y umbral).")
        metric = str(item.get("metric") or "").strip()
        if not _valid_metric(metric):
            raise ValueError(f"Criterio {index}: métrica no soportada «{metric}».")
        operator = str(item.get("operator") or "").strip()
        if operator not in OPERATORS:
            raise ValueError(f"Criterio {index}: operador no válido «{operator}».")
        threshold = _parse_threshold(item.get("threshold"))
        if threshold is None:
            raise ValueError(f"Criterio {index}: el umbral debe ser un número finito.")
        key = (metric, operator, threshold.normalize())
        if key in seen:
            continue
        seen.add(key)
        description = str(item.get("description") or "").strip()[:300] or None
        rules.append({
            "metric": metric,
            "operator": operator,
            "threshold": float(threshold),
            "description": description,
        })
    return rules


def _lenient_rules(raw: Any) -> list[dict[str, Any]]:
    """Criterios guardados: descarta los corruptos de uno en uno, sin romper la pasada."""
    if not isinstance(raw, list):
        return []
    rules: list[dict[str, Any]] = []
    for item in raw:
        try:
            rules.extend(normalize_rules([item]))
        except ValueError:
            continue
    return rules


def metric_label(metric: str) -> str:
    if metric.startswith(METRIC_PREFIX):
        return metric[len(METRIC_PREFIX):].strip()
    return METRIC_LABELS.get(metric, metric)


def format_es(value: Any, *, percent: bool = False) -> str:
    """Numero en formato es-ES (coma decimal, punto de miles)."""
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return str(value)
    text = f"{number:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
    return f"{text} %" if percent else text


def describe_rule(rule: dict[str, Any]) -> str:
    metric = str(rule.get("metric") or "")
    percent = metric in PERCENT_METRICS
    return (
        f"{metric_label(metric)} {_OPERATOR_TEXT.get(str(rule.get('operator')), rule.get('operator'))} "
        f"{format_es(rule.get('threshold'), percent=percent)}"
    )


def _rule_name(company: Company, rule: dict[str, Any]) -> str:
    return f"{company.ticker}: invalidación de tesis · {describe_rule(rule)}"[:300]


def latest_thesis(db: Session, company_id: int) -> ThesisVersion | None:
    return latest_thesis_version(db, company_id)


def sync_thesis_rules(db: Session, company: Company) -> list[AlertRule]:
    """Refleja los criterios de la ultima tesis en AlertRule. No hace commit.

    Solo toca reglas ``thesis_invalidation``: las reglas de precio/noticias que
    crea el usuario quedan intactas. Un criterio que desaparece de la tesis se
    desactiva (no se borra: conserva su historial de disparos).
    """
    thesis = latest_thesis(db, company.id)
    desired = _lenient_rules(thesis.invalidation_rules) if thesis is not None else []
    existing = {
        rule.name: rule
        for rule in db.scalars(
            select(AlertRule).where(
                AlertRule.company_id == company.id,
                AlertRule.rule_type == RULE_TYPE,
            )
        ).all()
    }
    settings = get_settings()
    channels = ["in_app"]
    if settings.telegram_enabled and settings.telegram_bot_token and settings.telegram_chat_id:
        channels.append("telegram")
    active: list[AlertRule] = []
    wanted_names: set[str] = set()
    for item in desired:
        name = _rule_name(company, item)
        wanted_names.add(name)
        rule = existing.get(name)
        if rule is None:
            rule = AlertRule(company_id=company.id, name=name, trigger_count=0)
            rule.channels = list(channels)
            rule.cooldown_seconds = COOLDOWN_SECONDS
            db.add(rule)
        assert thesis is not None
        rule.rule_type = RULE_TYPE
        rule.condition = {"operator": item["operator"], "value": item["threshold"]}
        rule.target = {
            "kind": TARGET_KIND,
            "metric": item["metric"],
            "thesis_version_id": thesis.id,
            "thesis_version": thesis.version,
            "description": item["description"],
        }
        rule.severity = "high"
        rule.active = True
        rule.metadata_ = {"ticker": company.ticker, "source": "thesis"}
        active.append(rule)
    for name, rule in existing.items():
        if name not in wanted_names and rule.active:
            rule.active = False
    db.flush()
    return active


def sync_all_thesis_rules(db: Session) -> None:
    """Sincroniza todas las empresas con tesis (o con reglas de tesis vivas)."""
    company_ids = set(db.scalars(select(ThesisVersion.company_id).distinct()).all())
    company_ids |= set(
        db.scalars(
            select(AlertRule.company_id).where(
                AlertRule.rule_type == RULE_TYPE, AlertRule.active.is_(True)
            )
        ).all()
    )
    for company_id in sorted(company_ids):
        company = db.get(Company, company_id)
        if company is not None:
            sync_thesis_rules(db, company)


def _latest_price(db: Session, company_id: int) -> tuple[Decimal | None, dict[str, Any]]:
    price = db.scalar(
        select(MarketPrice)
        .where(MarketPrice.company_id == company_id)
        .order_by(desc(MarketPrice.date))
        .limit(1)
    )
    if price is None or price.close is None:
        return None, {"status": "missing", "missing": "precio"}
    age_days = (date.today() - price.date).days
    return Decimal(price.close), {
        "market_price_id": price.id,
        "price": str(price.close),
        "date": price.date.isoformat(),
        "age_days": age_days,
        "status": "stale" if age_days >= min(get_settings().market_price_max_age_days, 1) else "fresh",
    }


def observe(db: Session, rule: AlertRule) -> tuple[Decimal | None, dict[str, Any]]:
    """Valor actual de la metrica de un criterio de tesis, con su procedencia."""
    target = rule.target or {}
    metric = str(target.get("metric") or "")
    base: dict[str, Any] = {
        "kind": TARGET_KIND,
        "metric": metric,
        "thesis_version_id": target.get("thesis_version_id"),
    }
    if metric == PRICE:
        value, info = _latest_price(db, rule.company_id)
        return value, {**base, **info}
    if metric in PERCENT_METRICS:
        thesis = db.get(ThesisVersion, target.get("thesis_version_id")) if target.get(
            "thesis_version_id"
        ) else None
        if thesis is None:
            return None, {**base, "status": "missing", "missing": "tesis"}
        reference = thesis.expected_value if metric == MARGIN_OF_SAFETY_PCT else thesis.current_price
        if reference is None or Decimal(reference) <= 0:
            missing = "valor_esperado" if metric == MARGIN_OF_SAFETY_PCT else "precio_tesis"
            return None, {**base, "status": "missing", "missing": missing}
        price, info = _latest_price(db, rule.company_id)
        if price is None or price <= 0:
            return None, {**base, **info}
        if metric == MARGIN_OF_SAFETY_PCT:
            value = (Decimal(reference) / price - 1) * 100
        else:
            value = (price / Decimal(reference) - 1) * 100
        return value, {**base, **info, "reference": str(reference)}
    if metric.startswith(METRIC_PREFIX):
        name = metric[len(METRIC_PREFIX):].strip()
        calculated = db.scalar(
            select(CalculatedMetric)
            .where(
                CalculatedMetric.company_id == rule.company_id,
                CalculatedMetric.metric == name,
                CalculatedMetric.value.is_not(None),
            )
            .order_by(
                desc(CalculatedMetric.fiscal_year), desc(CalculatedMetric.created_at)
            )
            .limit(1)
        )
        if calculated is not None and calculated.value is not None:
            return Decimal(calculated.value), {
                **base,
                "status": "fresh",
                "source": "calculated_metric",
                "calculated_metric_id": calculated.id,
                "period": calculated.period,
                "unit": calculated.unit,
            }
        fact = db.scalar(
            select(FinancialFact)
            .where(FinancialFact.company_id == rule.company_id, FinancialFact.metric == name)
            .order_by(desc(FinancialFact.fiscal_year), desc(FinancialFact.created_at))
            .limit(1)
        )
        if fact is not None and fact.value is not None:
            return Decimal(fact.value), {
                **base,
                "status": "fresh",
                "source": "financial_fact",
                "financial_fact_id": fact.id,
                "period": getattr(fact, "period", None),
            }
        return None, {**base, "status": "missing", "missing": name}
    return None, {**base, "status": "unsupported_target"}


def alert_message(company: Company, rule: AlertRule, observed: Any) -> str:
    target = rule.target or {}
    condition = rule.condition or {}
    item = {
        "metric": target.get("metric"),
        "operator": condition.get("operator"),
        "threshold": condition.get("value"),
    }
    percent = str(target.get("metric")) in PERCENT_METRICS
    version = target.get("thesis_version")
    head = f"{company.ticker}: salta un criterio de invalidación de la tesis"
    if version is not None:
        head += f" (v{version})"
    description = target.get("description")
    body = f"«{description}» ({describe_rule(item)})" if description else describe_rule(item)
    return f"{head}: {body}. Valor actual: {format_es(observed, percent=percent)}."
