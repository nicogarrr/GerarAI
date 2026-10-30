"""Commodity-cycle engine — requires volume/cost facts; no bootstrap.

Supuestos: flujo = max(precio − coste_unitario, 0) × volumen × (1 − tasa);
equity = flujo × múltiplo − net_debt (múltiplo y tasa de facts, tasa en
[0, 1), múltiplo > 0). Escenarios bear/base/bull = grid de precios
×(0.75/1.0/1.25) sobre el precio realizado/spot; probabilidades ponderadas
por confianza de evidencia y spread operativo (precio − coste)/precio.
Sensibilidad: la propia tabla de 3 filas del grid de precios.
"""

from __future__ import annotations

from sqlalchemy import desc, select

from app.models import FinancialFact
from app.valuation.commodity_sensitivity import commodity_price_sensitivity
from app.valuation.engines.base import (
    MODEL_VERSION,
    ValuationContext,
    ValuationEngine,
    adr_ratio,
    insufficient_result,
    is_adr_without_ratio,
    margin_of_safety,
)
from app.valuation.moat_framework import empty_moat_framework
from app.valuation.scenario_definitions import evidence_weighted_probabilities
from app.valuation.scenario_model import Scenario, probability_weighted_value


class CommodityCycleEngine(ValuationEngine):
    """Cíclicas de materias primas: valor sobre grid de precios.

    Supuestos: margen unitario floorado en 0 (precio bajo coste = flujo 0,
    nunca negativo); múltiplo sobre flujo después de impuestos.
    Expone bear/base/bull del grid y la tabla de sensibilidad de precios.
    """

    key = "commodity"

    def value(self, context: ValuationContext) -> dict:
        company = context.company
        snapshot = context.snapshot
        current_price = context.current_price
        if is_adr_without_ratio(company):
            # Producción y acciones vienen en ordinarias; el precio es del ADR.
            result = insufficient_result(
                ticker=company.ticker,
                model_type=company.valuation_model,
                engine_key=self.key,
                current_price=current_price,
                missing_inputs=["adr_ratio"],
                reason=(
                    f"{company.ticker} is quoted as an ADR but the ordinary-shares-per-ADR "
                    "ratio is unknown, so value per share and the quoted price are not on "
                    "the same basis."
                ),
                snapshot=snapshot,
            )
            result["moat"] = empty_moat_framework(
                company.company_type, company.factor_tags or [], company.special_risks or []
            )
            return result

        def latest(metric: str) -> FinancialFact | None:
            return context.db.scalar(
                select(FinancialFact)
                .where(FinancialFact.company_id == company.id, FinancialFact.metric == metric)
                .order_by(FinancialFact.fiscal_year.desc().nullslast(), desc(FinancialFact.created_at))
                .limit(1)
            )

        volume_fact = latest("production_volume") or latest("sales_volume")
        cost_fact = latest("cash_cost_per_unit") or latest("all_in_sustaining_cost")
        price_fact = latest("realized_commodity_price") or latest("spot_commodity_price")
        tax_fact = latest("effective_tax_rate")
        multiple_fact = latest("commodity_earnings_multiple")
        shares = snapshot.value("shares_diluted")
        net_debt = snapshot.value("net_debt")

        missing: list[str] = []
        if volume_fact is None:
            missing.append("production_volume_or_sales_volume")
        if cost_fact is None:
            missing.append("cash_cost_per_unit")
        if price_fact is None:
            missing.append("realized_or_spot_commodity_price")
        if tax_fact is None:
            missing.append("effective_tax_rate")
        if multiple_fact is None:
            missing.append("commodity_earnings_multiple")
        if shares is None or shares <= 0:
            missing.append("shares_diluted")
        if net_debt is None:
            # A commodity NAV is an enterprise value; converting it to equity
            # value requires net debt. Zero is not the same as unknown.
            missing.append("net_debt")

        if missing:
            result = insufficient_result(
                ticker=company.ticker,
                model_type=company.valuation_model,
                engine_key=self.key,
                current_price=current_price,
                missing_inputs=missing,
                reason="Commodity valuation requires volume, unit cost, price and shares — not a generic DCF.",
                snapshot=snapshot,
            )
            result["moat"] = empty_moat_framework(
                company.company_type, company.factor_tags or [], company.special_risks or []
            )
            return result

        assert volume_fact and cost_fact and price_fact and tax_fact and multiple_fact and shares

        def _period_key(fact: FinancialFact):
            return fact.fiscal_year if fact.fiscal_year is not None else fact.period

        # Cada hecho se elige por separado ("el ultimo"): volumen y coste de
        # periodos distintos dan un margen que nunca existio. El precio spot es
        # por definicion de hoy; el realizado debe ser del mismo periodo.
        flow_facts = [volume_fact, cost_fact]
        if price_fact.metric == "realized_commodity_price":
            flow_facts.append(price_fact)
        if len({_period_key(fact) for fact in flow_facts}) > 1:
            result = insufficient_result(
                ticker=company.ticker,
                model_type=company.valuation_model,
                engine_key=self.key,
                current_price=current_price,
                missing_inputs=["consistent_period_volume_cost_price"],
                reason="Commodity volume, unit cost and realized price come from different periods.",
                snapshot=snapshot,
            )
            result["moat"] = empty_moat_framework(
                company.company_type, company.factor_tags or [], company.special_risks or []
            )
            return result
        if not 0 <= float(tax_fact.value) < 1 or float(multiple_fact.value) <= 0:
            result = insufficient_result(
                ticker=company.ticker,
                model_type=company.valuation_model,
                engine_key=self.key,
                current_price=current_price,
                missing_inputs=["valid_effective_tax_rate_and_commodity_earnings_multiple"],
                reason="Commodity tax and valuation multiple assumptions must be sourced and economically valid.",
                snapshot=snapshot,
            )
            result["moat"] = empty_moat_framework(
                company.company_type, company.factor_tags or [], company.special_risks or []
            )
            return result

        base_price = float(price_fact.value)
        grid = commodity_price_sensitivity(
            base_volume=float(volume_fact.value),
            cash_cost_per_unit=float(cost_fact.value),
            commodity_prices=[base_price * 0.75, base_price, base_price * 1.25],
            tax_rate=float(tax_fact.value),
            multiple=float(multiple_fact.value),
            net_debt=net_debt,
            shares_outstanding=shares,
        )
        rows = grid["rows"]
        bear_v, base_v, bull_v = rows[0]["value_per_share"], rows[1]["value_per_share"], rows[2]["value_per_share"]
        sourced_facts = [volume_fact, cost_fact, price_fact, tax_fact, multiple_fact]
        evidence_confidence = sum(float(fact.confidence) for fact in sourced_facts) / len(
            sourced_facts
        )
        operating_spread = (base_price - float(cost_fact.value)) / max(abs(base_price), 1e-9)
        probabilities = evidence_weighted_probabilities(
            evidence_confidence=evidence_confidence,
            directional_signal=operating_spread,
            downside_risk=max(0.0, -operating_spread),
        )
        weighted = probability_weighted_value(
            [
                Scenario("bear", probabilities["bear"], bear_v),
                Scenario("base", probabilities["base"], base_v),
                Scenario("bull", probabilities["bull"], bull_v),
            ]
        )
        expected = weighted["expected_value"]
        # Valor por acción ordinaria; un ADR cotiza N ordinarias (BHP, VALE...).
        ratio = adr_ratio(company)
        comparable_price = current_price / ratio if (ratio and current_price) else current_price

        return {
            "ticker": company.ticker,
            "model_type": company.valuation_model,
            "status": "ok",
            "publishable": True,
            "current_price": current_price,
            "bear_value": bear_v,
            "base_value": base_v,
            "bull_value": bull_v,
            "expected_value": expected,
            "margin_of_safety": margin_of_safety(expected, comparable_price),
            "missing_inputs": [],
            "adr_ratio": ratio,
            "value_per_share_basis": "ordinary_share",
            "listed_share_values": (
                {
                    "bear": bear_v * ratio,
                    "base": base_v * ratio,
                    "bull": bull_v * ratio,
                    "expected": expected * ratio,
                }
                if ratio
                else None
            ),
            "comparable_price_basis": "ordinary_share" if ratio else "listed_share",
            "reverse_dcf": {},
            "sensitivity": grid,
            "moat": empty_moat_framework(
                company.company_type, company.factor_tags or [], company.special_risks or []
            ),
            "trace": {
                "method": company.valuation_model,
                "engine": self.key,
                "input_source": "financial_facts",
                "publishable": True,
                "status": "ok",
                "model_version": MODEL_VERSION,
                "scenario_style": "commodity_price_grid",
                "fact_ids": {
                    **snapshot.fact_ids(),
                    # Key by the fact's REAL metric name: the engine resolves
                    # aliases (production_volume/sales_volume), and labelling a
                    # sales_volume row as "production_volume" makes the
                    # provenance trail a lie for anyone auditing it.
                    volume_fact.metric: volume_fact.id,
                    cost_fact.metric: cost_fact.id,
                    price_fact.metric: price_fact.id,
                    tax_fact.metric: tax_fact.id,
                    multiple_fact.metric: multiple_fact.id,
                },
                # The commodity inputs drive 100% of this NAV but are not part
                # of the snapshot, so they must be listed here: the
                # point-in-time guard only inspects trace["periods"], and
                # without them an as_of valuation silently accepted facts from
                # a later fiscal year.
                "periods": {
                    **snapshot.periods(),
                    volume_fact.metric: volume_fact.period,
                    cost_fact.metric: cost_fact.period,
                    price_fact.metric: price_fact.period,
                    tax_fact.metric: tax_fact.period,
                    multiple_fact.metric: multiple_fact.period,
                },
                "commodity_input_metrics": {
                    "volume": volume_fact.metric,
                    "cost": cost_fact.metric,
                    "price": price_fact.metric,
                    "effective_tax_rate": tax_fact.metric,
                    "earnings_multiple": multiple_fact.metric,
                },
                "commodity_sensitivity": grid,
                "probabilities": probabilities,
                "probability_method": "source_confidence_plus_operating_spread",
                "evidence_confidence": evidence_confidence,
                "weighted": weighted["trace"],
            },
        }
