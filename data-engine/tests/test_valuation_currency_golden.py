"""Golden tests de divisas en la valoracion: BABA, CGEO.L, SAN.MC y Toyota (TM).

Cada caso se calcula a mano. El motor de prueba vale cada accion ordinaria a
15 veces su FCF por accion, en la divisa de los hechos, para que la cuenta se
pueda seguir con lapiz. Lo que se prueba es la cadena de divisas: la divisa
de reporte de los hechos, el precio en la unidad principal del listado
(peniques -> libras), el ratio ADR y el tipo de cambio point-in-time de la
tabla BCE (cruzado via EUR), mas el bloqueo cuando no se puede reconciliar.

Antes de este cambio:
- BABA comparaba 120 CNY por accion con 15 USD por accion: MOS +700 % (~7x);
- CGEO.L comparaba 22,5 GBP con 4.255 «GBP» (peniques): x100.

Tipos BCE del 23-oct-2026 en la prueba: EURUSD 1,10; EURCNY 7,70; EURJPY 165.
Cruces: USD->CNY = 7,70 / 1,10 = 7,0; USD->JPY = 165 / 1,10 = 150.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models import Company, FinancialFact, FXRate, MarketPrice, Tenant
from app.services import valuation_service
from app.services.valuation_service import ValuationService
from app.valuation.engines.base import (
    ValuationContext,
    ValuationEngine,
    adr_comparable_price,
    margin_of_safety,
)

PRICE_DAY = date(2026, 10, 23)


class FcfMultipleEngine(ValuationEngine):
    """Motor de prueba: valor por accion ordinaria = 15 x FCF / acciones."""

    key = "fcf_multiple_test"

    def value(self, context: ValuationContext) -> dict:
        fcf = context.snapshot.value("free_cash_flow")
        shares = context.snapshot.value("shares_diluted")
        assert fcf is not None and shares is not None
        value = 15 * fcf / shares
        comparable, ratio = adr_comparable_price(context.company, context.current_price)
        return {
            "ticker": context.company.ticker,
            "model_type": "fcf_multiple_test",
            "status": "ok",
            "publishable": True,
            "current_price": context.current_price,
            "bear_value": value * 0.8,
            "base_value": value,
            "bull_value": value * 1.2,
            "expected_value": value,
            "margin_of_safety": margin_of_safety(value, comparable),
            "adr_ratio": ratio,
            "listed_share_values": ({"base": value * ratio, "expected": value * ratio} if ratio else None),
            "missing_inputs": [],
            "trace": {},
        }


@pytest.fixture
def db(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    monkeypatch.setattr(valuation_service, "resolve", lambda _company: FcfMultipleEngine())
    with Session(engine) as session:
        session.add(Tenant(id=1, external_id="t1"))
        session.commit()
        session.info["tenant_id"] = 1
        yield session
    engine.dispose()


def _ecb(db: Session, rates: dict[str, str], day: date = PRICE_DAY) -> None:
    """Tabla BCE: base EUR; ``1 quote x rate = EUR`` -> rate = 1 / EURquote."""
    for quote, eur_quote in rates.items():
        db.add(
            FXRate(
                base_currency="EUR",
                quote_currency=quote,
                rate=Decimal(1) / Decimal(eur_quote),
                rate_date=day,
                source="ECB",
            )
        )


def _company(db: Session, ticker: str, *, tags: list[str] | None = None) -> Company:
    company = Company(
        ticker=ticker,
        name=ticker,
        exchange="NYSE",
        currency="USD",  # default del enriquecimiento: el sufijo debe mandar
        company_type="standard",
        valuation_model="fcf_multiple_test",
        factor_tags=tags or [],
    )
    db.add(company)
    db.flush()
    return company


def _facts(
    db: Session,
    company: Company,
    *,
    currency: str,
    revenue: int,
    fcf: int,
    shares: int,
    period: str = "2025-12-31:FY",
    fcf_currency: str | None = None,
) -> None:
    rows = [
        ("revenue", revenue, currency),
        ("free_cash_flow", fcf, fcf_currency or currency),
        ("shares_diluted", shares, "shares"),
        ("net_debt", 0, currency),
    ]
    for metric, value, unit in rows:
        db.add(
            FinancialFact(
                company_id=company.id,
                metric=metric,
                value=Decimal(value),
                unit=unit,
                period=period,
                fiscal_year=2025,
                fiscal_quarter="FY",
                source_type="SEC",
            )
        )


def _close(db: Session, company: Company, close: str, *, quote_currency: str | None = None) -> None:
    value = Decimal(close)
    db.add(
        MarketPrice(
            company_id=company.id,
            date=PRICE_DAY,
            open=value,
            high=value,
            low=value,
            close=value,
            source="test",
            quote_currency=quote_currency,
        )
    )


def _value(db: Session, company: Company) -> dict:
    db.commit()
    return ValuationService().value_company(db, company)


def test_golden_baba_cny_contra_adr_en_usd(db: Session) -> None:
    # FCF 152.000 M CNY / 19.000 M ordinarias = 8 CNY -> x15 = 120 CNY/ordinaria.
    # 120 CNY / 7,0 = 17,142857 USD/ordinaria; x8 (1 ADS = 8) = 137,142857 USD/ADS.
    # Precio ADS 120 USD -> 15 USD/ordinaria.
    company = _company(db, "BABA")
    _facts(
        db,
        company,
        currency="CNY",
        revenue=996_000_000_000,
        fcf=152_000_000_000,
        shares=19_000_000_000,
        period="2025-03-31:FY",
    )
    _close(db, company, "120")
    _ecb(db, {"USD": "1.10", "CNY": "7.70"})

    result = _value(db, company)

    assert result["status"] == "ok"
    assert result["value_currency"] == "USD"
    assert result["currency"]["status"] == "converted"
    assert result["currency"]["reporting_currency"] == "CNY"
    assert result["currency"]["fx"]["path"] == ["USD", "EUR", "CNY"]
    assert result["currency"]["fx"]["rate"] == pytest.approx(7.0, rel=1e-6)
    assert result["base_value"] == pytest.approx(17.142857, rel=1e-6)
    assert result["listed_share_values"]["base"] == pytest.approx(137.142857, rel=1e-6)
    assert result["current_price"] == pytest.approx(120.0)
    # MOS en una sola divisa: el mismo que valor por ADS contra precio del ADS.
    assert result["margin_of_safety"] == pytest.approx(margin_of_safety(137.142857, 120.0), rel=1e-6)


@pytest.mark.parametrize("quote_currency", ["GBX", "GBp"])
def test_golden_cgeo_l_peniques_a_libras(db: Session, quote_currency: str) -> None:
    # FCF 45 M GBP / 30 M acciones = 1,5 GBP -> x15 = 22,5 GBP.
    # Cierre 4.255 GBX = 42,55 GBP. Misma divisa: sin FX.
    company = _company(db, "CGEO.L")
    _facts(db, company, currency="GBP", revenue=300_000_000, fcf=45_000_000, shares=30_000_000)
    # The fixture must state the provider unit; .L alone is not proof of pence.
    _close(db, company, "4255", quote_currency=quote_currency)

    result = _value(db, company)

    assert result["status"] == "ok"
    assert result["value_currency"] == "GBP"
    assert result["currency"]["status"] == "same"
    assert result["base_value"] == pytest.approx(22.5)
    assert result["current_price"] == pytest.approx(42.55)
    assert result["margin_of_safety"] == pytest.approx(margin_of_safety(22.5, 42.55))


@pytest.mark.parametrize("quote_currency", [None, "USD"])
def test_cgeo_ambiguous_or_incompatible_quote_has_no_price_or_mos(db: Session, quote_currency: str | None) -> None:
    """Guard against making the golden green by guessing pence from .L."""
    company = _company(db, "CGEO.L")
    _facts(db, company, currency="GBP", revenue=300_000_000, fcf=45_000_000, shares=30_000_000)
    _close(db, company, "4255", quote_currency=quote_currency)

    result = _value(db, company)

    # Intrinsic value can exist without a comparable market price.
    assert result["base_value"] == pytest.approx(22.5)
    assert result["current_price"] is None
    assert result["margin_of_safety"] is None
    assert result["trace"]["price_status"] == "missing_market_price"
    assert result["trace"]["incomplete_without_price"] is True


def test_cgeo_explicit_major_unit_is_not_divided_again(db: Session) -> None:
    """A London ticker may explicitly receive GBP, not only GBX/GBp."""
    company = _company(db, "CGEO.L")
    _facts(db, company, currency="GBP", revenue=300_000_000, fcf=45_000_000, shares=30_000_000)
    _close(db, company, "42.55", quote_currency="GBP")

    result = _value(db, company)

    assert result["current_price"] == pytest.approx(42.55)
    assert result["margin_of_safety"] == pytest.approx(margin_of_safety(22.5, 42.55))
    assert result["trace"]["price_status"] == "ok"


def test_golden_san_mc_en_euros(db: Session) -> None:
    # FCF 12.600 M EUR / 15.000 M acciones = 0,84 EUR -> x15 = 12,6 EUR.
    # Cierre 8,40 EUR. La ficha dice USD por defecto, pero .MC cotiza en EUR:
    # no hace falta (ni se usa) ningun tipo de cambio.
    company = _company(db, "SAN.MC")
    _facts(db, company, currency="EUR", revenue=60_000_000_000, fcf=12_600_000_000, shares=15_000_000_000)
    _close(db, company, "8.40")

    result = _value(db, company)

    assert result["status"] == "ok"
    assert result["value_currency"] == "EUR"
    assert result["currency"]["status"] == "same"
    assert result["base_value"] == pytest.approx(12.6)
    assert result["margin_of_safety"] == pytest.approx(margin_of_safety(12.6, 8.40))


def test_golden_toyota_adr_en_yenes(db: Session) -> None:
    # FCF 3.900.000 M JPY / 13.000 M ordinarias = 300 JPY -> x15 = 4.500 JPY.
    # 4.500 JPY / 150 = 30 USD/ordinaria; x10 (1 ADS = 10, tabla ADR) = 300 USD/ADS.
    # Precio ADS 180 USD -> 18 USD/ordinaria.
    company = _company(db, "TM")
    _facts(
        db,
        company,
        currency="JPY",
        revenue=48_000_000_000_000,
        fcf=3_900_000_000_000,
        shares=13_000_000_000,
        period="2025-03-31:FY",
    )
    _close(db, company, "180")
    _ecb(db, {"USD": "1.10", "JPY": "165"})

    result = _value(db, company)

    assert result["status"] == "ok"
    assert result["value_currency"] == "USD"
    assert result["adr_ratio"] == 10.0
    assert result["currency"]["fx"]["rate"] == pytest.approx(150.0, rel=1e-6)
    assert result["base_value"] == pytest.approx(30.0, rel=1e-6)
    assert result["listed_share_values"]["base"] == pytest.approx(300.0, rel=1e-6)
    assert result["margin_of_safety"] == pytest.approx(margin_of_safety(300.0, 180.0), rel=1e-6)


def test_sin_tipo_de_cambio_se_bloquea(db: Session) -> None:
    company = _company(db, "BABA")
    _facts(
        db,
        company,
        currency="CNY",
        revenue=996_000_000_000,
        fcf=152_000_000_000,
        shares=19_000_000_000,
        period="2025-03-31:FY",
    )
    _close(db, company, "120")
    _ecb(db, {"USD": "1.10"})  # sin CNY

    result = _value(db, company)

    assert result["status"] == "insufficient_data"
    assert result["publishable"] is False
    assert result["missing_inputs"] == ["fx_rate:CNY/USD"]
    assert result["base_value"] is None
    assert result["margin_of_safety"] is None
    assert result["value_currency"] is None
    assert result["currency"]["status"] == "blocked"


def test_tipo_de_cambio_viejo_no_vale(db: Session) -> None:
    # Un tipo de hace casi tres meses no es el del dia del precio.
    company = _company(db, "BABA")
    _facts(
        db,
        company,
        currency="CNY",
        revenue=996_000_000_000,
        fcf=152_000_000_000,
        shares=19_000_000_000,
        period="2025-03-31:FY",
    )
    _close(db, company, "120")
    _ecb(db, {"USD": "1.10", "CNY": "7.70"}, day=date(2026, 8, 1))

    result = _value(db, company)

    assert result["status"] == "insufficient_data"
    assert result["missing_inputs"] == ["fx_rate:CNY/USD"]


def test_tipo_de_cambio_futuro_no_se_usa(db: Session) -> None:
    # Point-in-time: un tipo posterior a la fecha del precio es lookahead.
    company = _company(db, "BABA")
    _facts(
        db,
        company,
        currency="CNY",
        revenue=996_000_000_000,
        fcf=152_000_000_000,
        shares=19_000_000_000,
        period="2025-03-31:FY",
    )
    _close(db, company, "120")
    _ecb(db, {"USD": "1.10", "CNY": "7.70"}, day=date(2026, 10, 24))

    result = _value(db, company)

    assert result["status"] == "insufficient_data"


def test_hechos_en_varias_divisas_se_bloquean(db: Session) -> None:
    company = _company(db, "BABA")
    _facts(
        db,
        company,
        currency="CNY",
        revenue=996_000_000_000,
        fcf=21_000_000_000,
        shares=19_000_000_000,
        period="2025-03-31:FY",
        fcf_currency="USD",
    )
    _close(db, company, "120")
    _ecb(db, {"USD": "1.10", "CNY": "7.70"})

    result = _value(db, company)

    assert result["status"] == "insufficient_data"
    assert result["missing_inputs"] == ["single_reporting_currency"]
    assert result["base_value"] is None


def test_motor_dcf_real_es_homogeneo_en_la_divisa(db: Session, monkeypatch) -> None:
    """Con el DCF de verdad: los mismos datos en CNY (x7) con FX 7 dan el mismo
    valor en USD que los datos ya en USD. El DCF es lineal en la divisa
    (WACC y crecimientos son tasas), asi que convertir el precio a la divisa de
    los hechos y el resultado de vuelta equivale a convertir los hechos."""
    from app.valuation.engines import resolve as real_resolve

    monkeypatch.setattr(valuation_service, "resolve", real_resolve)

    def seed(ticker: str, currency: str, scale: int) -> Company:
        company = Company(
            ticker=ticker,
            name=ticker,
            exchange="NYSE",
            currency="USD",
            company_type="standard",
            valuation_model="standard_dcf",
            factor_tags=[],
        )
        db.add(company)
        db.flush()
        for metric, value, unit in [
            ("revenue", 10_000_000_000 * scale, currency),
            ("free_cash_flow", 1_500_000_000 * scale, currency),
            ("revenue_growth", Decimal("0.08"), "decimal"),
            ("shares_diluted", 1_000_000_000, "shares"),
            ("net_debt", 2_000_000_000 * scale, currency),
        ]:
            db.add(
                FinancialFact(
                    company_id=company.id,
                    metric=metric,
                    value=Decimal(value),
                    unit=unit,
                    period="2025-12-31:FY",
                    fiscal_year=2025,
                    fiscal_quarter="FY",
                    source_type="SEC",
                )
            )
        _close(db, company, "20")
        return company

    usd = seed("USDCO", "USD", 1)
    cny = seed("CNYCO", "CNY", 7)
    _ecb(db, {"USD": "1.10", "CNY": "7.70"})

    native = _value(db, usd)
    converted = _value(db, cny)

    assert native["base_value"] is not None
    assert converted["currency"]["status"] == "converted"
    assert converted["base_value"] == pytest.approx(native["base_value"], rel=1e-6)
    assert converted["margin_of_safety"] == pytest.approx(native["margin_of_safety"], rel=1e-6)
    assert converted["current_price"] == pytest.approx(20.0)


def test_computed_margin_convention_is_persisted_with_output(db: Session) -> None:
    from sqlalchemy import select

    from app.models import ValuationOutput
    from app.valuation.margin_convention import MARGIN_OF_SAFETY_CONVENTION

    company = _company(db, "CONV")
    _facts(db, company, currency="USD", revenue=1000, fcf=100, shares=10, period="2025-12-31:FY")
    _close(db, company, "100")
    result = _value(db, company)
    assert result["margin_of_safety"] == pytest.approx(1 / 3)
    assert result["trace"]["margin_of_safety_convention"] == MARGIN_OF_SAFETY_CONVENTION
    model = ValuationService().persist_output(db, company, result)
    outputs = list(db.scalars(select(ValuationOutput).where(ValuationOutput.valuation_model_id == model.id)))
    assert len(outputs) == 3
    assert all(row.output_payload["trace"]["margin_of_safety_convention"] == MARGIN_OF_SAFETY_CONVENTION for row in outputs)
