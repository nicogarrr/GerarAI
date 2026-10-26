"""Mapeo concepto-edgartools -> metrica canonica de GerarAI.

Fuente unica de verdad: ``SEC_METRIC_MAP`` de
``financial_ingestion_service`` (se importa, no se copia). Este modulo solo
invierte ese mapa (concepto us-gaap -> metrica) y documenta como llegan los
conceptos por cada via edgartools:

- Snapshot/offline: el JSON oficial companyfacts trae ``facts.us-gaap`` con
  los tags tal cual (``Revenues``, ``NetIncomeLoss``, ...): identidad directa
  contra ``SEC_METRIC_MAP``.
- Live edgartools: ``EntityFacts.get_fact(concept)`` / ``get_annual_fact`` /
  ``Company.get_financials()`` normalizan XBRL (``edgar.xbrl.standardization``)
  pero conservan el nombre del concepto us-gaap en ``FinancialFact.concept``
  (verificado en edgartools 5.59.1: ``edgar/entity/models.py``), asi que el
  mismo mapa aplica. Los labels de presentacion ("Revenues", "Net Income")
  NO se usan como clave: solo el concepto.

Reglas de fusion (las mismas que la via actual, sin duplicar semantica):
- alias (la mayoria): un ganador por periodo, el ``filed`` mas reciente.
- partes disjuntas (``SUMMED_COMPONENT_METRICS``, hoy ``intangible_assets``):
  se suman por periodo.
- alcance (``SCOPE_PRIORITY_METRICS``, hoy ``total_debt``): gana el concepto
  de mayor alcance declarado primero, ``filed`` solo desempata recasts.
- bancos (``bank_like``): sin tag agregado el revenue es
  ``InterestIncomeExpenseNet+NoninterestIncome`` (fail closed: faltando una
  parte no hay revenue); los subtotales de comisiones salen de candidatos.
"""

from __future__ import annotations

from typing import Any

from app.services.financial_ingestion_service import (
    BANK_REVENUE_COMPONENTS,
    BANK_REVENUE_CONCEPT,
    BANK_REVENUE_SUBTOTAL_TAGS,
    SEC_METRIC_MAP,
)

CONCEPT_TO_METRIC: dict[str, str] = {}
for _metric, _concepts, _unit in SEC_METRIC_MAP:
    for _concept in _concepts:
        CONCEPT_TO_METRIC.setdefault(_concept, _metric)


def concept_to_metric(concept: str) -> str | None:
    """Metrica canonica para un concepto us-gaap (o None si no mapea)."""
    if not concept:
        return None
    return CONCEPT_TO_METRIC.get(concept.strip())


def metric_concepts(metric: str) -> list[str]:
    """Conceptos candidatos de una metrica, en orden de declaracion."""
    for name, concepts, _unit in SEC_METRIC_MAP:
        if name == metric:
            return list(concepts)
    return []


def metric_unit(metric: str) -> str | None:
    """Unidad canonica de una metrica (``USD``, ``USD/share``, ...)."""
    for name, _concepts, unit in SEC_METRIC_MAP:
        if name == metric:
            return unit
    return None


def xbrl_unit_key(metric: str) -> str:
    """Clave de unidad tal como aparece en companyfacts (``USD/shares``)."""
    unit = metric_unit(metric) or "USD"
    return "USD/shares" if unit == "USD/share" else unit


def revenue_concepts_for(concepts: list[str], bank_like: bool) -> list[str]:
    """Candidatos a revenue (bancos: sin subtotales de comisiones).

    Misma regla que ``_revenue_concepts_for`` de la via actual, con la misma
    tabla (``BANK_REVENUE_SUBTOTAL_TAGS`` importada, no copiada).
    """
    if not bank_like:
        return list(concepts)
    return [c for c in concepts if c not in BANK_REVENUE_SUBTOTAL_TAGS]


def bank_revenue_components() -> tuple[str, ...]:
    return tuple(BANK_REVENUE_COMPONENTS)


def bank_revenue_concept_label() -> str:
    return BANK_REVENUE_CONCEPT


def mapping_table() -> list[dict[str, Any]]:
    """Tabla concepto -> metrica -> unidad (para el informe y el RAG)."""
    rows: list[dict[str, Any]] = []
    for metric, concepts, unit in SEC_METRIC_MAP:
        for concept in concepts:
            rows.append({"concept": concept, "metric": metric, "unit": unit})
    return rows
