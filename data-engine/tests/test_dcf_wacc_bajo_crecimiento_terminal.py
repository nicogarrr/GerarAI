"""Un DCF con WACC <= crecimiento terminal no tumba la valoración entera.

CHTR (prod, 3 y 4-nov-2026): una cablera muy apalancada sale con un WACC
calculado (deuda barata, mucho peso de deuda) igual o por debajo del
crecimiento terminal. ``run_path_dcf`` / ``run_dcf`` lanzan ``ValueError``
(«wacc must be greater than terminal_growth») porque la fórmula de Gordon
no está definida; el error salía del motor sin capturar y la generación de
la tesis entera fallaba.

Regla que fija este test, para cualquier empresa: es una condición de los
DATOS, no un fallo de programación. El motor DCF se declara no válido con
un motivo claro (``wacc_above_terminal_growth``) y la valoración sigue su
camino (respaldo sectorial / múltiplos); no se recorta el WACC ni la g en
silencio (eso sería cambiar el método). Las funciones puras de
``dcf_fcff`` siguen lanzando ``ValueError`` (contrato de test_dcf_fcff.py).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Company, FinancialFact, MarketPrice
from app.models.entities import Base
from app.valuation.engines import standard_dcf
from app.valuation.engines.standard_dcf import StandardDCFEngine


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _company(db: Session) -> Company:
    row = Company(
        ticker="WACCLOW",
        name="Cablera apalancada (sintética)",
        exchange="TEST",
        currency="USD",
        sector="Communication Services",
        industry="Telecom Services",
        company_type="standard",
        valuation_model="standard_dcf",
        special_sources=[],
        special_risks=[],
        factor_tags=[],
    )
    db.add(row)
    db.flush()
    return row


def _facts(db: Session, company: Company, *, growth: float) -> None:
    for year in (2023, 2024, 2025):
        for metric, value in (
            ("fcf_margin", 0.08),
            ("revenue", 55_000_000_000),
            ("net_debt", 95_000_000_000),
            ("revenue_growth", growth),
            ("shares_diluted", 150_000_000),
        ):
            db.add(
                FinancialFact(
                    company_id=company.id,
                    metric=metric,
                    value=Decimal(str(value)),
                    unit="decimal" if abs(float(value)) < 1 else "USD",
                    period=f"{year}-12-31:FY",
                    fiscal_year=year,
                    fiscal_quarter="FY",
                    source_type="wacc_g_test",
                    is_reported=True,
                    confidence=Decimal("0.90"),
                )
            )
    db.add(
        MarketPrice(
            company_id=company.id,
            date=date(2026, 10, 30),
            close=Decimal("230.00"),
            adj_close=Decimal("230.00"),
            source="wacc_g_test",
        )
    )
    db.commit()


def _rates(wacc: float, terminal: float):
    def fake(_db, _company, *, as_of=None):
        return wacc, "calculated_metric", terminal, "tag_default", []

    return fake


@pytest.mark.parametrize("growth", [0.03, 0.15], ids=["dcf_plano", "dcf_multietapa"])
@pytest.mark.parametrize("wacc", [0.025, 0.03], ids=["wacc_menor_que_g", "wacc_igual_a_g"])
def test_motor_dcf_se_declara_no_valido_en_vez_de_lanzar(db, monkeypatch, growth, wacc):
    company = _company(db)
    _facts(db, company, growth=growth)
    monkeypatch.setattr(standard_dcf, "resolve_rates", _rates(wacc, 0.03))

    engine = StandardDCFEngine()
    result = engine.value(engine.build_context(db, company, 230.0))

    assert result["status"] == "insufficient_data"
    assert "wacc_above_terminal_growth" in result["missing_inputs"]
    reason = str(result.get("reason") or result.get("trace", {}).get("reason") or result)
    assert "crecimiento terminal" in reason
    # Nada se publica como valor: ni base ni bajista/alcista inventados.
    assert result.get("base_value") is None


def test_spread_positivo_sigue_valorando(db, monkeypatch):
    """Control: con WACC > g el motor valora como siempre (sin la guarda)."""
    company = _company(db)
    _facts(db, company, growth=0.03)
    monkeypatch.setattr(standard_dcf, "resolve_rates", _rates(0.08, 0.03))

    engine = StandardDCFEngine()
    result = engine.value(engine.build_context(db, company, 230.0))

    assert result["status"] != "insufficient_data"
    assert "wacc_above_terminal_growth" not in (result.get("missing_inputs") or [])


def test_valuation_service_no_lanza_y_sigue_por_otros_caminos(db, monkeypatch):
    """Nivel servicio (el que llama la tesis): ni excepción ni tesis caída."""
    from app.services.valuation_service import ValuationService

    company = _company(db)
    _facts(db, company, growth=0.15)
    monkeypatch.setattr(standard_dcf, "resolve_rates", _rates(0.025, 0.03))

    result = ValuationService().value_company(db, company)

    assert isinstance(result, dict)
    # El motor DCF queda registrado como no válido con su motivo, tanto si
    # el respaldo sectorial publica algo como si no hay más datos.
    blob = repr(result)
    assert "wacc_above_terminal_growth" in blob


def test_red_del_servicio_cubre_cualquier_motor(db, monkeypatch):
    """Un motor que deja escapar la excepción tipada no tumba la valoración."""
    from app.services import valuation_service as vs
    from app.valuation.dcf_fcff import WaccNotAboveTerminalGrowthError

    company = _company(db)
    _facts(db, company, growth=0.03)

    def boom(self, context):
        raise WaccNotAboveTerminalGrowthError()

    monkeypatch.setattr(StandardDCFEngine, "value", boom)

    result = vs.ValuationService().value_company(db, company)

    assert isinstance(result, dict)
    assert "wacc_above_terminal_growth" in repr(result)


def test_funciones_puras_mantienen_el_contrato_value_error():
    """Contrato de test_dcf_fcff.py: sigue siendo ValueError, mismo mensaje."""
    from app.valuation.dcf_fcff import DCFInputs, WaccNotAboveTerminalGrowthError, run_dcf
    from app.valuation.normalized_fcf import run_path_dcf

    with pytest.raises(ValueError, match="wacc must be greater than terminal_growth") as exc:
        run_dcf(
            DCFInputs(
                revenue=100.0, revenue_growth=0.03, fcf_margin=0.1, wacc=0.03,
                terminal_growth=0.03, net_debt=0.0, shares_outstanding=10.0,
            )
        )
    assert isinstance(exc.value, WaccNotAboveTerminalGrowthError)
    with pytest.raises(WaccNotAboveTerminalGrowthError):
        run_path_dcf(
            revenue=100.0, growth_path=[0.1], margin_path=[0.1], wacc=0.02,
            terminal_growth=0.03, net_debt=0.0, shares_outstanding=10.0,
        )
