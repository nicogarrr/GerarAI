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
- ``margen_seguridad_pct``: ``((valor_esperado_tesis - precio) / valor_esperado_tesis) * 100``.
  Misma convencion (V - P) / V que ``ThesisVersion.margin_of_safety``, el motor
  (``discount_to_value_v1``) y el resto de pantallas, con el mismo benchmark
  (valor ESPERADO de la tesis) pero el precio de hoy. Una regla «< 20» pide lo
  mismo que el margen que muestran la ficha, la cartera y el screener.
- ``variacion_desde_tesis_pct``: ``(precio / precio_en_la_tesis - 1) * 100``.
- ``metrica:<nombre>``: ultimo ``CalculatedMetric`` con ese nombre (ejercicio
  mas reciente) y, si no hay, ultimo ``FinancialFact``. El umbral va en la
  unidad de la metrica (p. ej. ROIC 0,08 = 8 %).

Sin dato no dispara nunca: la observacion queda como ``missing``.
"""

from __future__ import annotations

import math
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import desc, or_, select
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
from app.services.fair_value_service import listed_value
from app.services.price_freshness import close_is_stale
from app.services.price_units import listing_price
from app.services.split_adjustment import (
    cumulative_split_factor_after,
    period_end_date,
    split_after_price,
    split_events_by_company,
    split_factor_for_fact,
)
from app.services.ttm_fundamentals import FLOW_METRICS

RULE_TYPE = "thesis_invalidation"
TARGET_KIND = "thesis_metric"
MAX_RULES = 20
# Un criterio de invalidacion se mueve despacio: como mucho un aviso al dia
# mientras siga cumpliendose (el cooldown del evaluador existente).
COOLDOWN_SECONDS = 86_400

PRICE = "precio"
QUARTER_LABELS = ("Q1", "Q2", "Q3", "Q4")
MARGIN_OF_SAFETY_PCT = "margen_seguridad_pct"
CHANGE_SINCE_THESIS_PCT = "variacion_desde_tesis_pct"
METRIC_PREFIX = "metrica:"
# Datos por accion y recuentos de acciones: cambian de base con un split. Un
# BPA anual de antes de un 10:1 es 10 veces el de hoy; se reexpresa a la base
# actual (regla unica fact_split_factor) antes de compararlo con el umbral.
PER_SHARE_METRICS = frozenset(
    {
        "eps_diluted",
        "eps_basic",
        "fcf_per_share",
        "revenue_per_share",
        "ttm_dividend_per_share",
        "loss_per_share",
    }
)
SHARE_COUNT_METRICS = frozenset({"shares_diluted", "shares_outstanding"})

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
    if not parsed.is_finite():
        return None
    # Se guarda como float: «1e400» es un Decimal finito pero un float infinito.
    return parsed if math.isfinite(float(parsed)) else None


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
    # El cierre se guarda como lo da el proveedor (Londres en peniques); la tesis
    # (valor esperado, precio de la tesis) está en la divisa PRINCIPAL del
    # listado. Sin unidad verificable no se compara (no dispara).
    company = db.get(Company, company_id)
    listed = (
        listing_price(Decimal(price.close), quote_currency=price.quote_currency, company=company)
        if company is not None
        else None
    )
    if listed is None:
        return None, {"status": "missing", "missing": "unidad_precio"}
    value, currency = listed
    age_days = (date.today() - price.date).days
    return value, {
        "market_price_id": price.id,
        "price": str(value),
        "currency": currency,
        "date": price.date.isoformat(),
        "age_days": age_days,
        "status": (
            "stale"
            if close_is_stale(
                price.date,
                company.exchange if company else None,
                get_settings().market_price_max_age_days,
                ticker=company.ticker if company else None,
            )
            else "fresh"
        ),
    }


def _split_factor_since_thesis(
    db: Session, company_id: int, thesis: ThesisVersion, price_day: Any
) -> Decimal | None:
    """Factor de splits entre la fecha de la tesis y el cierre; None si un split
    ya efectivo es posterior al ultimo cierre (base del cierre desconocida)."""
    events = split_events_by_company(db, [company_id]).get(company_id, [])
    if not events:
        return Decimal(1)
    try:
        close_day = date.fromisoformat(str(price_day)[:10])
    except ValueError:
        return None
    if split_after_price(events, close_day, max(date.today(), close_day)):
        return None
    created = getattr(thesis, "created_at", None)
    thesis_day = created.date() if created is not None else None
    return cumulative_split_factor_after([e for e in events if e[0] <= close_day], thesis_day)


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
        if metric == MARGIN_OF_SAFETY_PCT:
            # Valor por acción COTIZADA: un ADR se compara con su valor por ADR.
            basis = thesis.valuation_basis if isinstance(thesis.valuation_basis, dict) else {}
            listed_reference = listed_value(basis, fallback={"expected_value": thesis.expected_value})
            reference = Decimal(str(listed_reference)) if listed_reference is not None else None
        else:
            reference = thesis.current_price
        if reference is None or Decimal(reference) <= 0:
            missing = "valor_esperado" if metric == MARGIN_OF_SAFETY_PCT else "precio_tesis"
            return None, {**base, "status": "missing", "missing": missing}
        price, info = _latest_price(db, rule.company_id)
        if price is None or price <= 0:
            return None, {**base, **info}
        # La tesis esta en la base de acciones de su fecha; el cierre, en la del
        # dia. Un split posterior a la tesis cambia la base (10:1 -> precio de
        # tesis 1000 = 100 hoy). Sin esto «variacion desde tesis» leia -90 % y
        # disparaba el criterio. Con el ultimo cierre anterior a un split ya
        # efectivo la base del cierre es desconocida: N/D, como en valoracion.
        factor = _split_factor_since_thesis(db, rule.company_id, thesis, info.get("date"))
        if factor is None:
            return None, {**base, **info, "status": "missing", "missing": "precio_anterior_a_split"}
        reference = Decimal(reference) / factor
        if metric == MARGIN_OF_SAFETY_PCT:
            # Convencion unica del producto (V - P) / V: el % que ve el usuario
            # en la tesis, la ficha, la cartera y el screener. V/P - 1 es el
            # potencial de revalorizacion, no el margen (ver engines/base.py).
            value = (Decimal(reference) - price) / Decimal(reference) * 100
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
            if name in PER_SHARE_METRICS or name in SHARE_COUNT_METRICS:
                # Sin fecha de publicacion no se sabe si el calculo ya recoge
                # un split posterior al cierre del periodo: N/D, nunca x10.
                events = split_events_by_company(db, [rule.company_id]).get(
                    rule.company_id, []
                )
                end = period_end_date(calculated.period)
                if events and (
                    end is None or any(end < day <= date.today() for day, _r in events)
                ):
                    return None, {
                        **base,
                        "status": "missing",
                        "missing": "split_posterior_al_periodo",
                        "period": calculated.period,
                    }
            return Decimal(calculated.value), {
                **base,
                "status": "fresh",
                "source": "calculated_metric",
                "calculated_metric_id": calculated.id,
                "period": calculated.period,
                "unit": calculated.unit,
            }
        query = select(FinancialFact).where(
            FinancialFact.company_id == rule.company_id, FinancialFact.metric == name
        )
        if name in FLOW_METRICS:
            # Un flujo (ingresos, beneficio...) de un trimestre no es el del año:
            # el 10-Q del Q1 tiene fiscal_year mas reciente que el ultimo 10-K y
            # ganaba el orden, asi que «ingresos < X» comparaba un trimestre con
            # un umbral anual. Solo cuentan los datos anuales.
            query = query.where(
                or_(
                    FinancialFact.fiscal_quarter.is_(None),
                    FinancialFact.fiscal_quarter.not_in(QUARTER_LABELS),
                ),
                ~or_(*(FinancialFact.period.like(f"%:{q}") for q in QUARTER_LABELS)),
            )
        fact = db.scalar(
            query.order_by(desc(FinancialFact.fiscal_year), desc(FinancialFact.created_at)).limit(1)
        )
        if fact is not None and fact.value is not None:
            value = Decimal(fact.value)
            if name in PER_SHARE_METRICS or name in SHARE_COUNT_METRICS:
                factor = split_factor_for_fact(
                    db,
                    rule.company_id,
                    period=getattr(fact, "period", None),
                    filed=getattr(fact, "filed", None),
                    cutoff=date.today(),
                )
                value = value / factor if name in PER_SHARE_METRICS else value * factor
            return value, {
                **base,
                "status": "fresh",
                "source": "financial_fact",
                "financial_fact_id": fact.id,
                "period": getattr(fact, "period", None),
            }
        return None, {**base, "status": "missing", "missing": name}
    return None, {**base, "status": "unsupported_target"}


def alert_title(company: Company, rule: AlertRule, language: str = "es") -> str:
    """Titulo del aviso. En castellano, el nombre guardado de la regla (igual que
    siempre); en ingles se compone al vuelo sin tocar el nombre guardado, que es
    la clave de la regla en ``sync_thesis_rules``."""
    if language != "en":
        return rule.name
    target = rule.target or {}
    condition = rule.condition or {}
    item = {
        "metric": target.get("metric"),
        "operator": condition.get("operator"),
        "threshold": condition.get("value"),
    }
    return f"{company.ticker}: thesis invalidation · {_describe_rule_en(item)}"[:300]


def alert_message(company: Company, rule: AlertRule, observed: Any, language: str = "es") -> str:
    target = rule.target or {}
    condition = rule.condition or {}
    item = {
        "metric": target.get("metric"),
        "operator": condition.get("operator"),
        "threshold": condition.get("value"),
    }
    percent = str(target.get("metric")) in PERCENT_METRICS
    version = target.get("thesis_version")
    description = target.get("description")
    if language == "en":
        head = f"{company.ticker}: a thesis invalidation criterion was triggered"
        if version is not None:
            head += f" (v{version})"
        rule_text = _describe_rule_en(item)
        body = f"«{description}» ({rule_text})" if description else rule_text
        return f"{head}: {body}. Current value: {_format_en(observed, percent=percent)}."
    head = f"{company.ticker}: salta un criterio de invalidación de la tesis"
    if version is not None:
        head += f" (v{version})"
    body = f"«{description}» ({describe_rule(item)})" if description else describe_rule(item)
    return f"{head}: {body}. Valor actual: {format_es(observed, percent=percent)}."


_METRIC_LABELS_EN: dict[str, str] = {
    PRICE: "price",
    MARGIN_OF_SAFETY_PCT: "margin of safety",
    CHANGE_SINCE_THESIS_PCT: "change since the thesis",
}


def _format_en(value: Any, *, percent: bool = False) -> str:
    """Numero en formato ingles (punto decimal, coma de miles)."""
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return str(value)
    text = f"{number:,.2f}"
    return f"{text}%" if percent else text


def _describe_rule_en(rule: dict[str, Any]) -> str:
    metric = str(rule.get("metric") or "")
    label = _METRIC_LABELS_EN.get(metric) or metric_label(metric)
    return (
        f"{label} {_OPERATOR_TEXT.get(str(rule.get('operator')), rule.get('operator'))} "
        f"{_format_en(rule.get('threshold'), percent=metric in PERCENT_METRICS)}"
    )
