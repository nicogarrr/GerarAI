"""Standard FCFF DCF engine — only runs on coherent financial_facts snapshots.

Supuestos: DCF a 5 años sobre ``revenue`` y ``fcf_margin`` del snapshot
coherente (margen = FCF/ingresos si falta, acotado a [1%, 50%]); crecimiento
de ingresos de facts o ``default_growth`` acotado a [-15%, +45%]; WACC y
terminal de ``default_wacc``/``default_terminal_growth`` (fuente
``tag_default``); ``net_debt`` del snapshot (negativo = caja neta, suma a
equity). Escenarios bear/base/bull mecánicos anclados a facts
(±8pp crecimiento, ±6pp margen, WACC +2pp/−1pp) con probabilidades
ponderadas por confianza de evidencia; sensibilidad: grid 3×3
crecimiento × WACC; reverse DCF: crecimiento requerido al precio actual.
"""

from __future__ import annotations

from app.valuation.dcf_fcff import DCFInputs, run_dcf
from app.valuation.engines.base import (
    MODEL_VERSION,
    ValuationContext,
    ValuationEngine,
    adr_ratio,
    apply_publication_blockers,
    clamp_fcf_margin,
    default_growth,
    insufficient_result,
    is_adr_without_ratio,
    margin_of_safety,
    resolve_rates,
)
from app.valuation.moat_framework import empty_moat_framework
from app.valuation.reverse_dcf import ReverseDCFInputs, solve_required_growth
from app.valuation.scenario_definitions import mechanical_dcf_scenarios
from app.valuation.scenario_model import Scenario, probability_weighted_value
from app.valuation.sensitivity import sensitivity_grid

# The facts the standard FCFF DCF actually reads. Used to scope
# ``evidence_confidence`` so unrelated ingested facts cannot move the
# scenario probabilities.
MODEL_INPUT_METRICS = frozenset(
    {"revenue", "fcf_margin", "free_cash_flow", "revenue_growth", "net_debt", "shares_diluted"}
)


_SCENARIO_LABEL_ES = {"bear": "bajista", "base": "base", "bull": "alcista"}


def _num_es(value: float, digits: int = 2) -> str:
    """Cifra en formato español (coma decimal), sin notación científica."""
    return f"{value:.{digits}f}".replace(".", ",")


def _pct_es(ratio: float) -> str:
    return f"{_num_es(ratio * 100)} %"


def _scenario_nd_note(name: str, raw_value: float | None, scenario_margin: float) -> str:
    """Por qué un escenario sale N/D (convención d2656966: una cifra <= 0 no
    es una valoración publicable, igual que un P/E negativo no es un múltiplo).

    El valor bruto se conserva en la traza (``value_per_share_raw``) y sigue
    contando en el valor esperado ponderado: excluirlo inflaría el esperado y
    rompería el orden bear <= base."""
    label = _SCENARIO_LABEL_ES.get(name, name)
    if raw_value is None:
        return f"Escenario {label}: el modelo no produjo un valor por acción calculable: N/D."
    if scenario_margin <= 0:
        return (
            f"Escenario {label}: con el margen FCF de este escenario ({_pct_es(scenario_margin)}) "
            "la empresa quema más caja de la que genera y el valor por acción sale "
            f"{_num_es(raw_value)}. Una cifra negativa no es una valoración publicable: N/D. "
            "El valor esperado sí la tiene en cuenta."
        )
    return (
        f"Escenario {label}: la deuda y las obligaciones superan el valor del negocio "
        f"en este escenario y el valor por acción sale {_num_es(raw_value)}. "
        "Una cifra negativa no es una valoración publicable: N/D. "
        "El valor esperado sí la tiene en cuenta."
    )


