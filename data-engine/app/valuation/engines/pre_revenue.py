"""Pre-revenue / speculative scenario engine with funding-gap dilution.

Supuestos: DCF a 5 años con ingresos floor de 1.0 (permite revenue ~0 sin
romper la matemática) y margen acotado a [1%, 40%]; crecimiento de facts o
``default_growth`` (20% para tags pre-FCF/speculative) acotado a
[-15%, +60%]; WACC de un ``CalculatedMetric`` trazable y, si no existe, 13%
por defecto en estos nombres (que entonces bloquea la publicación);
escenarios causales (retraso de ejecución/estrés de financiación,
comercialización base, monetización acelerada) con dilución extra por
escenario (bear ≥ 15%, cap 80% sobre el valor); funding gap estimado de
caja/OCF/capex con horizonte de 2 años y buffer de 50. Sensibilidad: grid
crecimiento × WACC; sin ingresos coherentes devuelve insufficient_data (no
bootstrap). ``net_debt`` ausente nunca es 0: se declara como input faltante.
"""

from __future__ import annotations

from dataclasses import replace

from app.services.inferred_input_service import InferredInputService
from app.valuation.dcf_fcff import (
    ConvergenceDCFInputs,
    DCFInputs,
    run_dcf,
    run_dcf_margin_convergence,
)
from app.valuation.engines.base import (
    MODEL_VERSION,
    NET_DEBT_REQUIRED_REASON,
    ValuationContext,
    ValuationEngine,
    adr_ratio,
    apply_publication_blockers,
    default_growth,
    expected_value_or_nd,
    insufficient_from_context,
    insufficient_result,
    insufficient_with_moat,
    is_adr_without_ratio,
    margin_of_safety,
    normalize_scenario_display,
    resolve_rates,
)
from app.valuation.funding_gap import estimate_funding_gap
from app.valuation.moat_framework import empty_moat_framework
from app.valuation.reverse_dcf import ReverseDCFInputs, solve_required_growth
from app.valuation.scenario_definitions import (
    evidence_weighted_probabilities,
    speculative_causal_scenarios,
)
from app.valuation.scenario_model import Scenario, probability_weighted_value
from app.valuation.sensitivity import sensitivity_grid


