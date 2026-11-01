"""Tests dorados de las fórmulas de valoración (auditoría de fórmulas, fase 2).

Cada test llama a la función real con las entradas del ``numeric_check`` de la
auditoría (``GerarAI_formulas.pdf``) y compara con el valor calculado a mano.
En el docstring de cada test van la fuente de la definición estándar y la
cuenta a mano, para que cualquiera pueda rehacerla en papel.

Fuera de este fichero, a propósito:
- margen de seguridad (V/P − 1 frente a (V − P)/V), puente EV→equity con
  minoritarios/preferentes y colchón de caja del funding gap: sus convenciones
  se están cambiando en otro PR y aquí no se fija la antigua;
- conciliación de dividendos del activo regulado (bug abierto, se arregla en
  otro PR).
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

import pytest

from app.services.inferred_input_service import (
    MIN_WACC_TERMINAL_SPREAD,
    pick_rate_pair,
)
from app.services.long_term_model_service import LongTermModelService
from app.services.metric_calculation_service import MetricCalculationService
from app.valuation.commodity_sensitivity import commodity_price_sensitivity
from app.valuation.dcf_fcff import DCFInputs, run_dcf
from app.valuation.dilution_model import DilutionInput, run_dilution
from app.valuation.dividend_equity import (
    DdmInputs,
    fcfe_bridge,
    gordon_value,
    run_ddm,
)
from app.valuation.engines.sector_specific import _pb_sensitivity_rows
from app.valuation.engines.sotp_engine import sotp_discount_sensitivity
from app.valuation.reverse_dcf import ReverseDCFInputs, solve_required_growth
from app.valuation.scenario_model import Scenario, probability_weighted_value
from app.valuation.sensitivity import sensitivity_grid
from app.valuation.sotp import run_sotp

# Caso de la auditoría para el DCF FCFF (ver dcf_fcff_core).
CASO_DCF = DCFInputs(
    revenue=100.0,
    revenue_growth=0.10,
    fcf_margin=0.10,
    wacc=0.10,
    terminal_growth=0.02,
    net_debt=20.0,
    shares_outstanding=10.0,
    years=2,
)


def test_dcf_fcff_dos_anos_coincide_con_el_calculo_a_mano():
    """DCF FCFF con valor terminal de Gordon, convención de fin de año.

    Fuente: Damodaran, *Investment Valuation* (3.ª ed.), cap. 12; CFA L2, FCFF.
    A mano: ingresos 110 y 121 → FCF 11 y 12,1; VP = 11/1,1 + 12,1/1,21 =
    10 + 10 = 20. VT = 12,1·1,02/(0,10 − 0,02) = 154,275; VP(VT) =
    154,275/1,21 = 127,5. EV = 147,5; equity = 147,5 − 20 = 127,5;
    por acción 12,75.
    """
    result = run_dcf(CASO_DCF)
    assert result.forecast[0]["fcf"] == pytest.approx(11.0)
    assert result.forecast[1]["fcf"] == pytest.approx(12.1)
    assert result.trace["pv_explicit_fcf"] == pytest.approx(20.0)
    assert result.trace["terminal_value"] == pytest.approx(154.275)
    assert result.trace["pv_terminal_value"] == pytest.approx(127.5)
    assert result.enterprise_value == pytest.approx(147.5)
    assert result.equity_value == pytest.approx(127.5)
    assert result.value_per_share == pytest.approx(12.75)


def test_reverse_dcf_recupera_el_crecimiento_del_caso():
    """Reverse DCF (Mauboussin & Rappaport, *Expectations Investing*, 2001).

    A mano: con los mismos datos del DCF, un precio de 12,75 implica
    exactamente el 10 % de crecimiento de ingresos que lo generó.
    """
    out = solve_required_growth(
        ReverseDCFInputs(
            market_price=12.75,
            revenue=100.0,
            fcf_margin=0.10,
            wacc=0.10,
            terminal_growth=0.02,
            net_debt=20.0,
            shares_outstanding=10.0,
            years=2,
        )
    )
    assert out["out_of_bounds"] is False
    assert out["required_revenue_growth"] == pytest.approx(0.10, abs=1e-9)


def test_pick_rate_pair_descarta_el_inferido_que_rompe_el_spread():
    """Guardia WACC > g (Damodaran, *Investment Valuation*, cap. 12).

    El valor terminal de Gordon exige r > g; el código pide un spread mínimo
    de 2 pp. A mano: WACC 9 % inferido y g 8 % inferido → spread 1 pp < 2 pp:
    se descarta primero g (vuelve al 3 % por defecto) y el par queda 9 %/3 %.
    """
    assert pytest.approx(0.02) == MIN_WACC_TERMINAL_SPREAD
    wacc, terminal, dropped = pick_rate_pair(
        wacc=0.09,
        wacc_inferred=True,
        terminal=0.08,
        terminal_inferred=True,
        default_wacc_value=0.10,
        default_terminal_value=0.03,
    )
    assert (wacc, terminal, dropped) == (pytest.approx(0.09), pytest.approx(0.03), ["terminal_growth"])
    # Un par válido no se toca.
    assert pick_rate_pair(
        wacc=0.09,
        wacc_inferred=True,
        terminal=0.03,
        terminal_inferred=True,
        default_wacc_value=0.10,
        default_terminal_value=0.03,
    ) == (0.09, 0.03, [])


def test_normalizacion_de_tasas_en_puntos_porcentuales():
    """Convención de unidades: FRED DGS10 se publica en % (4,5 = 4,5 %).

    A mano: 4,5 → 0,045; 0,045 se queda en 0,045. (El caso ambiguo de un
    tipo menor del 1 % escrito en puntos, p. ej. 0,9, no se fija aquí.)
    """
    service = MetricCalculationService()
    assert service._normalize_rate(Decimal("4.5"))[0] == Decimal("0.045")
    assert service._normalize_rate(Decimal("0.045"))[0] == Decimal("0.045")


def test_gordon_ddm_una_etapa():
    """Gordon: P = D0·(1 + g)/(ke − g). Fuente: CFA L2 Equity, Discounted
    Dividend Valuation; Damodaran ddm.xls.

    A mano: D0 2, ke 9 %, g 4 % → 2·1,04/0,05 = 41,6.
    """
    assert gordon_value(2.0, 0.09, 0.04) == pytest.approx(41.6)
    single = run_ddm(
        DdmInputs(
            dividend_per_share=2.0,
            cost_of_equity=0.09,
            stage1_growth=0.04,
            stage1_years=0,
            stage2_growth=0.04,
            shares_diluted=1.0,
        )
    )
    assert single.value_per_share == pytest.approx(41.6)


def test_ddm_dos_etapas():
    """DDM de dos etapas (CFA L2 Equity, two-stage DDM).

    A mano: D0 1, ke 10 %, g1 10 % durante 2 años, g2 3 %. D1 = 1,1 (VP 1),
    D2 = 1,21 (VP 1); VT = 1,21·1,03/0,07 = 17,8043 → VP 14,7143;
    total 16,7143 (= 16,714285…).
    """
    out = run_ddm(
        DdmInputs(
            dividend_per_share=1.0,
            cost_of_equity=0.10,
            stage1_growth=0.10,
            stage1_years=2,
            stage2_growth=0.03,
            shares_diluted=10.0,
        )
    )
    assert out.forecast[0]["pv_dividend"] == pytest.approx(1.0)
    assert out.forecast[1]["pv_dividend"] == pytest.approx(1.0)
    assert out.trace["terminal_value"] == pytest.approx(1.21 * 1.03 / 0.07)
    assert out.value_per_share == pytest.approx(16.714285714285715)
    assert out.equity_value == pytest.approx(167.14285714285714)


def test_fcfe_puente_corregido():
    """FCFE = NI − (capex − D&A) + Δdeuda − ΔWC (CFA L2, Free Cash Flow
    Valuation; Damodaran, *Investment Valuation*, cap. 14). Corregido en #2300.

    A mano: NI 100, capex 50, D&A 20, Δdeuda 0, ΔWC 0 → 100 − 30 = 70
    (el ratio de retención 0,6 ya no multiplica la reinversión).
    """
    out = fcfe_bridge(
        net_income=100.0,
        capex=50.0,
        depreciation_amortization=20.0,
        retention_ratio=0.6,
        delta_total_debt=0.0,
        delta_working_capital=0.0,
    )
    assert out["fcfe"] == pytest.approx(70.0)
    con_deuda = fcfe_bridge(
        net_income=100.0,
        capex=50.0,
        depreciation_amortization=20.0,
        retention_ratio=0.6,
        delta_total_debt=15.0,
        delta_working_capital=5.0,
    )
    # 100 − 30 + 15 − 5 = 80
    assert con_deuda["fcfe"] == pytest.approx(80.0)


def test_dilucion_con_credito_por_el_capital_captado():
    """Emisión de acciones (CFA L2 Equity; Damodaran, *Dilution*).

    A mano: 100 acciones, V = 20/acc., capta 1.000 a 10 → 100 acciones nuevas;
    (2.000 + 1.000)/200 = 15 por acción; dilución 100/200 = 50 %.
    """
    out = run_dilution(
        DilutionInput(
            current_shares=100.0,
            new_capital_needed=1000.0,
            issuance_price=10.0,
            current_value_per_share=20.0,
        )
    )
    assert out["new_shares"] == pytest.approx(100.0)
    assert out["dilution_pct"] == pytest.approx(0.5)
    assert out["diluted_value_per_share"] == pytest.approx(15.0)


def test_sensibilidad_a_materias_primas():
    """Valor = (EBITDA·(1 − t)·múltiplo − deuda neta)/acciones (convención del
    código; Damodaran, FCFF). Nota de la auditoría: grava el EBITDA entero,
    sin escudo fiscal de la amortización.

    A mano: volumen 10, coste 40, precio 60, t 25 %, múltiplo 8, deuda neta
    50, 10 acciones → EBITDA 200; 150·8 = 1.200; − 50 = 1.150; 115/acción.
    Precio por debajo del coste → EBITDA 0 (no negativo): (0 − 50)/10 = −5.
    """
    out = commodity_price_sensitivity(
        base_volume=10.0,
        cash_cost_per_unit=40.0,
        commodity_prices=[60.0, 30.0],
        tax_rate=0.25,
        multiple=8.0,
        net_debt=50.0,
        shares_outstanding=10.0,
    )
    assert out["rows"][0]["after_tax_cash_flow"] == pytest.approx(150.0)
    assert out["rows"][0]["value_per_share"] == pytest.approx(115.0)
    assert out["rows"][1]["value_per_share"] == pytest.approx(-5.0)


def test_sotp_holding_con_descuento():
    """NAV/acc·(1 − descuento) (Damodaran, *The Value of Cash and Cross
    Holdings*; CFA L2).

    A mano: NAV/acc 50, descuento 20 % → 40; ±5 pp → 42,5 y 37,5.
    """
    rows = {r["scenario"]: r for r in sotp_discount_sensitivity(nav_per_share=50.0, base_discount=0.20)["rows"]}
    assert rows["base_discount"]["value_per_share"] == pytest.approx(40.0)
    assert rows["narrow_discount"]["value_per_share"] == pytest.approx(42.5)
    assert rows["wide_discount"]["value_per_share"] == pytest.approx(37.5)


def test_pb_justificado_banco():
    """P/B justificado = (ROE − g)/(ke − g), acotado a [0,25; 3] (CFA L2 Equity,
    Market-Based Valuation; Damodaran, *Valuing Financial Service Firms*).

    A mano: TBV/acción 40, ROE 12 %, g 4 %, ke 10 % → 0,08/0,06 = 1,3333 →
    53,33 por acción.
    """
    rows = {
        r["scenario"]: r
        for r in _pb_sensitivity_rows(book_per_share=40.0, roe=0.12, cost_of_equity=0.10, growth=0.04)["rows"]
    }
    assert rows["base_coe"]["justified_pb"] == pytest.approx(4 / 3)
    assert rows["base_coe"]["value_per_share"] == pytest.approx(160 / 3)


def test_pb_aseguradora_con_factor_de_suscripcion():
    """Aseguradora: BVPS·P/B justificado·clamp(1 + (1 − ratio combinado)·2,
    0,75, 1,25) (CFA L2, Market-Based Valuation; factor propio del código).

    A mano: BVPS 50, ROE 12 %, g 4 %, ke 9 %, ratio combinado 0,95 → P/B
    0,08/0,05 = 1,6; factor 1 + 0,05·2 = 1,10 → 50·1,6·1,1 = 88.
    """
    factor = max(0.75, min(1.25, 1 + (1 - 0.95) * 2))
    assert factor == pytest.approx(1.10)
    rows = {
        r["scenario"]: r
        for r in _pb_sensitivity_rows(
            book_per_share=50.0, roe=0.12, cost_of_equity=0.09, growth=0.04, underwriting_factor=factor
        )["rows"]
    }
    assert rows["base_coe"]["justified_pb"] == pytest.approx(1.6)
    assert rows["base_coe"]["value_per_share"] == pytest.approx(88.0)


def test_escenarios_ponderados_por_probabilidad():
    """E[V] = Σ (p_i/Σp)·V_i (CFA L2, scenario analysis).

    A mano: pesos 1/2/1 y valores 50/100/200 → (50 + 200 + 200)/4 = 112,5.
    """
    out = probability_weighted_value(
        [Scenario("bear", 1.0, 50.0), Scenario("base", 2.0, 100.0), Scenario("bull", 1.0, 200.0)]
    )
    assert out["expected_value"] == pytest.approx(112.5)


def test_suma_de_partes_simple():
    """EV = Σ métrica_i·múltiplo_i; equity = EV − deuda neta (CFA L2;
    Damodaran, *The Dark Side of Valuation*).

    A mano: 100·8 + 50·12 = 1.400; − 300 = 1.100; /10 = 110.
    """
    out = run_sotp(
        [{"name": "A", "metric": 100, "multiple": 8}, {"name": "B", "metric": 50, "multiple": 12}],
        net_debt=300.0,
        shares_outstanding=10.0,
    )
    assert out["enterprise_value"] == pytest.approx(1400.0)
    assert out["equity_value"] == pytest.approx(1100.0)
    assert out["value_per_share"] == pytest.approx(110.0)


def test_rejilla_de_sensibilidad_recalcula_el_dcf_y_anula_wacc_menor_que_g():
    """Rejilla crecimiento × WACC (práctica estándar, tablas de Damodaran).

    La celda (g 10 %, WACC 10 %) es el caso del DCF: 12,75. La celda con
    WACC 2 % = g terminal 2 % no es valorable → None.
    """
    grid = sensitivity_grid(CASO_DCF, [0.10], [0.10, 0.02])
    cells = grid["rows"][0]["values"]
    assert cells[0]["value_per_share"] == pytest.approx(12.75)
    assert cells[1]["value_per_share"] is None
    assert cells[1]["error"] == "cell_out_of_range"



def test_cagr_y_dispersion_del_modelo_largo_plazo():
    """CAGR = (V_fin/V_ini)^(1/años) − 1 (CFA L1 Quantitative Methods).

    A mano: 100 → 121 en 2 años → 1,21^0,5 − 1 = 10 %. Extremo negativo o
    base cero → N/D. Dispersión: desviación típica poblacional de
    [0,1; 0,2; 0,3] = √(0,02/3) = 0,08165.
    """
    cagr = LongTermModelService._cagr
    assert cagr([{"year": 2023, "value": 100.0}, {"year": 2025, "value": 121.0}]) == pytest.approx(0.10)
    assert cagr([{"year": 2023, "value": 0.0}, {"year": 2025, "value": 121.0}]) is None
    assert cagr([{"year": 2023, "value": -100.0}, {"year": 2025, "value": 121.0}]) is None
    assert cagr([{"year": 2025, "value": 100.0}, {"year": 2025, "value": 121.0}]) is None
    assert LongTermModelService._spread([0.1, 0.2, 0.3]) == pytest.approx((0.02 / 3) ** 0.5)


def _fact_anual(metric: str, value: float, year: int):
    from app.models import FinancialFact

    return FinancialFact(
        metric=metric,
        value=Decimal(str(value)),
        period=f"FY{year}",
        fiscal_year=year,
        fiscal_quarter="FY",
    )


def test_dcf_del_modelo_largo_plazo_con_forecast_explicito():
    """DCF FCFF del modelo a largo plazo (Damodaran, *Investment Valuation*,
    cap. 12-15; CFA L2 Free Cash Flow Valuation).

    A mano: FCF 10 y 11 (N = 2), WACC 10 %, g 3 %, deuda neta 20, 10 acciones.
    VP explícito = 10/1,1 + 11/1,21 = 9,0909 + 9,0909 = 18,1818.
    VT = 11·1,03/0,07 = 161,857 → VP = 161,857/1,21 = 133,766.
    EV = 151,948; equity = 131,948; 13,1948 por acción.
    """
    from app.services.long_term_model_service import Assumption

    def assumption(value: float) -> Assumption:
        return Assumption(value, "decimal", "test", "golden", [], 1.0)

    payload = LongTermModelService()._scenario_payload(
        name="base",
        spec={
            "probability": 1.0,
            "growth": 0.10,
            "fcf_margin": 0.10,
            "wacc": 0.10,
            "terminal_growth": 0.03,
            "drivers": {},
        },
        forecast=[
            {"year": 2026, "revenue": 100.0, "fcf_margin": 0.10, "free_cash_flow": 10.0, "shares_diluted": 10.0, "evidence": {"revenue": {"source_fact_ids": []}}},
            {"year": 2027, "revenue": 110.0, "fcf_margin": 0.10, "free_cash_flow": 11.0, "shares_diluted": 10.0, "evidence": {"revenue": {"source_fact_ids": []}}},
        ],
        assumptions={key: assumption(0.1) for key in ("revenue_growth", "fcf_margin", "wacc", "terminal_growth")},
        fact_cache=defaultdict(
            list,
            {
                "revenue": [_fact_anual("revenue", 100.0, 2025)],
                "net_debt": [_fact_anual("net_debt", 20.0, 2025)],
                "shares_diluted": [_fact_anual("shares_diluted", 10.0, 2025)],
            },
        ),
        latest_year=2025,
    )
    dcf = payload["valuation"]
    assert dcf is not None
    assert dcf["trace"]["pv_explicit_fcf"] == pytest.approx(10 / 1.1 + 11 / 1.21)
    assert dcf["trace"]["terminal_value"] == pytest.approx(11 * 1.03 / 0.07)
    assert dcf["enterprise_value"] == pytest.approx(151.948, abs=1e-3)
    assert dcf["equity_value"] == pytest.approx(131.948, abs=1e-3)
    assert dcf["value_per_share"] == pytest.approx(13.1948, abs=1e-4)


WACC_TICKER = "TGOLDWACC"


def _limpiar_wacc() -> None:
    from sqlalchemy import delete, select

    from app.core.database import SessionLocal, init_db
    from app.models import CalculatedMetric, Company, FinancialFact

    init_db()
    db = SessionLocal()
    try:
        for company in db.scalars(select(Company).where(Company.ticker == WACC_TICKER)).all():
            db.execute(delete(CalculatedMetric).where(CalculatedMetric.company_id == company.id))
            db.execute(delete(FinancialFact).where(FinancialFact.company_id == company.id))
            db.delete(company)
        db.commit()
    finally:
        db.close()


def test_wacc_estandar_capm():
    """WACC = E/(E+D)·ke + D/(E+D)·kd·(1 − t), ke = rf + β·ERP + CRP
    (Damodaran, *Applied Corporate Finance*, cap. 4; CFA L1 Cost of Capital).

    A mano: rf 4 %, β 1,2, ERP 5 %, CRP 0 → ke = 10 %. E 800, D 200,
    kd = intereses 12/deuda 200 = 6 %, t 25 % → WACC = 0,8·10 % +
    0,2·6 %·0,75 = 8 % + 0,9 % = 8,90 %.
    """
    from app.core.database import SessionLocal
    from app.models import Company, FinancialFact

    _limpiar_wacc()
    db = SessionLocal()
    try:
        company = Company(
            ticker=WACC_TICKER,
            name="Golden WACC Co",
            exchange="TEST",
            currency="USD",
            sector="Software",
            industry="Application Software",
            company_type="standard",
            valuation_model="standard_dcf",
            special_sources=[],
            special_risks=[],
            factor_tags=[],
        )
        db.add(company)
        db.flush()

        def add(metric: str, value: str, period: str, quarter: str | None, source: str = "test_metric") -> None:
            db.add(
                FinancialFact(
                    company_id=company.id,
                    metric=metric,
                    value=Decimal(value),
                    unit="USD",
                    period=period,
                    fiscal_year=2025,
                    fiscal_quarter=quarter,
                    source_type=source,
                    is_reported=True,
                    confidence=Decimal("0.90"),
                )
            )

        add("risk_free_rate", "0.04", "2025-12-31", None)
        add("beta", "1.2", "2025-12-31", None)
        add("equity_risk_premium", "0.05", "2025-12-31", None)
        add("country_risk_premium", "0", "2025-12-31", None)
        add("market_cap", "800", "2025-12-31", None, source="yfinance")
        add("interest_expense", "12", "FY2025", "FY")
        add("total_debt", "200", "FY2025", "FY", source="SEC")
        add("effective_tax_rate", "0.25", "FY2025", "FY")
        db.commit()

        result = MetricCalculationService().calculate(db, company, "wacc", persist=False)
        assert result.status == "ok"
        assert result.value == Decimal("0.08900000")
        assert result.calculation_trace["cost_of_debt"] == "0.06"
    finally:
        db.close()
        _limpiar_wacc()