def _normalized_fcf_margin(
    context: "ValuationContext", snapshot
) -> tuple[float | None, dict | None]:
    """Margen FCF del DCF como mediana de los ultimos 3 ejercicios fiscales.

    Motivacion: KO tenia un margen del ultimo FY de 10,1 % frente a 21,3 % y
    22,2 % de los dos anteriores (caida puntual del flujo operativo con
    beneficio estable, hechos SEC reales) y usar el ultimo ano en crudo
    deprimia la base de forma severa. La magnitud exacta observada en prod
    durante el analisis no es reproducible de forma aislada (depende de los
    demas supuestos del motor: WACC, crecimiento, terminal); la auditoria
    externa con supuestos propios obtuvo otra magnitud en la misma direccion.

    Reglas: con >= 2 FY la mediana resiste un ano puntual; con 1 FY se
    mantiene el comportamiento anterior. Guarda de tendencia: con caidas en
    todos los pares consecutivos del historial (tendencia monotona a la
    baja) la mediana sobrevalora, asi que se usa el ultimo FY
    (equivale a min(mediana, ultimo) en ese caso). La traza publica la
    normalizacion con los valores por periodo y la tendencia detectada.
    Nunca se inventa un margen que no salga de hechos.

    Limite conocido (preexistente): un margen negativo no tiene floor; esta
    normalizacion no cambia ese comportamiento.
    """
    latest = snapshot.value("fcf_margin")
    try:
        from app.valuation.financial_snapshot import _available_at, _facts_for_metric

        # Misma politica que el snapshot: elegibilidad/cuarentena, orden
        # fiscal_year desc + created_at desc y corte point-in-time por
        # ``filed`` cuando hay as_of (sin as_of no cambia el comportamiento).
        # Un replay historico no puede consumir FY publicados despues del
        # corte, y dos proveedores del mismo FY no ocupan dos plazas:
        # setdefault deja UN hecho por ejercicio (el primero del orden, el
        # mas reciente conocido en el corte).
        facts = _facts_for_metric(context.db, context.company.id, "fcf_margin")
        facts, _, _ = _available_at(facts, context.as_of)
    except Exception:  # noqa: BLE001 - sin historial, comportamiento anterior
        return latest, None
    by_year: dict[int, object] = {}
    for fact in facts:
        if fact.fiscal_quarter != "FY" or fact.fiscal_year is None:
            continue
        by_year.setdefault(fact.fiscal_year, fact)
    values = [
        {"period": fact.period, "fiscal_year": year, "value": float(fact.value)}
        for year, fact in sorted(by_year.items(), key=lambda kv: kv[0], reverse=True)[:3]
    ]
    if len(values) < 2:
        return latest, None
    ordered = sorted(item["value"] for item in values)
    n = len(ordered)
    median = ordered[n // 2] if n % 2 == 1 else (ordered[n // 2 - 1] + ordered[n // 2]) / 2
    # Tendencia sobre el historial reciente (values viene del mas nuevo al
    # mas viejo): caida monotona = todos los pares consecutivos caen.
    pairs_declining = all(
        values[i]["value"] < values[i + 1]["value"] for i in range(len(values) - 1)
    )
    pairs_rising = all(
        values[i]["value"] > values[i + 1]["value"] for i in range(len(values) - 1)
    )
    trend = "declining" if pairs_declining else "rising" if pairs_rising else "mixed"
    normalized = values[0]["value"] if trend == "declining" else median
    normalization = {
        "method": "median_last_n_fiscal_years",
        "n": n,
        "periods": values,
        "latest_value": values[0]["value"],
        "median_value": median,
        "trend": trend,
        "trend_guard_applied": trend == "declining",
        "normalized_value": normalized,
    }
    return normalized, normalization


class StandardDCFEngine(ValuationEngine):
    """DCF FCFF estándar sobre snapshot coherente.

    Supuestos: margen FCF acotado a [1%, 50%], crecimiento a [-15%, +45%],
    WACC/terminal por tags (ver ``base.default_wacc``); caja neta
    (``net_debt`` negativo) aumenta el equity. Expone bear/base/bull,
    grid de sensibilidad crecimiento × WACC y reverse DCF.
    """

    key = "standard_dcf"

    def value(self, context: ValuationContext) -> dict:
        company = context.company
        snapshot = context.snapshot
        current_price = context.current_price

        if not snapshot.coherent:
            result = insufficient_result(
                ticker=company.ticker,
                model_type=company.valuation_model,
                engine_key=self.key,
                current_price=current_price,
                missing_inputs=snapshot.missing_inputs,
                reason="Coherent financial snapshot required. Bootstrap assumptions are disabled.",
                snapshot=snapshot,
            )
            result["moat"] = empty_moat_framework(
                company.company_type, company.factor_tags or [], company.special_risks or []
            )
            return result

        revenue = snapshot.value("revenue")
        shares = snapshot.value("shares_diluted")
        assert revenue is not None and shares is not None

        if is_adr_without_ratio(company):
            # The filing reports ordinary shares and the quote is an ADR price.
            # Without the ratio, value per share is off by a factor of N, so
            # the engine refuses rather than publishing an 8x error.
            result = insufficient_result(
                ticker=company.ticker,
                model_type=company.valuation_model,
                engine_key=self.key,
                current_price=current_price,
                missing_inputs=["adr_ratio"],
                reason=(
                    f"{company.ticker} is quoted as an ADR but the ordinary-shares-per-ADR "
                    "ratio is unknown, so shares_diluted and the quoted price are not "
                    "on the same basis."
                ),
                snapshot=snapshot,
            )
            result["moat"] = empty_moat_framework(
                company.company_type, company.factor_tags or [], company.special_risks or []
            )
            return result

        margin, margin_normalization = _normalized_fcf_margin(context, snapshot)
        if margin is None:
            fcf = snapshot.value("free_cash_flow")
            if fcf is None:
                result = insufficient_result(
                    ticker=company.ticker,
                    model_type=company.valuation_model,
                    engine_key=self.key,
                    current_price=current_price,
                    missing_inputs=["normalized_fcf_or_fcf_margin"],
                    reason="FCF margin cannot be derived from the coherent snapshot.",
                    snapshot=snapshot,
                )
                result["moat"] = empty_moat_framework(
                    company.company_type, company.factor_tags or [], company.special_risks or []
                )
                return result
            margin = fcf / revenue

        if margin <= 0:
            # A known-negative FCF margin means the company consumes cash. The
            # FCFF DCF cannot represent that: clamping the floor to +1% would
            # turn a reported burn into a positive enterprise value. Refuse
            # instead of publishing a sign-flipped valuation.
            result = insufficient_result(
                ticker=company.ticker,
                model_type=company.valuation_model,
                engine_key=self.key,
                current_price=current_price,
                missing_inputs=["non_negative_fcf_margin"],
                reason=(
                    f"Sourced FCF margin is {margin:.4f} (the company burns cash). "
                    "A FCFF DCF cannot value a negative FCF margin without "
                    "misrepresenting it; use a funding-gap / dilution model."
                ),
                snapshot=snapshot,
            )
            result["moat"] = empty_moat_framework(
                company.company_type, company.factor_tags or [], company.special_risks or []
            )
            return result

        growth = snapshot.value("revenue_growth")
        if growth is None:
            raw_growth = default_growth(company)
            growth_source = "tag_default"
        else:
            raw_growth = growth
            growth_source = "financial_facts"

        raw_margin = margin
        growth = max(min(raw_growth, 0.45), -0.15)
        margin, margin_clamped = clamp_fcf_margin(margin, ceiling=0.50)

        wacc, wacc_source, terminal, terminal_source, dropped_inferred = resolve_rates(
            context.db, company, as_of=context.as_of
        )

        net_debt = snapshot.value("net_debt")
        if net_debt is None:
            # Missing net debt is never treated as "debt-free": the equity
            # bridge is EV - net_debt, so 0.0 would invent equity out of thin
            # air and inflate value per share by exactly net_debt / shares.
            result = insufficient_result(
                ticker=company.ticker,
                model_type=company.valuation_model,
                engine_key=self.key,
                current_price=current_price,
                missing_inputs=["net_debt"],
                reason=(
                    "net_debt is required for the equity bridge (EV - net debt) and "
                    "must not be assumed to be zero."
                ),
                snapshot=snapshot,
            )
            result["moat"] = empty_moat_framework(
                company.company_type, company.factor_tags or [], company.special_risks or []
            )
            return result

        # Puente completo EV -> equity: también restan los intereses
        # minoritarios y las acciones preferentes cuando el emisor los declara
        # (sin hecho = no existen; se deja constancia en la traza).
        minority_interest = snapshot.value("minority_interest") or 0.0
        preferred_stock = snapshot.value("preferred_stock") or 0.0
        base_inputs = DCFInputs(
            revenue=revenue,
            revenue_growth=growth,
            fcf_margin=margin,
            wacc=wacc,
            terminal_growth=terminal,
            net_debt=net_debt,
            shares_outstanding=shares,
            minority_interest=minority_interest,
            preferred_stock=preferred_stock,
        )

        # Only the facts the DCF actually consumes may move the evidence
        # confidence: averaging in balance-sheet rows the model never reads
        # would shift the base-case probability just because a balance sheet
        # happened to be ingested.
        confidence_facts = [
            fact for metric, fact in snapshot.facts.items() if metric in MODEL_INPUT_METRICS
        ]
        evidence_confidence = (
            sum(float(fact.confidence) for fact in confidence_facts) / len(confidence_facts)
            if confidence_facts
            else 0.0
        )
        scenarios = mechanical_dcf_scenarios(
            growth,
            margin,
            wacc,
            terminal,
            evidence_confidence,
        )
        scenario_results = {}
        for scenario in scenarios:
            result = run_dcf(
                DCFInputs(
                    revenue=revenue,
                    revenue_growth=float(scenario.assumptions["revenue_growth"]),
                    fcf_margin=float(scenario.assumptions["fcf_margin"]),
                    wacc=float(scenario.assumptions["wacc"]),
                    terminal_growth=float(scenario.assumptions["terminal_growth"]),
                    net_debt=net_debt,
                    shares_outstanding=shares,
                    minority_interest=minority_interest,
                    preferred_stock=preferred_stock,
                )
            )
            scenario_results[scenario.name] = {
                "definition": {
                    "name": scenario.name,
                    "probability": scenario.probability,
                    "drivers": scenario.drivers,
                    "description": scenario.description,
                    "assumptions": scenario.assumptions,
                },
                "value_per_share": result.value_per_share,
                "trace": result.trace,
            }

        # El esperado se pondera con los valores BRUTOS (un bear negativo
        # cuenta): excluirlo inflaría el esperado y rompería bear <= base.
        weighted = probability_weighted_value(
            [
                Scenario(name, data["definition"]["probability"], data["value_per_share"])
                for name, data in scenario_results.items()
            ]
        )

        # Convención d2656966: un valor por acción <= 0 no es publicable; el
        # escenario sale N/D con explicación, nunca como cifra negativa.
        scenario_notes: dict[str, str] = {}
        for scenario in scenarios:
            data = scenario_results[scenario.name]
            raw_value = data["value_per_share"]
            if raw_value is not None and raw_value > 0:
                continue
            note = _scenario_nd_note(
                scenario.name, raw_value, float(scenario.assumptions["fcf_margin"])
            )
            scenario_notes[scenario.name] = note
            data["value_per_share_raw"] = raw_value
            data["value_per_share"] = None
            data["value_note"] = note

        # The DCF runs in the filing's share basis (ordinary shares), so the
        # quote has to be converted into that basis before margin of safety is
        # compared against it.
        ratio = adr_ratio(company)
        comparable_price = current_price / ratio if (ratio and current_price) else current_price

        reverse = {}
        if comparable_price is not None and comparable_price > 0:
            # Same ordinary-share basis as the DCF value per share.
            reverse = solve_required_growth(
                ReverseDCFInputs(
                    market_price=comparable_price,
                    revenue=revenue,
                    fcf_margin=margin,
                    wacc=wacc,
                    terminal_growth=terminal,
                    net_debt=net_debt,
                    shares_outstanding=shares,
                    minority_interest=minority_interest,
                    preferred_stock=preferred_stock,
                )
            )
            # Base explicita: la cifra solo se entiende con el margen FCF y el
            # WACC con los que se resolvio (la vista del modelo usa el margen
            # normalizado y puede dar otra cifra con otra base).
            reverse = {**reverse, "fcf_margin": margin, "wacc": wacc}

        sensitivity = sensitivity_grid(
            base_inputs,
            growth_values=[growth - 0.04, growth, growth + 0.04],
            wacc_values=[wacc - 0.01, wacc, wacc + 0.01],
        )

        expected_raw = weighted["expected_value"]
        bear = scenario_results["bear"]["value_per_share"]
        base = scenario_results["base"]["value_per_share"]
        bull = scenario_results["bull"]["value_per_share"]
        if expected_raw > 0:
            expected: float | None = expected_raw
        else:
            # Mismo criterio que en los escenarios: un esperado <= 0 es N/D
            # explicado, no una cifra negativa (el bruto queda en la traza).
            expected = None
            scenario_notes["expected"] = (
                "El valor esperado (ponderado por probabilidad) sale "
                f"{_num_es(expected_raw)} con estos supuestos: N/D, no se publica "
                "una cifra negativa."
            )

        # Terminal value share guard: a DCF where >80% of the EV is the terminal
        # value is not a 5-year forecast, it is a perpetuity assumption.
        base_trace = scenario_results["base"]["trace"]
        pv_explicit = base_trace.get("pv_explicit_fcf")
        pv_terminal = base_trace.get("pv_terminal_value")
        terminal_share = None
        if isinstance(pv_explicit, (int, float)) and isinstance(pv_terminal, (int, float)):
            total = pv_explicit + pv_terminal
            if total > 0:
                terminal_share = pv_terminal / total

        clamp_notes: list[str] = []
        if margin_clamped:
            clamp_notes.append(f"fcf_margin {raw_margin:.4f} clamped to the {margin:.4f} ceiling")
        if growth != raw_growth:
            clamp_notes.append(f"revenue_growth {raw_growth:.4f} clamped to {growth:.4f}")
        if terminal_share is not None and terminal_share > 0.80:
            clamp_notes.append(
                f"terminal value is {terminal_share:.1%} of enterprise value; "
                "the 5-year forecast is not the driver of this valuation"
            )

        publication_blockers: list[str] = []
        if wacc_source != "calculated_metric":
            publication_blockers.append("traceable_wacc")
        if terminal_share is not None and terminal_share > 0.95:
            publication_blockers.append("forecast_is_not_the_driver")


        return apply_publication_blockers(
            {
            "ticker": company.ticker,
            "model_type": company.valuation_model,
            "status": "ok",
            "publishable": True,
            "current_price": current_price,
            "bear_value": bear,
            "base_value": base,
            "bull_value": bull,
            "expected_value": expected,
            "margin_of_safety": margin_of_safety(expected, comparable_price),
            "missing_inputs": [],
            "publication_blockers": publication_blockers,
            "adr_ratio": ratio,
            "value_per_share_basis": "ordinary_share",
            "listed_share_values": (
                {
                    "bear": bear * ratio if bear is not None else None,
                    "base": base * ratio if base is not None else None,
                    "bull": bull * ratio if bull is not None else None,
                    "expected": expected * ratio if expected is not None else None,
                }
                if ratio
                else None
            ),
            "scenario_notes": scenario_notes,
            "comparable_price_basis": "ordinary_share" if ratio else "listed_share",
            "reverse_dcf": reverse,
            "sensitivity": sensitivity,
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
                "growth_source": growth_source,
                "growth_clamped_from": raw_growth if growth != raw_growth else None,
                "fcf_margin_source": "financial_facts",
                "fcf_margin_normalization": margin_normalization,
                "fcf_margin_clamped_from": raw_margin if margin_clamped else None,
                "wacc_source": wacc_source,
                "terminal_source": terminal_source,
                "inferred_inputs_ignored": dropped_inferred,
                "wacc": wacc,
                "net_debt": net_debt,
                "minority_interest": minority_interest,
                "preferred_stock": preferred_stock,
                "equity_bridge": "EV - net_debt - minority_interest - preferred_stock",
                "adr_ratio": ratio,
                "comparable_price": comparable_price,
                "terminal_value_share": terminal_share,
                "clamp_notes": clamp_notes,
                "expected_value_raw": expected_raw,
                "scenario_notes": scenario_notes,
                "publication_blockers": publication_blockers,
                "scenario_style": "fact_anchored_sensitivity",
                "probability_method": "source_confidence_plus_company_financials",
                "evidence_confidence": evidence_confidence,
                "evidence_confidence_inputs": sorted(MODEL_INPUT_METRICS & set(snapshot.facts)),
                "fact_ids": snapshot.fact_ids(),
                "periods": snapshot.periods(),
                "snapshot": {
                    "as_of": snapshot.as_of_period,
                    "income_statement": snapshot.income_statement,
                    "balance_sheet": snapshot.balance_sheet,
                    "shares": snapshot.shares_period,
                    "warnings": snapshot.warnings,
                },
                "scenarios": scenario_results,
                "weighted": weighted["trace"],
                "reverse_dcf": reverse.get("trace") if reverse else None,
            },
            }
        )