class PreRevenueScenarioEngine(ValuationEngine):
    """Nombres pre-revenue/especulativos: escenarios causales + dilución por funding gap.

    Supuestos: requiere snapshot coherente (revenue + acciones) más drivers
    operativos; mapea 3 escenarios causales a bear/base/bull compatibles con
    la API; expone grid de sensibilidad y reverse DCF. Sin facts coherentes
    devuelve insufficient_data con la lista de inputs operativos requeridos.
    """

    key = "pre_revenue"

    def value(self, context: ValuationContext) -> dict:
        """ADR: el filing da acciones ORDINARIAS y el precio es del ADR (N
        ordinarias). Todo el cálculo (margen, DCF inverso, rango indicativo) se
        hace con el precio por ordinaria, como en standard_dcf; el resultado
        conserva el precio cotizado y añade los valores por ADR."""
        company = context.company
        listed_price = context.current_price
        if is_adr_without_ratio(company):
            return insufficient_result(
                ticker=company.ticker,
                model_type=company.valuation_model,
                engine_key=self.key,
                current_price=listed_price,
                missing_inputs=["adr_ratio"],
                reason=(
                    f"{company.ticker} is quoted as an ADR but the ordinary-shares-per-ADR "
                    "ratio is unknown, so value per share and the quoted price are not on "
                    "the same basis."
                ),
                snapshot=context.snapshot,
            )
        ratio = adr_ratio(company)
        if not ratio:
            return self._value_ordinary(context)
        comparable = listed_price / ratio if listed_price else listed_price
        result = self._value_ordinary(replace(context, current_price=comparable))
        result["current_price"] = listed_price
        result["adr_ratio"] = ratio
        result["value_per_share_basis"] = "ordinary_share"
        result["comparable_price_basis"] = "ordinary_share"
        values = {
            name: result.get(f"{name}_value")
            for name in ("bear", "base", "bull", "expected")
        }
        result["listed_share_values"] = (
            {name: value * ratio for name, value in values.items()}
            if all(value is not None for value in values.values())
            else None
        )
        return result

    def _margin_convergence_orientation(
        self,
        context: ValuationContext,
        snapshot,
        current_price: float | None,
        *,
        reported_margin: float,
    ) -> dict | None:
        """Orientación por convergencia de margen para growth con margen inmaduro.

        Solo si existe un margen FCF OBJETIVO inferido y validado (base
        explícita + URLs https, positivo). Resultado SIEMPRE orientativo
        (blocker ``inferred_fcf_margin_target``): los supuestos son el margen
        reportado (hecho) y el objetivo (inferencia marcada); nada se inventa.
        None = sin base para converger: el llamador mantiene el N/D explicado.
        """
        company = context.company
        if context.db is None or company.id is None:
            return None
        target_input = InferredInputService().latest_valid(context.db, company.id, "fcf_margin")
        if target_input is None:
            return None
        target_margin = float(target_input.value)
        if target_margin <= 0:
            return None
        revenue = snapshot.value("revenue")
        shares = snapshot.value("shares_diluted")
        net_debt = snapshot.value("net_debt")
        if revenue is None or revenue <= 0 or shares is None or net_debt is None:
            return None

        growth = snapshot.value("revenue_growth")
        if growth is None:
            growth = default_growth(company)
        growth = max(min(growth, 0.60), -0.15)
        wacc, wacc_source, terminal, _terminal_source, _dropped = resolve_rates(
            context.db, company, as_of=context.as_of
        )

        scenario_defs = {
            "bear": {
                "revenue_growth": max(growth - 0.08, -0.15),
                "wacc": wacc + 0.02,
            },
            "base": {"revenue_growth": growth, "wacc": wacc},
            "bull": {
                "revenue_growth": min(growth + 0.08, 0.60),
                "wacc": max(wacc - 0.01, terminal + 0.01),
            },
        }
        scenario_values: dict[str, float | None] = {}
        scenario_traces: dict = {}
        for name, assumptions in scenario_defs.items():
            try:
                dcf = run_dcf_margin_convergence(
                    ConvergenceDCFInputs(
                        revenue=revenue,
                        revenue_growth=assumptions["revenue_growth"],
                        initial_fcf_margin=reported_margin,
                        target_fcf_margin=target_margin,
                        wacc=assumptions["wacc"],
                        terminal_growth=terminal,
                        net_debt=net_debt,
                        shares_outstanding=shares,
                    )
                )
                value: float | None = dcf.value_per_share
                trace = dcf.trace
            except ValueError:
                # Ni convergiendo se alcanza un FCF terminal positivo: el
                # escenario no es valorable (N/D explicado abajo).
                value = None
                trace = {"error": "converged_fcf_not_positive"}
            scenario_values[name] = value
            scenario_traces[name] = {
                "definition": {"name": name, "assumptions": assumptions},
                "value_per_share": value,
                "trace": trace,
            }

        probabilities = evidence_weighted_probabilities(
            evidence_confidence=0.0, directional_signal=0.0, downside_risk=0.0
        )
        weighted = probability_weighted_value(
            [Scenario(name, probabilities[name], v) for name, v in scenario_values.items() if v is not None]
            or [Scenario("base", 1.0, 0.0)]
        )
        # El esperado se pondera con los brutos disponibles; los N/D (no
        # calculables) no pueden aportar y se declaran en scenario_notes.
        expected_raw = weighted["expected_value"] if any(
            v is not None for v in scenario_values.values()
        ) else 0.0
        expected, expected_note = expected_value_or_nd(expected_raw)
        display, scenario_notes = normalize_scenario_display(
            scenario_values, scenario_traces=scenario_traces
        )
        if expected_note:
            scenario_notes["expected"] = expected_note

        ratio = adr_ratio(company)
        comparable_price = current_price / ratio if (ratio and current_price) else current_price
        blockers = ["inferred_fcf_margin_target"]
        if wacc_source != "calculated_metric":
            blockers.append("traceable_wacc")
        return apply_publication_blockers(
            {
                "ticker": company.ticker,
                "model_type": company.valuation_model,
                "status": "ok",
                "publishable": True,
                "current_price": current_price,
                "bear_value": display["bear"],
                "base_value": display["base"],
                "bull_value": display["bull"],
                "expected_value": expected,
                "margin_of_safety": margin_of_safety(expected, comparable_price),
                "missing_inputs": [],
                "publication_blockers": blockers,
                "adr_ratio": ratio,
                "value_per_share_basis": "ordinary_share",
                "listed_share_values": None,
                "comparable_price_basis": "ordinary_share" if ratio else "listed_share",
                "scenario_notes": scenario_notes,
                "reverse_dcf": {},
                "sensitivity": {"rows": []},
                "moat": empty_moat_framework(
                    company.company_type, company.factor_tags or [], company.special_risks or []
                ),
                "trace": {
                    "method": "fcff_dcf_margin_convergence",
                    "engine": self.key,
                    "input_source": "financial_facts+inferred_target",
                    "publishable": False,
                    "status": "ok",
                    "model_version": MODEL_VERSION,
                    "reported_fcf_margin": reported_margin,
                    "target_fcf_margin": target_margin,
                    "target_fcf_margin_input_id": target_input.id,
                    "target_fcf_margin_base": target_input.base,
                    "target_fcf_margin_source_urls": list(target_input.source_urls or []),
                    "revenue_growth": growth,
                    "wacc": wacc,
                    "wacc_source": wacc_source,
                    "terminal_growth": terminal,
                    "expected_value_raw": expected_raw,
                    "scenario_notes": scenario_notes,
                    "scenarios": scenario_traces,
                    "probabilities": probabilities,
                    "fact_ids": snapshot.fact_ids(),
                    "periods": snapshot.periods(),
                    "publication_blockers": blockers,
                },
            }
        )

    def _value_ordinary(self, context: ValuationContext) -> dict:
        company = context.company
        snapshot = context.snapshot
        current_price = context.current_price

        rejected = self._reported_non_positive_fcf(company, snapshot, current_price)
        if rejected is not None:
            # Antes de negar: growth con margen inmaduro y un objetivo de margen
            # inferido validado (base + URLs) obtiene una ORIENTACION por
            # convergencia de margen. Sin objetivo con fuente, N/D explicado.
            reported = snapshot.value("fcf_margin")
            if reported is None:
                fcf = snapshot.value("free_cash_flow")
                rev = snapshot.value("revenue")
                reported = (fcf / rev) if (fcf is not None and rev) else None
            if reported is not None and reported <= 0:
                convergence = self._margin_convergence_orientation(
                    context, snapshot, current_price, reported_margin=float(reported)
                )
                if convergence is not None:
                    return convergence
            return rejected

        # Still refuse bootstrap — speculative names need at least revenue + shares.
        if not snapshot.coherent:
            shares = snapshot.value("shares_diluted")
            if current_price is not None and current_price > 0 and shares is not None and shares > 0:
                # Precio de mercado + acciones (con o sin revenue coherente)
                # pero sin margen/FCF: rango indicativo con supuestos
                # documentados en vez de NO VALUATION. Nunca final.
                # Sin acciones no hay matematica por-accion posible.
                return self._indicative_partial(
                    company, snapshot, current_price, context.db, context.as_of
                )
            return insufficient_from_context(
                context,
                missing=snapshot.missing_inputs
                + [
                    "deployment_curve_or_capacity_plan",
                    "funding_plan",
                    "dilution_schedule",
                ],
                reason=(
                    "Pre-revenue/speculative valuation requires a coherent financial snapshot "
                    "plus operational drivers. Generic bootstrap DCF is disabled."
                ),
                extra_trace={
                    "required_operational_inputs": [
                        "satellites_or_capacity_deployed",
                        "revenue_ramp",
                        "constellation_capex",
                        "financing_and_dilution",
                    ]
                },
            )

        revenue = snapshot.value("revenue")
        shares = snapshot.value("shares_diluted")
        assert revenue is not None and shares is not None

        margin = snapshot.value("fcf_margin")
        inferred_margin = None
        if margin is None:
            fcf = snapshot.value("free_cash_flow")
            if fcf is None and context.db is not None and company.id is not None:
                # Sin FCF reportado: un margen FCF INFERIDO con base explicita y
                # URLs https (validado) permite escenarios. Nunca es un fact y el
                # resultado queda marcado como no publicable.
                inferred_margin = InferredInputService().latest_valid(
                    context.db, company.id, "fcf_margin"
                )
                if inferred_margin is not None:
                    margin = float(inferred_margin.value)
            if margin is not None:
                pass
            elif fcf is None or revenue <= 0:
                return insufficient_from_context(
                    context,
                    missing=["normalized_fcf_or_fcf_margin"],
                    reason="Cannot derive FCF margin for speculative scenario DCF.",
                )
            else:
                margin = fcf / revenue

        if margin <= 0:
            # Un margen FCF reportado negativo es quema de caja. Un DCF FCFF
            # sobre ese signo da un EV y un valor por accion NEGATIVOS (ASTS:
            # -84,70 USD/accion con un margen de -15,46) que se publicaban como
            # bear/base/bull. El capital propio no vale menos de cero. Un margen
            # INFERIDO solo sustituye a un FCF AUSENTE (mas arriba), nunca a uno
            # reportado: el dato reportado gana.
            # Empresa de alto crecimiento con margen inmaduro (RKLB, 30-oct-2026:
            # «es imposible que el valor justo sea -94 %»): con un margen FCF
            # OBJETIVO inferido y validado (base explicita + URLs https) se
            # publica una ORIENTACION por convergencia de margen (del reportado
            # al objetivo en 5 anos), nunca una valoracion final. Sin objetivo
            # con fuente, se niega, como standard_dcf.
            convergence = self._margin_convergence_orientation(
                context, snapshot, current_price, reported_margin=margin
            )
            if convergence is not None:
                return convergence
            return insufficient_from_context(
                context,
                missing=["non_negative_fcf_margin"],
                reason=(
                    f"El margen FCF reportado es {margin:.4f} (quema de caja): "
                    "un DCF FCFF daria un valor por acción negativo. No se "
                    "publica rango por acción sin un margen normalizado con "
                    "fuente."
                ),
            )

        # Near-zero revenue speculative names: still allow but flag low confidence.
        growth = snapshot.value("revenue_growth")
        growth_source = "financial_facts" if growth is not None else "tag_default"
        if growth is None:
            growth = default_growth(company)

        growth = max(min(growth, 0.60), -0.15)
        # El margen no positivo ya fue rechazado, nunca se eleva a +1%.
        # Solo se limita el extremo alto para los escenarios especulativos.
        margin = min(margin, 0.40)
        wacc, wacc_source, terminal, terminal_source, dropped_inferred = resolve_rates(context.db, company, as_of=context.as_of)
        net_debt = snapshot.value("net_debt")
        if net_debt is None:
            # El puente de equity es EV - net_debt. Heredarlo como 0.0 no dice
            # "sin deuda": dice "deuda desconocida" y aun asi inventa equity.
            # Una biotech con EV 400M y 150M de caja no ingerida pasaria de
            # 2,00 a 1,25 EUR/accion sobre 200M de acciones (+60% de sobrevalor)
            # sin un solo fact detras. Mismo criterio que standard_dcf.
            return insufficient_from_context(
                context,
                missing=["net_debt"],
                reason=NET_DEBT_REQUIRED_REASON,
            )

        # Preliminary base for funding-gap dilution estimate.
        base_preview = run_dcf(
            DCFInputs(
                revenue=max(revenue, 1.0),
                revenue_growth=growth,
                fcf_margin=margin,
                wacc=wacc,
                terminal_growth=terminal,
                net_debt=net_debt,
                shares_outstanding=shares,
            )
        )
        funding = estimate_funding_gap(
            snapshot,
            current_price=current_price,
            value_per_share=base_preview.value_per_share,
        )
        dilution_pct = 0.0
        if funding.dilution:
            dilution_pct = float(funding.dilution.get("dilution_pct") or 0.0)

        evidence_confidence = sum(float(fact.confidence) for fact in snapshot.facts.values()) / len(
            snapshot.facts
        )
        scenarios = speculative_causal_scenarios(
            growth,
            margin,
            wacc,
            terminal,
            dilution_pct,
            evidence_confidence,
        )
        scenario_results = {}
        for scenario in scenarios:
            dcf = run_dcf(
                DCFInputs(
                    revenue=max(revenue, 1.0),
                    revenue_growth=float(scenario.assumptions["revenue_growth"]),
                    fcf_margin=float(scenario.assumptions["fcf_margin"]),
                    wacc=float(scenario.assumptions["wacc"]),
                    terminal_growth=float(scenario.assumptions["terminal_growth"]),
                    net_debt=net_debt,
                    shares_outstanding=shares,
                )
            )
            extra_dilution = float(scenario.assumptions.get("extra_dilution_pct") or 0.0)
            # La dilución recorta un valor positivo. Multiplicar un valor
            # NEGATIVO (quema de caja) lo acercaría a cero y rompería el
            # orden bear <= base <= bull: una quema diluida no vale menos
            # negativo.
            value = dcf.value_per_share
            if value > 0:
                value *= 1.0 - min(extra_dilution, 0.80)
            scenario_results[scenario.name] = {
                "definition": {
                    "name": scenario.name,
                    "probability": scenario.probability,
                    "drivers": scenario.drivers,
                    "description": scenario.description,
                    "assumptions": scenario.assumptions,
                },
                "value_per_share": value,
                "undiluted_value_per_share": dcf.value_per_share,
                "trace": dcf.trace,
            }

        # Map causal names to bear/base/bull for API compatibility.
        ordered = list(scenario_results.values())
        bear_v = ordered[0]["value_per_share"]
        base_v = ordered[1]["value_per_share"]
        bull_v = ordered[2]["value_per_share"]

        weighted = probability_weighted_value(
            [
                Scenario(s["definition"]["name"], s["definition"]["probability"], s["value_per_share"])
                for s in ordered
            ]
        )
        expected = weighted["expected_value"]

        reverse = {}
        if current_price is not None and current_price > 0:
            reverse = solve_required_growth(
                ReverseDCFInputs(
                    market_price=current_price,
                    revenue=max(revenue, 1.0),
                    fcf_margin=margin,
                    wacc=wacc,
                    terminal_growth=terminal,
                    net_debt=net_debt,
                    shares_outstanding=shares,
                )
            )

        sensitivity = sensitivity_grid(
            DCFInputs(
                revenue=max(revenue, 1.0),
                revenue_growth=growth,
                fcf_margin=margin,
                wacc=wacc,
                terminal_growth=terminal,
                net_debt=net_debt,
                shares_outstanding=shares,
            ),
            growth_values=[growth - 0.05, growth, growth + 0.05],
            wacc_values=[wacc - 0.01, wacc, wacc + 0.02],
        )

        publishable = funding.status != "incomplete" and inferred_margin is None
        status = "ok" if publishable else "partial"
        missing = list(funding.missing_inputs) if funding.status == "incomplete" else []
        # Sin un CalculatedMetric fechado el WACC es un supuesto por tags: no
        # hay forma de trazar la tasa que decide el valor terminal. Con g
        # terminal 2,5% el spread 10,5pp frente al 6,0pp real baja el factor
        # de descuento del TV de 1,80 a 1,29 (~-35% de valor por accion). Se
        # publica igual como orientacion, nunca como valoracion final.
        publication_blockers: list[str] = []
        if wacc_source != "calculated_metric":
            publication_blockers.append("traceable_wacc")

        notices = []
        if not publishable:
            notices.append(
                "Scenario values computed but funding-gap dilution is incomplete; "
                "treat as non-final."
            )
        if publication_blockers:
            if wacc_source == "inferred_input":
                notices.append(
                    "WACC is an INFERRED input (documented basis and URLs), not a "
                    "traceable CalculatedMetric: treat the value as non-final."
                )
            else:
                notices.append(
                    "WACC is a tag default with no traceable CalculatedMetric: the discount "
                    "rate is an assumption, not a dated source."
                )
        if dropped_inferred:
            notices.append(
                "Inferred inputs ignored because wacc - terminal_growth < 2pp: "
                + ", ".join(dropped_inferred)
            )

        return apply_publication_blockers(
            {
            "ticker": company.ticker,
            "model_type": company.valuation_model,
            "status": status,
            "publishable": publishable,
            "current_price": current_price,
            "bear_value": bear_v,
            "base_value": base_v,
            "bull_value": bull_v,
            "expected_value": expected,
            "margin_of_safety": margin_of_safety(expected, current_price),
            "missing_inputs": missing,
            "publication_blockers": publication_blockers,
            "reverse_dcf": reverse,
            "sensitivity": sensitivity,
            "moat": empty_moat_framework(
                company.company_type, company.factor_tags or [], company.special_risks or []
            ),
            "trace": {
                "method": company.valuation_model,
                "engine": self.key,
                "input_source": "financial_facts",
                "publishable": publishable,
                "status": status,
                "publication_blockers": publication_blockers,
                "model_version": MODEL_VERSION,
                "growth_source": growth_source,
                "wacc": wacc,
                "wacc_source": wacc_source,
                "terminal_source": terminal_source,
                "inferred_inputs_ignored": dropped_inferred,
                "net_debt": net_debt,
                "valuation_basis": (
                    "inferred_inputs" if inferred_margin is not None else "reported_facts"
                ),
                "inferred_inputs": (
                    [
                        {
                            "origen": "INFERIDO",
                            "input_key": inferred_margin.input_key,
                            "value": float(inferred_margin.value),
                            "base_inferencia": inferred_margin.base,
                            "urls_inferencia": list(inferred_margin.source_urls or []),
                            "inferred_input_id": inferred_margin.id,
                        }
                    ]
                    if inferred_margin is not None
                    else []
                ),
                "scenario_style": "causal_speculative",
                "probability_method": "source_confidence_plus_growth_and_funding_risk",
                "evidence_confidence": evidence_confidence,
                "fact_ids": snapshot.fact_ids(),
                "periods": snapshot.periods(),
                "snapshot": {
                    "as_of": snapshot.as_of_period,
                    "income_statement": snapshot.income_statement,
                    "balance_sheet": snapshot.balance_sheet,
                    "shares": snapshot.shares_period,
                    "warnings": snapshot.warnings,
                },
                "funding_gap": {
                    "status": funding.status,
                    "funding_gap": funding.funding_gap,
                    "available_cash": funding.available_cash,
                    "planned_capex": funding.planned_capex,
                    "burn_proxy": funding.burn_proxy,
                    "min_cash_buffer": funding.min_cash_buffer,
                    "min_cash_buffer_basis": funding.min_cash_buffer_basis,
                    "missing_inputs": funding.missing_inputs,
                    "dilution": funding.dilution,
                },
                "scenarios": scenario_results,
                "weighted": weighted["trace"],
                "notice": " ".join(notices) or None,
            },
            }
        )

    def _reported_non_positive_fcf(self, company, snapshot, current_price) -> dict | None:
        """Un dato reportado no se sustituye por un margen inferido."""
        rejected = {
            metric: float(value)
            for metric in ("fcf_margin", "free_cash_flow")
            if (value := snapshot.value(metric)) is not None and value <= 0
        }
        if not rejected:
            return None
        return insufficient_with_moat(
            company,
            engine_key=self.key,
            current_price=current_price,
            missing=list(snapshot.missing_inputs) + ["non_negative_fcf_margin"],
            reason=(
                "El FCF o margen FCF reportado es cero o negativo; un margen "
                "inferido no puede sustituir ese dato. Sin valor por acción "
                "hasta tener un margen normalizado con fuente."
            ),
            snapshot=snapshot,
            extra_trace={
                "rejected_reported_fcf": rejected,
                "observed_cash_burn": {
                    metric: float(value)
                    for metric in ("operating_cash_flow", "free_cash_flow")
                    if (value := snapshot.value(metric)) is not None and value < 0
                },
            },
        )

    def _indicative_partial(self, company, snapshot, current_price: float, db=None, as_of=None) -> dict:
        """Rango indicativo cuando hay precio + acciones sin snapshot coherente.

        Supuestos documentados (nunca facts): revenue floor $1 si no hay
        revenue coherente, margen FCF base 15% con banda bear/bull [1%, 35%],
        crecimiento y WACC tag-default. El reverse DCF usa los supuestos
        base. Status ``partial`` y ``publishable=False``: orientativo, no final.
        """
        rejected = self._reported_non_positive_fcf(company, snapshot, current_price)
        if rejected is not None:
            return rejected

        # Un margen FCF base de +15% es un SUPUESTO. Si los propios facts
        # reportan quema de caja (flujo operativo o FCF negativo), el supuesto
        # contradice el dato y el rango resultante (p. ej. ASTS: 0,80 USD/accion
        # con precio 58,86 y OCF -71,5M) seria un numero inventado presentado
        # como valoracion. Fail closed: sin valor por accion, con la causa.
        cash_facts = {
            metric: float(value)
            for metric in ("operating_cash_flow", "free_cash_flow")
            if (value := snapshot.value(metric)) is not None
        }
        observed_burn = {k: v for k, v in cash_facts.items() if v < 0}
        # Relajacion acotada: un margen FCF INFERIDO con base explicita y URLs
        # https permite escenarios (siempre publishable=False y marcados). Sin
        # base valida sigue fail-closed: sin numero.
        # Solo en la rama quema/sin dato de caja: con caja positiva no se
        # consulta ni se usa ningun input inferido.
        reported_margin = snapshot.value("fcf_margin")
        reported_fcf = snapshot.value("free_cash_flow")
        needs_inference = (
            reported_margin is None and reported_fcf is None
            and (bool(observed_burn) or not cash_facts)
        )
        inferred = (
            InferredInputService().latest_valid(db, company.id, "fcf_margin")
            if needs_inference and db is not None and company.id is not None
            else None
        )
        if needs_inference and (inferred is None or float(inferred.value) <= 0):
            return insufficient_with_moat(
                company,
                engine_key=self.key,
                current_price=current_price,
                missing=list(snapshot.missing_inputs)
                + ["normalized_fcf_or_fcf_margin"],
                reason=(
                    (
                        "Los facts reportan quema de caja ("
                        + ", ".join(f"{k}={v:.0f}" for k, v in observed_burn.items())
                        + "); un margen FCF base positivo supuesto contradice el dato. "
                        if observed_burn
                        else "Sin dato reportado de flujo de caja (operating_cash_flow / "
                        "free_cash_flow): el margen FCF seria un supuesto sin base. "
                    )
                    + "No se publica rango por acción hasta tener un margen FCF "
                    "normalizado o una curva de despliegue/financiacion con fuente."
                ),
                snapshot=snapshot,
                extra_trace={
                    "observed_cash_burn": observed_burn,
                    "required_operational_inputs": [
                        "satellites_or_capacity_deployed",
                        "revenue_ramp",
                        "constellation_capex",
                        "financing_and_dilution",
                    ],
                },
            )

        revenue = snapshot.value("revenue")
        revenue_assumed = revenue is None or revenue <= 0
        if revenue_assumed:
            revenue = 1.0
        else:
            revenue = float(revenue)
        shares = float(snapshot.value("shares_diluted"))
        growth = snapshot.value("revenue_growth")
        growth_source = "financial_facts" if growth is not None else "tag_default"
        if growth is None:
            growth = default_growth(company)
        growth = max(min(growth, 0.60), -0.15)
        assumed_margin_base = float(inferred.value) if inferred is not None else 0.15
        wacc, wacc_source, terminal, terminal_source, dropped_inferred = resolve_rates(db, company, as_of=as_of)
        net_debt = snapshot.value("net_debt")
        net_debt_missing = net_debt is None
        # El puente de equity sigue siendo EV - net_debt. Sin el dato, el
        # rango por accion es en realidad EV/acciones: asumir deuda cero
        # infla el valor exactamente net_debt/shares (2,00 vs 1,25 EUR sobre
        # 200M de acciones en una biotech con 150M de caja no ingerida). Se
        # declara como supuesto explicito en vez de presentarlo como equity.
        net_debt_used = 0.0 if net_debt is None else float(net_debt)

        preview = run_dcf(
            DCFInputs(
                revenue=max(revenue, 1.0),
                revenue_growth=growth,
                fcf_margin=assumed_margin_base,
                wacc=wacc,
                terminal_growth=terminal,
                net_debt=net_debt_used,
                shares_outstanding=shares,
            )
        )
        funding = estimate_funding_gap(
            snapshot,
            current_price=current_price,
            value_per_share=preview.value_per_share,
        )
        dilution_pct = 0.0
        if funding.dilution:
            dilution_pct = float(funding.dilution.get("dilution_pct") or 0.0)

        scenarios = speculative_causal_scenarios(
            growth, assumed_margin_base, wacc, terminal, dilution_pct, 0.5
        )
        scenario_results = {}
        for scenario in scenarios:
            dcf = run_dcf(
                DCFInputs(
                    revenue=max(revenue, 1.0),
                    revenue_growth=float(scenario.assumptions["revenue_growth"]),
                    fcf_margin=float(scenario.assumptions["fcf_margin"]),
                    wacc=float(scenario.assumptions["wacc"]),
                    terminal_growth=float(scenario.assumptions["terminal_growth"]),
                    net_debt=net_debt_used,
                    shares_outstanding=shares,
                )
            )
            extra_dilution = float(scenario.assumptions.get("extra_dilution_pct") or 0.0)
            # La dilución recorta un valor positivo. Multiplicar un valor
            # NEGATIVO (quema de caja) lo acercaría a cero y rompería el
            # orden bear <= base <= bull: una quema diluida no vale menos
            # negativo.
            value = dcf.value_per_share
            if value > 0:
                value *= 1.0 - min(extra_dilution, 0.80)
            scenario_results[scenario.name] = {
                "definition": {
                    "name": scenario.name,
                    "probability": scenario.probability,
                    "drivers": scenario.drivers,
                    "description": scenario.description,
                    "assumptions": scenario.assumptions,
                },
                "value_per_share": value,
                "undiluted_value_per_share": dcf.value_per_share,
                "trace": dcf.trace,
            }

        ordered = list(scenario_results.values())
        bear_v = ordered[0]["value_per_share"]
        base_v = ordered[1]["value_per_share"]
        bull_v = ordered[2]["value_per_share"]
        weighted = probability_weighted_value(
            [
                Scenario(s["definition"]["name"], s["definition"]["probability"], s["value_per_share"])
                for s in ordered
            ]
        )
        expected = weighted["expected_value"]

        reverse = solve_required_growth(
            ReverseDCFInputs(
                market_price=current_price,
                revenue=max(revenue, 1.0),
                fcf_margin=assumed_margin_base,
                wacc=wacc,
                terminal_growth=terminal,
                net_debt=net_debt_used,
                shares_outstanding=shares,
            )
        )
        sensitivity = sensitivity_grid(
            DCFInputs(
                revenue=max(revenue, 1.0),
                revenue_growth=growth,
                fcf_margin=assumed_margin_base,
                wacc=wacc,
                terminal_growth=terminal,
                net_debt=net_debt_used,
                shares_outstanding=shares,
            ),
            growth_values=[growth - 0.05, growth, growth + 0.05],
            wacc_values=[wacc - 0.01, wacc, wacc + 0.02],
        )
        missing = list(snapshot.missing_inputs)
        if net_debt_missing and "net_debt" not in missing:
            missing.append("net_debt")
        # El rango sigue siendo orientativo, pero deja de ser un valor de
        # equity: se declara que falta el dato y que el WACC es un supuesto.
        publication_blockers: list[str] = []
        if net_debt_missing:
            publication_blockers.append("net_debt")
        if wacc_source != "calculated_metric":
            publication_blockers.append("traceable_wacc")

        return apply_publication_blockers(
            {
            "ticker": company.ticker,
            "model_type": company.valuation_model,
            "status": "partial",
            "publishable": False,
            "current_price": current_price,
            "bear_value": bear_v,
            "base_value": base_v,
            "bull_value": bull_v,
            "expected_value": expected,
            "margin_of_safety": margin_of_safety(expected, current_price),
            "missing_inputs": missing,
            "publication_blockers": publication_blockers,
            "reverse_dcf": reverse,
            "sensitivity": sensitivity,
            "moat": empty_moat_framework(
                company.company_type, company.factor_tags or [], company.special_risks or []
            ),
            "trace": {
                "method": company.valuation_model,
                "engine": self.key,
                "input_source": "financial_facts",
                "valuation_basis": (
                    "inferred_inputs" if inferred is not None else "indicative_assumptions"
                ),
                "inferred_inputs": (
                    [
                        {
                            "origen": "INFERIDO",
                            "input_key": inferred.input_key,
                            "value": float(inferred.value),
                            "base_inferencia": inferred.base,
                            "urls_inferencia": list(inferred.source_urls or []),
                            "inferred_input_id": inferred.id,
                            "observed_cash_burn": observed_burn,
                        }
                    ]
                    if inferred is not None
                    else []
                ),
                "publishable": False,
                "status": "partial",
                "publication_blockers": publication_blockers,
                "model_version": MODEL_VERSION,
                "growth_source": growth_source,
                "wacc": wacc,
                "wacc_source": wacc_source,
                "terminal_source": terminal_source,
                "inferred_inputs_ignored": dropped_inferred,
                "net_debt": net_debt,
                "net_debt_source": "missing_assumed_zero" if net_debt_missing else "financial_facts",
                "scenario_style": "causal_speculative_indicative",
                "probability_method": "source_confidence_plus_growth_and_funding_risk",
                "fact_ids": snapshot.fact_ids(),
                "periods": snapshot.periods(),
                "assumed": {
                    "revenue_floor_used": revenue_assumed,
                    "revenue_base": revenue,
                    "fcf_margin_base": assumed_margin_base,
                    "fcf_margin_band": [float(sc.assumptions["fcf_margin"]) for sc in scenarios],
                    "revenue_growth": growth,
                    "wacc": wacc,
                    "terminal_growth": terminal,
                    "reason": (
                        "Snapshot has revenue+shares but no coherent FCF margin; "
                        "indicative band used instead of blocking valuation."
                    ),
                },
                "snapshot": {
                    "as_of": snapshot.as_of_period,
                    "income_statement": snapshot.income_statement,
                    "balance_sheet": snapshot.balance_sheet,
                    "shares": snapshot.shares_period,
                    "warnings": snapshot.warnings,
                },
                "funding_gap": {
                    "status": funding.status,
                    "funding_gap": funding.funding_gap,
                    "missing_inputs": funding.missing_inputs,
                    "dilution": funding.dilution,
                },
                "scenarios": scenario_results,
                "weighted": weighted["trace"],
                "notice": (
                    "INDICATIVE RANGE — uses assumed FCF margin "
                    f"(base {assumed_margin_base:.0%}, band "
                    f"{min(float(sc.assumptions['fcf_margin']) for sc in scenarios):.0%}"
                    f"-{max(float(sc.assumptions['fcf_margin']) for sc in scenarios):.0%})"
                    + (" and $1 revenue floor (no coherent revenue)" if revenue_assumed else "")
                    + " because no coherent snapshot exists. Not a final fair value; "
                    "resolve missing inputs before publishing."
                    + (
                        " Per-share figures are EV/shares, not equity: net_debt is "
                        "unknown, so assuming zero debt would overstate the equity by "
                        "net_debt/shares."
                        if net_debt_missing
                        else ""
                    )
                ),
            },
            }
        )
