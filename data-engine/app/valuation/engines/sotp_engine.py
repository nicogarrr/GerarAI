"""Sum-of-the-parts engine for multi-segment / holding-style names.

Supuestos: NAV = Σ(métrica_operativa_segmento × múltiplo_segmento) − net_debt,
todo de FinancialFact con contrato ``segment_{nombre}_operating_metric`` y
``segment_{nombre}_valuation_multiple`` (múltiplos > 0, métricas > 0); holding
discount de facts en [0, 1); valor/acc = NAV/acc × (1 − descuento).
Escenarios bear/base/bull: descuento +15pp (techo 45%) / base / −8pp con NAV
×1.12 en bull. Sensibilidad: tabla de 3 filas variando el descuento
(−5pp / base / +5pp) a NAV base. Sin fallback a DCF de firma única.
"""

from __future__ import annotations

from sqlalchemy import desc, select

from app.models import FinancialFact
from app.valuation.engines.base import (
    MODEL_VERSION,
    ValuationContext,
    ValuationEngine,
    adr_comparable_price,
    apply_publication_blockers,
    insufficient_result,
    is_adr_without_ratio,
    margin_of_safety,
)
from app.valuation.moat_framework import empty_moat_framework
from app.valuation.scenario_definitions import holding_company_scenarios
from app.valuation.scenario_model import Scenario, probability_weighted_value
from app.valuation.sotp import run_sotp


def sotp_discount_sensitivity(*, nav_per_share: float, base_discount: float) -> dict:
    """Tabla de sensibilidad 1-D sobre el descuento holding.

    Revalúa ``NAV/acc × (1 − descuento)`` en tres puntos
    (−5pp / base / +5pp, acotado a [0, 0.60]); el NAV se mantiene en base.
    Devuelve el formato estándar ``{"rows": [...], "trace": {...}}``.
    """
    rows = []
    for label, discount in (
        ("narrow_discount", max(base_discount - 0.05, 0.0)),
        ("base_discount", base_discount),
        ("wide_discount", min(base_discount + 0.05, 0.60)),
    ):
        rows.append(
            {
                "scenario": label,
                "holding_discount": discount,
                "nav_per_share": nav_per_share,
                "value_per_share": nav_per_share * (1.0 - discount),
            }
        )
    return {"rows": rows, "trace": {"method": "sotp_holding_discount_sensitivity"}}


