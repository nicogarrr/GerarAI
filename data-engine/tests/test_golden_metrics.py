"""Tests dorados de métricas y ratios (auditoría de fórmulas, fase 2).

Cada test llama a la función real con las entradas del ``numeric_check`` de la
auditoría (``GerarAI_formulas.pdf``) y compara con el valor calculado a mano.
La fuente de la definición estándar y la cuenta van en el docstring.

Fuera de este fichero, a propósito, porque sus convenciones se cambian en
otros PRs y aquí no se fija la antigua: ROE del screener en % (unidades),
ratios con denominador negativo, owner earnings y acciones por clase (EPS de
BRK/V).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import sessionmaker

from app.api.routes.portfolio import _scenario_returns
from app.api.routes.thesis import _pct_change
from app.core.database import SessionLocal, init_db
from app.models import CalculatedMetric, Company, Document, FinancialFact
from app.models.entities import Base
from app.services.driver_operating_model import DriverOperatingModel
from app.services.financial_ingestion_service import FinancialIngestionService
from app.services.metric_calculation_service import MetricCalculationService
from app.services.metric_semantics import MetricSemanticsRegistry
from app.services.number_format import format_compact_es
from app.services.number_parsing import parse_localized_number
from app.services.peer_comparison_service import PeerComparisonService
from app.services.screener_service import ScreenerService
from app.services.split_adjustment import cumulative_split_factor_after
from app.services.thesis_projection_service import ThesisProjectionService


def _fact(metric: str, value: str, year: int, fact_id: int = 1) -> FinancialFact:
    return FinancialFact(
        id=fact_id,
        company_id=1,
        metric=metric,
        value=Decimal(value),
        period=f"FY{year}",
        fiscal_year=year,
        fiscal_quarter="FY",
        confidence=Decimal("0.9"),
    )


# --- Funciones puras ---------------------------------------------------------


def test_variacion_frente_a_lo_esperado_con_base_negativa():
    """Variación = (real − esperado)/|esperado| (Investopedia, «Percentage
    Change»). A mano: esperado −10, real −5 → (−5 + 10)/10 = +0,5 (mejora;
    con /esperado saldría −0,5)."""
    _, variance = MetricSemanticsRegistry.classify("eps", Decimal("-10"), Decimal("-5"))
    assert variance == Decimal("0.5")
    assert MetricSemanticsRegistry.classify("eps", Decimal("0"), Decimal("1"))[1] is None


def test_factor_de_split_acumulado():
    """F = Π ratio_i de los splits posteriores al cierre; EPS_aj = EPS/F
    (CFA L1 FRA, reexpresión del EPS por splits; NIC 33 §64).
    A mano: splits 4:1 (2020-08-31) y 7:1 (2014-06-09). Cierre 2019-09-28 →
    F = 4; cierre 2013-12-31 → 4·7 = 28; EPS 12 → 3 tras el 4:1."""
    splits = [(date(2020, 8, 31), Decimal("4")), (date(2014, 6, 9), Decimal("7"))]
    assert cumulative_split_factor_after(splits, date(2019, 9, 28)) == Decimal("4")
    assert cumulative_split_factor_after(splits, date(2013, 12, 31)) == Decimal("28")
    assert Decimal("12") / cumulative_split_factor_after(splits, date(2019, 9, 28)) == Decimal("3")
    assert cumulative_split_factor_after(splits, None) == Decimal("1")


def test_parseo_de_numeros_con_parte_entera_cero():
    """Un separador seguido de 3 dígitos es de miles, salvo con parte entera
    0 (CLDR / Unicode TR35; RAE, Ortografía 2010 §4.5). Corregido en #2295.
    A mano: «0,250» → 0,25; «-0.125» → −0,125; «0,24» → 0,24; «1.250» → 1250."""
    assert parse_localized_number("0,250")[0] == Decimal("0.250")  # type: ignore[index]
    assert parse_localized_number("-0.125")[0] == Decimal("-0.125")  # type: ignore[index]
    assert parse_localized_number("0,24")[0] == Decimal("0.24")  # type: ignore[index]
    assert parse_localized_number("1.250")[0] == Decimal("1250")  # type: ignore[index]


def test_formato_compacto_es():
    """Cifra compacta es-ES con escala fija (ECMA-402, notation «compact»).
    A mano: 200.966.000.000 → 200,97 mil M; 24.000.000 → 24 M."""
    assert format_compact_es(200_966_000_000) == "200,97 mil M"
    assert format_compact_es(24_000_000) == "24 M"


def test_cagr_del_screener():
    """CAGR = (V_fin/V_ini)^(1/Δaños) − 1 (CFA L1 Quantitative Methods;
    Investopedia «CAGR»). A mano: 100 (FY2020) → 161,051 (FY2025):
    1,61051^(1/5) − 1 = 10 %. Base ≤ 0 → N/D."""
    serie = [_fact("revenue", "161.051", 2025, 2), _fact("revenue", "100", 2020, 1)]
    obs = ScreenerService._cagr(serie)
    assert obs is not None
    assert float(obs.value) == pytest.approx(0.10, abs=1e-12)
    assert ScreenerService._cagr([_fact("revenue", "161", 2025, 2), _fact("revenue", "0", 2020, 1)]) is None


def test_cagr_del_fcf_por_accion_del_screener():
    """CAGR de FCF/acción con numerador y denominador del mismo año.
    A mano: FCF 1.000/100 acc. (FY2020) = 10 y 1.932,612/120 acc. (FY2025) =
    16,1051 → 10 %."""
    numeradores = [_fact("free_cash_flow", "1932.612", 2025, 4), _fact("free_cash_flow", "1000", 2020, 3)]
    denominadores = [_fact("shares_diluted", "120", 2025, 6), _fact("shares_diluted", "100", 2020, 5)]
    obs = ScreenerService.__new__(ScreenerService)._ratio_cagr(numeradores, denominadores)
    assert obs is not None
    assert float(obs.value) == pytest.approx(0.10, abs=1e-9)


def test_cagr_de_ingresos_de_la_tesis():
    """Mismo CAGR en la proyección de la tesis; extremos ≤ 0 → N/D.
    A mano: 100 → 161,051 en 5 años → 10 %."""
    rate = ThesisProjectionService._revenue_cagr({2020: _fact("revenue", "100", 2020), 2025: _fact("revenue", "161.051", 2025)})
    assert rate.value == pytest.approx(0.10)
    assert ThesisProjectionService._revenue_cagr({2020: _fact("revenue", "-5", 2020), 2025: _fact("revenue", "10", 2025)}).value is None


def test_cagr_del_modelo_operativo_por_drivers():
    """CAGR del modelo por drivers, solo FY. A mano: 100 → 161,051 en 5 años
    → 10 %; base 0 → N/D."""
    assert DriverOperatingModel._cagr([(2020, 100.0, 1, "USD"), (2025, 161.051, 2, "USD")]) == pytest.approx(0.10)
    assert DriverOperatingModel._cagr([(2020, 0.0, 1, "USD"), (2025, 161.051, 2, "USD")]) is None


def test_rentabilidad_de_escenario_de_cartera():
    """CAGR implícito (VI/P)^(1/h) − 1 y retorno total VI/P − 1.
    A mano: VI 161,051, P 100, h 5 → 10 % anual y 61,051 % total."""
    out = _scenario_returns(161.051, 100.0, 5)
    assert out is not None
    cagr, total = out
    assert cagr == pytest.approx(0.10)
    assert total == pytest.approx(0.61051)
    assert _scenario_returns(161.051, 0.0, 5) is None


def test_variacion_porcentual_de_la_tesis_con_base_negativa():
    """(nuevo − base)/|base|·100 (Investopedia «Percentage Change»; Damodaran,
    crecimiento con beneficios negativos, cap. 11). A mano: −10 → −5 = +50 %;
    base 0 → N/D."""
    assert _pct_change(-10, -5) == pytest.approx(50.0)
    assert _pct_change(0, 5) is None


def test_mediana_de_pares():
    """Mediana de los múltiplos de pares (Damodaran, *Investment Valuation*,
    caps. 17-18). A mano: [1, 3, 2, 10] → ordenado [1, 2, 3, 10] → 2,5."""
    service = PeerComparisonService.__new__(PeerComparisonService)
    assert service._median([Decimal(v) for v in (1, 3, 2, 10)]) == Decimal("2.5")
    assert service._median([Decimal(v) for v in (1, 3, 2)]) == Decimal("2")
    assert service._median([]) is None


# --- Con base de datos -----------------------------------------------------

TICKER = "TGOLDMET"


def _limpiar() -> None:
    init_db()
    db = SessionLocal()
    try:
        for company in db.scalars(select(Company).where(Company.ticker == TICKER)).all():
            db.execute(delete(CalculatedMetric).where(CalculatedMetric.company_id == company.id))
            db.execute(delete(FinancialFact).where(FinancialFact.company_id == company.id))
            db.delete(company)
        db.commit()
    finally:
        db.close()


@pytest.fixture()
def empresa_bd():
    _limpiar()
    db = SessionLocal()
    company = Company(
        ticker=TICKER,
        name="Golden Metrics Co",
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

    def add(metric: str, value: str, year: int = 2025) -> None:
        db.add(
            FinancialFact(
                company_id=company.id,
                metric=metric,
                value=Decimal(value),
                unit="USD",
                period=f"FY{year}",
                fiscal_year=year,
                fiscal_quarter="FY",
                source_type="test_metric",
                is_reported=True,
                confidence=Decimal("0.90"),
            )
        )

    try:
        yield db, company, add
    finally:
        db.close()
        _limpiar()


def test_margen_neto(empresa_bd):
    """Margen = X/ingresos del mismo periodo (Investopedia, «Profit Margin»).
    A mano: beneficio neto 20, ingresos 200 → 0,10."""
    db, company, add = empresa_bd
    add("net_income", "20")
    add("revenue", "200")
    db.commit()
    result = MetricCalculationService().calculate(db, company, "net_margin", persist=False)
    assert result.status == "ok"
    assert result.value == Decimal("0.10000000")


def test_roic_con_capital_invertido_medio(empresa_bd):
    """ROIC = EBIT·(1 − t)/capital invertido medio, capital = deuda +
    patrimonio − caja (Damodaran, «Return on Capital (ROC), ROIC and ROE»,
    2007). A mano: EBIT 100, t 25 % → NOPAT 75; capital 300 (FY2024: 100 +
    250 − 50) y 500 (FY2025: 200 + 350 − 50) → medio 400 → 0,1875."""
    db, company, add = empresa_bd
    add("operating_income", "100")
    add("effective_tax_rate", "0.25")
    for year, debt, equity in ((2024, "100", "250"), (2025, "200", "350")):
        add("total_debt", debt, year)
        add("total_equity", equity, year)
        add("cash_and_equivalents", "50", year)
    db.commit()
    result = MetricCalculationService().calculate(db, company, "roic", persist=False)
    assert result.status == "ok"
    assert result.value == Decimal("0.18750000")


def test_roic_sin_tipo_impositivo_usa_el_21(empresa_bd):
    """Sin tipo efectivo ni impuesto/BAI, el ROIC usa un 21 % fijo (tipo
    federal de EE. UU.; convención discutible para emisores no
    estadounidenses, cf. tablas de tipos marginales de Damodaran).
    A mano: EBIT 100 → NOPAT 79; capital medio 400 → 0,1975."""
    db, company, add = empresa_bd
    add("operating_income", "100")
    for year, debt, equity in ((2024, "100", "250"), (2025, "200", "350")):
        add("total_debt", debt, year)
        add("total_equity", equity, year)
        add("cash_and_equivalents", "50", year)
    db.commit()
    result = MetricCalculationService().calculate(db, company, "roic", persist=False)
    assert result.status == "ok"
    assert result.value == Decimal("0.19750000")


def test_margen_neto_medio_a_5_anos(empresa_bd):
    """Media simple de los ratios anuales (mínimo 3 años; CFA).
    A mano: márgenes 10 %, 20 % y 30 % (20/200, 40/200, 60/200) → 20 %."""
    db, company, add = empresa_bd
    for year, income in ((2023, "20"), (2024, "40"), (2025, "60")):
        add("net_income", income, year)
        add("revenue", "200", year)
    db.commit()
    result = MetricCalculationService().calculate(db, company, "net_margin_5y", persist=False)
    assert result.status == "ok"
    assert result.value == Decimal("0.20000000")


@pytest.fixture()
def memoria():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _derivar(db, *, sector: str, industry: str, facts: list[tuple[str, str, int]]) -> dict[tuple[str, int], Decimal]:
    company = Company(
        ticker="TGOLDSEC",
        name="Golden SEC Co",
        exchange="NYSE",
        currency="USD",
        sector=sector,
        industry=industry,
        company_type="research_candidate",
        valuation_model="unassigned",
        special_sources=[],
        special_risks=[],
        factor_tags=[],
    )
    db.add(company)
    db.flush()
    document = Document(company_id=company.id, title="10-K", source_type="SEC", metadata_={})
    db.add(document)
    db.flush()
    for metric, value, year in facts:
        db.add(
            FinancialFact(
                company_id=company.id,
                metric=metric,
                value=Decimal(value),
                unit="USD",
                period=f"{year}-12-31:FY",
                fiscal_year=year,
                fiscal_quarter="FY",
                source_type="SEC",
                is_reported=True,
                confidence=Decimal("0.95"),
            )
        )
    db.flush()
    FinancialIngestionService()._derive_sec_metrics(db, company, document)
    db.flush()
    rows = db.scalars(
        select(FinancialFact).where(FinancialFact.company_id == company.id, FinancialFact.is_reported.is_(False))
    ).all()
    return {(row.metric, int(row.fiscal_year)): Decimal(row.value) for row in rows if row.fiscal_year is not None}


def test_derivadas_sec_fcf_deuda_neta_y_crecimiento(memoria):
    """FCF = OCF + capex (capex guardado negativo); deuda neta = deuda − caja;
    crecimiento = ingresos_t/ingresos_{t−1} − 1 (Investopedia, «Free Cash
    Flow», «Net Debt», «Year over Year»; CFA).
    A mano: OCF 500, capex −120 → FCF 380; deuda 800, caja 300 → 500;
    ingresos 100 → 120 → +20 %."""
    derived = _derivar(
        memoria,
        sector="Technology",
        industry="Software",
        facts=[
            ("operating_cash_flow", "500", 2025),
            ("capital_expenditure", "-120", 2025),
            ("revenue", "100", 2024),
            ("revenue", "120", 2025),
            ("total_debt", "800", 2025),
            ("cash_and_equivalents", "300", 2025),
        ],
    )
    assert derived[("free_cash_flow", 2025)] == Decimal("380")
    assert derived[("net_debt", 2025)] == Decimal("500")
    assert derived[("revenue_growth", 2025)] == pytest.approx(Decimal("0.2"))


def test_roe_aseguradora_sobre_patrimonio_medio(memoria):
    """ROE = beneficio neto/patrimonio medio (CFA, análisis DuPont).
    A mano: beneficio 100, patrimonio 900 (FY2024) y 1.100 (FY2025) →
    100/1.000 = 0,10; crecimiento del valor contable 1.100/900 − 1 = 22,2 %."""
    derived = _derivar(
        memoria,
        sector="Financials",
        industry="Insurance - Property & Casualty",
        facts=[
            ("net_income", "100", 2025),
            ("total_equity", "900", 2024),
            ("total_equity", "1100", 2025),
        ],
    )
    assert derived[("roe", 2025)] == Decimal("0.1")
    assert derived[("book_value_growth", 2025)] == pytest.approx(Decimal("1100") / Decimal("900") - 1)