class SOTPEngine(ValuationEngine):
    """SOTP: suma de segmentos menos deuda neta, con descuento holding.

    Supuestos: múltiplos por segmento y descuento holding de FinancialFact;
    NAV/acc × (1 − descuento). Sensibilidad: tabla de descuento holding
    (−5pp / base / +5pp) a NAV base.
    """

    key = "sotp"

    def value(self, context: ValuationContext) -> dict:
        company = context.company
        snapshot = context.snapshot
        current_price = context.current_price

        if is_adr_without_ratio(company):
            return insufficient_result(
                ticker=company.ticker, model_type=company.valuation_model,
                engine_key=self.key, current_price=current_price,
                missing_inputs=["adr_ratio"],
                reason="ADR without a valid adr:N ratio: ordinary NAV cannot be compared to ADR price.",
            )
        comparable_price, ratio = adr_comparable_price(company, current_price)

        facts = list(
            context.db.scalars(
                select(FinancialFact)
                .where(FinancialFact.company_id == company.id)
                .order_by(FinancialFact.fiscal_year.desc().nullslast(), desc(FinancialFact.created_at))
            ).all()
        )
        latest_by_metric: dict[str, FinancialFact] = {}
        for fact in facts:
            latest_by_metric.setdefault(fact.metric, fact)
        shares_fact = latest_by_metric.get("shares_diluted")
        net_debt_fact = latest_by_metric.get("net_debt")
        shares = float(shares_fact.value) if shares_fact is not None else None
        net_debt = float(net_debt_fact.value) if net_debt_fact is not None else None

        segments: list[dict] = []
        segment_period_keys: list = []
        missing_segments: list[str] = []
        segment_sources: list[FinancialFact] = []
        suffix = "_valuation_multiple"
        for multiple_metric, multiple_fact in latest_by_metric.items():
            if not multiple_metric.startswith("segment_") or not multiple_metric.endswith(suffix):
                continue
            prefix = multiple_metric[: -len(suffix)]
            operating_metric = f"{prefix}_operating_metric"
            operating_fact = latest_by_metric.get(operating_metric)
            if operating_fact is None or float(operating_fact.value) <= 0:
                missing_segments.append(operating_metric)
                continue
            if float(multiple_fact.value) <= 0:
                missing_segments.append(multiple_metric)
                continue
            segment_name = prefix.removeprefix("segment_")
            segments.append(
                {
                    "name": segment_name,
                    "metric": float(operating_fact.value),
                    "multiple": float(multiple_fact.value),
                    "metric_fact_id": operating_fact.id,
                    "multiple_fact_id": multiple_fact.id,
                    "period": operating_fact.period,
                }
            )
            segment_sources.extend([operating_fact, multiple_fact])
            segment_period_keys.append(
                operating_fact.fiscal_year
                if operating_fact.fiscal_year is not None
                else operating_fact.period
            )

        discount_fact = latest_by_metric.get("holding_company_discount")

        missing: list[str] = []
        if shares is None or shares <= 0:
            missing.append("shares_diluted")
        if net_debt is None:
            missing.append("net_debt")
        if discount_fact is None or not 0 <= float(discount_fact.value) < 1:
            missing.append("holding_company_discount")
        # Cada segmento toma "su ultimo" hecho por separado: sin esta comprobacion
        # un NAV podia sumar un segmento de FY2024 con otro de FY2022 y publicarlo
        # como un unico periodo.
        segment_periods = set(segment_period_keys)
        if len(segment_periods) > 1:
            missing.append("consistent_segment_periods")
        if not segments:
            missing.extend(
                missing_segments
                or ["segment_*_operating_metric", "segment_*_valuation_multiple"]
            )

        # `missing` recoge exactamente lo que bloquearia: shares nulos o no
        # positivos, deuda neta ausente, descuento fuera de [0, 1) o ningun
        # segmento valorable. Preguntar de nuevo por cada termino repetia la
        # condicion y hacia imposible saber cual habia bloqueado, que es justo
        # lo que `missing_inputs` publica.
        if missing:
            result = insufficient_result(
                ticker=company.ticker,
                model_type=company.valuation_model,
                engine_key=self.key,
                current_price=current_price,
                missing_inputs=sorted(set(missing)),
                reason=(
                    "SOTP requires coherent shares/net-debt plus segment-level facts. "
                    "Do not fall back to a single-firm DCF for holding/multi-segment names."
                ),
                snapshot=snapshot,
                extra_trace={
                    "segment_fact_contract": {
                        "operating_metric": "segment_{name}_operating_metric",
                        "valuation_multiple": "segment_{name}_valuation_multiple",
                    },
                    "found_segments": [s["name"] for s in segments],
                },
            )
            result["moat"] = empty_moat_framework(
                company.company_type, company.factor_tags or [], company.special_risks or []
            )
            return result

        assert discount_fact is not None
        base = run_sotp(segments, net_debt=net_debt, shares_outstanding=shares)
        nav_per_share = base["value_per_share"]
        discount = float(discount_fact.value)
        confidence_sources = segment_sources + [discount_fact]
        if shares_fact is not None:
            confidence_sources.append(shares_fact)
        if net_debt_fact is not None:
            confidence_sources.append(net_debt_fact)
        evidence_confidence = sum(float(fact.confidence) for fact in confidence_sources) / len(
            confidence_sources
        )
        scenarios = holding_company_scenarios(
            nav_per_share,
            holding_discount=discount,
            evidence_confidence=evidence_confidence,
        )

        scenario_results = {}
        for scenario in scenarios:
            nav = float(scenario.assumptions["nav_per_share"])
            disc = float(scenario.assumptions["holding_discount"])
            value = nav * (1.0 - disc)
            scenario_results[scenario.name] = {
                "definition": {
                    "name": scenario.name,
                    "probability": scenario.probability,
                    "drivers": scenario.drivers,
                    "description": scenario.description,
                    "assumptions": scenario.assumptions,
                },
                "value_per_share": value,
            }

        weighted = probability_weighted_value(
            [
                Scenario(s["definition"]["name"], s["definition"]["probability"], s["value_per_share"])
                for s in scenario_results.values()
            ]
        )
        expected = weighted["expected_value"]

        sensitivity = sotp_discount_sensitivity(
            nav_per_share=nav_per_share,
            base_discount=discount,
        )

        # A total that is missing one of its parts is not the total. The
        # segments that DO have facts were summed and divided by shares, which
        # produces a per-share NAV of a business nobody owns: publishing it as
        # the SOTP of the company stated a value for segments the model never
        # looked at, and the margin of safety computed on it inherits the
        # omission. The number stays as an orientation of the known part.
        publication_blockers = [
            f"segment:{metric}" for metric in missing_segments
        ]

        return apply_publication_blockers(
            {
            "ticker": company.ticker,
            "model_type": company.valuation_model,
            "status": "ok",
            "publishable": True,
            "current_price": current_price,
            "bear_value": scenario_results["bear"]["value_per_share"],
            "base_value": scenario_results["base"]["value_per_share"],
            "bull_value": scenario_results["bull"]["value_per_share"],
            "expected_value": expected,
            "margin_of_safety": margin_of_safety(expected, comparable_price),
            "listed_share_values": {
                "bear": scenario_results["bear"]["value_per_share"] * ratio,
                "base": scenario_results["base"]["value_per_share"] * ratio,
                "bull": scenario_results["bull"]["value_per_share"] * ratio,
                "expected": expected * ratio,
            } if ratio else None,
            "adr_ratio": ratio,
            "value_per_share_basis": "ordinary_share",
            "comparable_price_basis": "ordinary_share" if ratio else "listed_share",
            "missing_inputs": missing_segments,
            "publication_blockers": publication_blockers,
            "reverse_dcf": {},
            "sensitivity": sensitivity,
            "moat": empty_moat_framework(
                company.company_type, company.factor_tags or [], company.special_risks or []
            ),
            "trace": {
                "comparable_price": comparable_price,
                "method": company.valuation_model,
                "engine": self.key,
                "input_source": "financial_facts",
                "publishable": True,
                "status": "ok",
                "model_version": MODEL_VERSION,
                "scenario_style": "holding_discount_on_sotp",
                "fact_ids": {
                    **snapshot.fact_ids(),
                    "shares_diluted": shares_fact.id if shares_fact else None,
                    "net_debt": net_debt_fact.id if net_debt_fact else None,
                    "holding_company_discount": discount_fact.id,
                    **{
                        f"segment_{segment['name']}_operating_metric": segment["metric_fact_id"]
                        for segment in segments
                    },
                    **{
                        f"segment_{segment['name']}_valuation_multiple": segment["multiple_fact_id"]
                        for segment in segments
                    },
                },
                "periods": {
                    **snapshot.periods(),
                    "shares_diluted": shares_fact.period if shares_fact else None,
                    "net_debt": net_debt_fact.period if net_debt_fact else None,
                    "holding_company_discount": discount_fact.period,
                    **{
                        f"segment_{segment['name']}": segment["period"]
                        for segment in segments
                    },
                },
                "snapshot": {
                    "as_of": snapshot.as_of_period,
                    "income_statement": snapshot.income_statement,
                    "balance_sheet": snapshot.balance_sheet,
                    "shares": snapshot.shares_period,
                    "warnings": snapshot.warnings,
                },
                "sotp": base,
                "holding_discount_base": discount,
                "holding_discount_source": "financial_facts",
                "probability_method": "source_confidence_plus_holding_discount",
                "evidence_confidence": evidence_confidence,
                "missing_optional_segments": missing_segments,
                "segments_valued": [segment["name"] for segment in segments],
                "scenarios": scenario_results,
                "weighted": weighted["trace"],
            },
            }
        )
