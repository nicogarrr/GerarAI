"""Tests de la proyección mes a mes de dividendos con escenario fiscal."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import (
    Base,
    Company,
    DividendRecord,
    FXRate,
    Portfolio,
    Position,
)
from app.services.dividend_projection_service import DividendProjectionService


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _company(db, ticker="AAPL", currency="USD", country="US"):
    company = Company(
        ticker=ticker,
        name=ticker,
        exchange="NASDAQ",
        currency=currency,
        sector="Tech",
        industry="Tech",
        company_type="holding",
        valuation_model="unassigned",
        domicile_country=country,
        special_sources=[],
        special_risks=[],
        factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def _position(db, company, quantity="10", currency="USD", base="EUR"):
    portfolio = Portfolio(name="p", base_currency=base)
    db.add(portfolio)
    db.commit()
    position = Position(
        portfolio_id=portfolio.id,
        company_id=company.id,
        quantity=Decimal(quantity),
        average_cost=Decimal("150"),
        market_price=Decimal("200"),
        market_value=Decimal("2000"),
        currency=currency,
    )
    db.add(position)
    db.commit()
    return position


def _dividend(db, company, ex_date, amount, currency="USD", pay_date=None):
    record = DividendRecord(
        company_id=company.id,
        ex_date=ex_date,
        pay_date=pay_date,
        amount=Decimal(str(amount)),
        currency=currency,
        source="yahoo",
    )
    db.add(record)
    db.commit()
    return record


def _fx(db, quote="USD", base="EUR", rate="0.9"):
    db.add(
        FXRate(
            base_currency=base,
            quote_currency=quote,
            rate_date=date.today(),
            rate=Decimal(rate),
        )
    )
    db.commit()


def test_quarterly_payer_projects_same_amounts_next_year(db):
    company = _company(db)
    _position(db, company)
    today = date.today()
    for days_ago in (15, 105, 195, 285):
        _dividend(db, company, today - timedelta(days=days_ago), "0.25")
    _fx(db)

    out = DividendProjectionService().project(db, months=12)

    assert out["label"] == "INFERIDO"
    assert out["coverage"]["with_data"] == 1
    assert out["coverage"]["sin_datos"] == []
    pos = out["positions"][0]
    assert pos["ticker"] == "AAPL"
    assert pos["frequency_last_year"] == 4
    assert pos["gross_native"] == pytest.approx(10.0)
    assert pos["gross_base"] == pytest.approx(9.0)
    assert pos["source_withheld_base"] == pytest.approx(1.35)
    month_sum = sum(m["gross_base"] for m in out["months"])
    assert month_sum == pytest.approx(9.0)


def test_position_without_records_is_sin_datos_never_zero(db):
    company = _company(db, ticker="XYZ")
    _position(db, company)
    _fx(db)

    out = DividendProjectionService().project(db, months=12)

    assert out["coverage"]["with_data"] == 0
    assert out["coverage"]["sin_datos"] == ["XYZ"]
    assert all(m["gross_base"] == 0.0 for m in out["months"])
    assert out["positions"] == []


def test_fiscal_scenario_progressive_irpf_and_double_taxation(db):
    company = _company(db)
    _position(db, company, quantity="100000")
    today = date.today()
    _dividend(db, company, today - timedelta(days=60), "1.00")
    _dividend(db, company, today - timedelta(days=200), "1.00")
    _fx(db, rate="1.0")

    out = DividendProjectionService().project(db, months=12)

    year = str(today.year + 1)
    fiscal = out["fiscal_by_year"][year]
    # 200.000 EUR: escala 2025 -> 44.880 cuota; tipo medio 22,44% > 15%,
    # asi que la deduccion cubre todo el impuesto extranjero (30.000).
    assert fiscal["gross_base"] == pytest.approx(200000.0)
    assert fiscal["irpf_scenario"] == pytest.approx(44880.0)
    assert fiscal["source_withheld_foreign"] == pytest.approx(30000.0)
    assert fiscal["double_tax_deduction"] == pytest.approx(30000.0)
    assert fiscal["net_scenario"] == pytest.approx(200000.0 - 44880.0)
    assert fiscal["covered_tickers"] == ["AAPL"]
    assert "condicionado" in fiscal["note"]


def test_unknown_country_withholding_is_none_and_excluded(db):
    company = _company(db, ticker="NSR", country="JP")
    _position(db, company)
    today = date.today()
    _dividend(db, company, today - timedelta(days=100), "5.00")
    _fx(db)

    out = DividendProjectionService().project(db, months=12)

    pos = out["positions"][0]
    assert pos["source_withholding_rate"] is None
    assert pos["source_withheld_base"] is None
    assert out["coverage"]["unknown_source_withholding"] == ["NSR"]
    months_with_excluded = [m for m in out["months"] if m["excluded_tickers"]]
    assert months_with_excluded
    for m in months_with_excluded:
        assert m["gross_base"] == 0.0
        assert "Subconjunto cubierto" in m["note"]
        # El bruto con FX conocido se muestra aparte, nunca como neto.
        assert m["gross_unverified_base"] > 0
        assert m["gross_total_base"] == m["gross_unverified_base"]
    summary = out["gross_summary"]
    assert summary["gross_total_base"] == pytest.approx(pos["gross_base"])
    assert summary["gross_unverified_base"] == pytest.approx(pos["gross_base"])
    assert "retención en origen no verificada" in summary["label"]
    assert summary["excluded_no_fx"] == []
    assert summary["complete"] is True


def test_currency_mismatch_records_are_skipped(db):
    company = _company(db, ticker="GBPAY", currency="GBP", country="GB")
    _position(db, company, currency="GBP")
    today = date.today()
    _dividend(db, company, today - timedelta(days=50), "1.00", currency="USD")

    out = DividendProjectionService().project(db, months=12)

    assert out["coverage"]["sin_datos"] == ["GBPAY"]
    assert out["positions"] == []


def test_missing_fx_excludes_base_aggregation(db):
    company = _company(db, ticker="NOFX", country="US")
    _position(db, company)
    today = date.today()
    _dividend(db, company, today - timedelta(days=70), "2.00")

    out = DividendProjectionService().project(db, months=12)

    assert out["coverage"]["fx_missing"] == ["NOFX"]
    assert out["positions"][0]["gross_base"] is None
    assert all(m["gross_base"] == 0.0 for m in out["months"])
    excluded = [m for m in out["months"] if m["excluded_tickers"]]
    assert excluded and all("Subconjunto cubierto" in m["note"] for m in excluded)
    summary = out["gross_summary"]
    assert summary["excluded_no_fx"] == ["NOFX"]
    assert summary["complete"] is False
    assert summary["gross_total_base"] == 0.0


def test_horizon_24_replicates_both_years(db):
    company = _company(db)
    _position(db, company)
    today = date.today()
    _dividend(db, company, today - timedelta(days=30), "1.00")
    _fx(db, rate="1.0")

    out = DividendProjectionService().project(db, months=24)

    per_year = {}
    for m in out["months"]:
        per_year[m["month"][:4]] = per_year.get(m["month"][:4], 0.0) + m["gross_base"]
    year1 = str(today.year + 1)
    year2 = str(today.year + 2)
    assert per_year.get(year1, 0.0) == pytest.approx(10.0)
    assert per_year.get(year2, 0.0) == pytest.approx(10.0)


def test_future_declared_dividend_is_reported_not_replicated(db):
    company = _company(db)
    _position(db, company)
    today = date.today()
    _dividend(db, company, today - timedelta(days=90), "0.50")
    _dividend(db, company, today + timedelta(days=30), "100.00")
    _fx(db, rate="1.0")

    out = DividendProjectionService().project(db, months=12)

    pos = out["positions"][0]
    assert pos["frequency_last_year"] == 1
    assert pos["gross_native"] == pytest.approx(5.0)
    assert len(out["declared_future"]) == 1
    future = out["declared_future"][0]
    assert future["amount_per_share"] == pytest.approx(100.0)
    assert future["label"] == "INGESTADO"
    assert future["source"] == "yahoo"


def test_zero_and_short_positions_ignored(db):
    company = _company(db)
    _position(db, company, quantity="0")
    today = date.today()
    _dividend(db, company, today - timedelta(days=45), "1.00")
    _fx(db)

    out = DividendProjectionService().project(db, months=12)

    assert out["coverage"]["with_data"] == 0
    assert out["positions"] == []
    assert all(m["gross_base"] == 0.0 for m in out["months"])


def test_non_eur_base_disables_fiscal_scenario(db):
    company = _company(db)
    _position(db, company, quantity="1000", base="USD")
    today = date.today()
    _dividend(db, company, today - timedelta(days=80), "10.00")
    _fx(db, quote="USD", base="USD", rate="1.0")

    out = DividendProjectionService().project(db, months=12)

    year = str(today.year + 1)
    fiscal = out["fiscal_by_year"][year]
    assert fiscal["irpf_scenario"] is None
    assert fiscal["net_scenario"] is None
    assert "no es EUR" in fiscal["note"]


def test_spanish_withholding_is_prepayment_not_double_charge(db):
    company = _company(db, ticker="ESPCO", currency="EUR", country="ES")
    _position(db, company, quantity="100", currency="EUR")
    today = date.today()
    _dividend(db, company, today - timedelta(days=90), "1.00", currency="EUR")
    _fx(db, quote="EUR", base="EUR", rate="1.0")

    out = DividendProjectionService().project(db, months=12)

    year = str(today.year + 1)
    fiscal = out["fiscal_by_year"][year]
    # 100 EUR brutos: retencion a cuenta 19 (anticipo), cuota IRPF 19 (19%).
    # Neto = 100 - 19 de impuesto total = 81, NO 62 (sin doble cargo).
    assert fiscal["gross_base"] == pytest.approx(100.0)
    assert fiscal["retencion_a_cuenta_es"] == pytest.approx(19.0)
    assert fiscal["source_withheld_foreign"] == pytest.approx(0.0)
    assert fiscal["irpf_scenario"] == pytest.approx(19.0)
    assert fiscal["double_tax_deduction"] == pytest.approx(0.0)
    assert fiscal["cuota_pendiente_estimada"] == pytest.approx(0.0)
    assert fiscal["net_scenario"] == pytest.approx(81.0)


def test_unknown_country_excluded_from_fiscal_year(db):
    company = _company(db, ticker="NSR", country=None)
    _position(db, company)
    today = date.today()
    _dividend(db, company, today - timedelta(days=100), "1.00")
    _fx(db, rate="1.0")

    out = DividendProjectionService().project(db, months=12)

    assert out["coverage"]["unknown_source_withholding"] == ["NSR"]
    assert out["fiscal_by_year"], "el ano con todo excluido debe tener fila"
    for fiscal in out["fiscal_by_year"].values():
        assert fiscal["gross_base"] is None
        assert fiscal["covered_tickers"] == []
        assert "NSR" in fiscal["excluded_tickers"]


def test_annual_cycle_not_duplicated_at_boundaries(db):
    company = _company(db)
    _position(db, company)
    today = date.today()
    # Registro exactamente en el cutoff (hoy - 1 ano) y su ciclo siguiente
    # (hoy): la replica debe contar UN ciclo anual, no dos.
    _dividend(db, company, today.replace(year=today.year - 1), "1.00")
    _dividend(db, company, today, "1.00")
    _fx(db, rate="1.0")

    out = DividendProjectionService().project(db, months=12)

    pos = out["positions"][0]
    assert pos["frequency_last_year"] == 1
    assert pos["gross_native"] == pytest.approx(10.0)


class _FakeDate(date):
    """date con today() fijado para probar el clamp del horizonte."""

    _today = date(2026, 1, 31)

    @classmethod
    def today(cls):
        return cls._today


def _patch_today(monkeypatch, value):
    _FakeDate._today = value
    monkeypatch.setattr("app.services.dividend_projection_service.date", _FakeDate)


def test_end_date_clamp_jan31(db, monkeypatch):
    _patch_today(monkeypatch, date(2026, 1, 31))
    out = DividendProjectionService().project(db, months=1)
    assert out["months"][-1]["month"] == "2026-02"


def test_end_date_clamp_feb29_leap(db, monkeypatch):
    _patch_today(monkeypatch, date(2028, 2, 29))
    out = DividendProjectionService().project(db, months=12)
    assert out["months"][-1]["month"] == "2029-02"


def test_horizon_13_months(db, monkeypatch):
    _patch_today(monkeypatch, date(2026, 12, 31))
    out = DividendProjectionService().project(db, months=13)
    assert out["months"][-1]["month"] == "2028-01"


def test_cuota_pendiente_us_deduces_di(db):
    company = _company(db)
    _position(db, company, quantity="100")
    today = date.today()
    _dividend(db, company, today - timedelta(days=90), "10.00")
    _fx(db, rate="1.0")

    out = DividendProjectionService().project(db, months=12)

    year = str(today.year + 1)
    fiscal = out["fiscal_by_year"][year]
    # 1.000 EUR brutos: IRPF 190, DI 150, a cuenta 0 -> pendiente 40.
    assert fiscal["irpf_scenario"] == pytest.approx(190.0)
    assert fiscal["double_tax_deduction"] == pytest.approx(150.0)
    assert fiscal["retencion_a_cuenta_es"] == pytest.approx(0.0)
    assert fiscal["cuota_pendiente_estimada"] == pytest.approx(40.0)
    assert fiscal["net_scenario"] == pytest.approx(1000.0 - 190.0)


def test_cuota_pendiente_mixed_es_us(db):
    es = _company(db, ticker="ESCO", currency="EUR", country="ES")
    _position(db, es, quantity="100", currency="EUR")
    us = _company(db, ticker="USCO", currency="USD", country="US")
    _position(db, us, quantity="100", currency="USD")
    today = date.today()
    _dividend(db, es, today - timedelta(days=90), "1.00", currency="EUR")
    _dividend(db, us, today - timedelta(days=90), "1.00")
    _fx(db, quote="USD", base="EUR", rate="1.0")
    _fx(db, quote="EUR", base="EUR", rate="1.0")

    out = DividendProjectionService().project(db, months=12)

    year = str(today.year + 1)
    fiscal = out["fiscal_by_year"][year]
    # 200 EUR (100 ES + 100 US): IRPF 38, DI 15, a cuenta 19 -> pendiente 4.
    assert fiscal["gross_base"] == pytest.approx(200.0)
    assert fiscal["irpf_scenario"] == pytest.approx(38.0)
    assert fiscal["double_tax_deduction"] == pytest.approx(15.0)
    assert fiscal["retencion_a_cuenta_es"] == pytest.approx(19.0)
    assert fiscal["cuota_pendiente_estimada"] == pytest.approx(4.0)
    assert fiscal["net_scenario"] == pytest.approx(200.0 - 38.0)


def test_fiscal_year_with_only_excluded_positions_shows_row(db):
    company = _company(db, ticker="NSR", country="JP")
    _position(db, company)
    today = date.today()
    _dividend(db, company, today - timedelta(days=100), "5.00")
    _fx(db)

    out = DividendProjectionService().project(db, months=12)

    assert out["fiscal_by_year"], "el ano con todo excluido debe tener fila"
    row = list(out["fiscal_by_year"].values())[0]
    assert row["covered_tickers"] == []
    assert row["excluded_tickers"] == ["NSR"]
    assert row["gross_base"] is None
    assert row["irpf_scenario"] is None
    assert row["net_scenario"] is None
    assert "Sin datos" in row["note"]


def _setup_payer(db, ticker, country):
    company = _company(db, ticker=ticker, country=country)
    _position(db, company, quantity="100")
    _dividend(db, company, date.today() - timedelta(days=100), "1.00")
    _fx(db)
    return company


def test_verified_canadian_payer_uses_treaty_ceiling_as_scenario(db):
    _setup_payer(db, "BN", "CA")

    out = DividendProjectionService().project(db, months=12)

    pos = out["positions"][0]
    assert pos["source_withholding_rate"] == pytest.approx(0.15)
    assert pos["withholding_basis"] == "emisor_verificado"
    assert pos["withholding_kind"] == "techo_convenio"
    assert pos["unverified_reason"] is None
    assert out["coverage"]["unknown_source_withholding"] == []
    assert any("25 %" in c for c in out["fiscal_conditions"])


def test_canadian_domicile_without_verified_payer_stays_unverified(db):
    _setup_payer(db, "XYZ", "CA")

    out = DividendProjectionService().project(db, months=12)

    pos = out["positions"][0]
    assert pos["source_withholding_rate"] is None
    assert out["coverage"]["unknown_source_withholding"] == ["XYZ"]
    assert "CA" in out["coverage"]["unverified_reasons"]["XYZ"]
    assert out["gross_summary"]["gross_unverified_base"] > 0


def test_baba_cayman_issuer_is_zero_scenario_with_visible_conditions(db):
    _setup_payer(db, "BABA", "HK")

    out = DividendProjectionService().project(db, months=12)

    pos = out["positions"][0]
    assert pos["domicile_country"] == "KY"
    assert pos["withholding_basis"] == "emisor_verificado"
    assert pos["withholding_kind"] == "sin_impuesto_origen_escenario"
    assert pos["source_withholding_rate"] == 0
    assert pos["unverified_reason"] is None
    cond = pos["scenario_conditions"]
    assert "Item 10.E" in cond and "20 %" in cond and "NO verificada" in cond
    assert "depositario" in cond
    assert out["coverage"]["unknown_source_withholding"] == []


def test_fiscal_conditions_do_not_contradict_the_ky_zero_scenario(db):
    _setup_payer(db, "BABA", "HK")

    out = DividendProjectionService().project(db, months=12)

    joined = " ".join(out["fiscal_conditions"])
    assert "neto queda N/D" not in joined and "no se asume 0 %" not in joined
    assert "Item 10.E" in joined and "NO es la retención efectiva del broker" in joined


def test_non_baba_positions_have_no_scenario_conditions(db):
    _setup_payer(db, "BN", "CA")

    out = DividendProjectionService().project(db, months=12)

    assert out["positions"][0]["scenario_conditions"] is None


def test_hk_domicile_without_verified_issuer_is_not_assumed_zero(db):
    _setup_payer(db, "HKCO", "HK")

    out = DividendProjectionService().project(db, months=12)

    pos = out["positions"][0]
    assert pos["source_withholding_rate"] is None
    assert out["coverage"]["unknown_source_withholding"] == ["HKCO"]


def test_fiscal_conditions_have_no_garbled_characters():
    from app.services import dividend_projection_service as svc

    assert "segên" not in " ".join(svc._FISCAL_CONDITIONS)  # noqa: SLF001


def test_uncertain_yahoo_event_is_not_sin_datos_and_not_projected(db):
    from datetime import datetime

    from app.models.entities import DividendRecord

    company = _company(db, ticker="UNC")
    _position(db, company)
    _fx(db)
    ex = date.today() - timedelta(days=30)
    for amount, fetched in (("0.5", datetime(2026, 1, 1)), ("2.0", datetime(2026, 9, 1))):
        db.add(DividendRecord(company_id=company.id, ex_date=ex, amount=Decimal(amount), currency="USD", source="yahoo_finance", fetched_at=fetched))
    db.commit()

    out = DividendProjectionService().project(db, months=12)

    assert out["coverage"]["uncertain_dividends"] == ["UNC"]
    assert out["coverage"]["sin_datos"] == []  # incierto no es «sin dividendos»
    assert out["gross_summary"]["excluded_uncertain_dividends"] == ["UNC"]
    assert out["gross_summary"]["complete"] is False
    assert out["positions"] == []


def test_partial_total_when_one_position_uncertain_and_another_has_data(db):
    from datetime import datetime

    from app.models.entities import DividendRecord

    good = _company(db, ticker="GOOD")
    _position(db, good)
    unc = _company(db, ticker="UNC")
    position = Position(
        portfolio_id=1, company_id=unc.id, quantity=Decimal("10"), average_cost=Decimal("150"),
        market_price=Decimal("200"), market_value=Decimal("2000"), currency="USD",
    )
    db.add(position)
    _fx(db)
    today = date.today()
    for q in (30, 120, 210, 300):
        db.add(DividendRecord(company_id=good.id, ex_date=today - timedelta(days=q), amount=Decimal("0.5"), currency="USD", source="fmp"))
    ex = today - timedelta(days=30)
    for amount, fetched in (("0.2", datetime(2026, 1, 1)), ("0.8", datetime(2026, 9, 1))):
        db.add(DividendRecord(company_id=unc.id, ex_date=ex, amount=Decimal(amount), currency="USD", source="yahoo_finance", fetched_at=fetched))
    db.commit()

    out = DividendProjectionService().project(db, months=12)

    assert out["gross_summary"]["gross_total_base"] > 0
    assert out["gross_summary"]["complete"] is False
    assert out["gross_summary"]["excluded_uncertain_dividends"] == ["UNC"]
    assert out["coverage"]["uncertain_dividends"] == ["UNC"] and out["coverage"]["sin_datos"] == []
    assert [p["ticker"] for p in out["positions"]] == ["GOOD"]


# --- P1-6: dedupe cross-provider conservador (Yahoo vs FMP) ---------------


def _src_dividend(db, company, ex_date, amount, source, currency="USD"):
    db.add(DividendRecord(
        company_id=company.id, ex_date=ex_date, amount=Decimal(str(amount)),
        currency=currency, source=source,
    ))
    db.commit()


def test_yahoo_and_fmp_same_ex_date_different_amount_are_not_summed(db):
    # Yahoo da el importe ajustado por split y FMP el declarado: sumarlos
    # duplicaria el cobro. Sin poder identificar el evento, se excluye.
    company = _company(db, ticker="XPRV")
    _position(db, company)
    _fx(db)
    ex = date.today() - timedelta(days=30)
    _src_dividend(db, company, ex, "0.1925", "yahoo_finance")
    _src_dividend(db, company, ex, "0.77", "fmp")

    out = DividendProjectionService().project(db, months=12)

    assert out["coverage"]["uncertain_dividends"] == ["XPRV"]
    assert out["coverage"]["sin_datos"] == []
    assert out["positions"] == []
    assert out["gross_summary"]["complete"] is False
    assert out["gross_summary"]["excluded_uncertain_dividends"] == ["XPRV"]


def test_cross_provider_conflict_on_one_date_does_not_hide_other_clean_dates(db):
    # El conflicto es de UNA fecha, pero la posicion entera queda marcada
    # incierta (regla vigente): nunca un total parcial presentado como completo.
    company = _company(db, ticker="XMIX")
    _position(db, company)
    _fx(db)
    today = date.today()
    _src_dividend(db, company, today - timedelta(days=30), "0.20", "yahoo_finance")
    _src_dividend(db, company, today - timedelta(days=30), "0.80", "fmp")
    _src_dividend(db, company, today - timedelta(days=120), "0.50", "fmp")

    out = DividendProjectionService().project(db, months=12)

    assert out["coverage"]["uncertain_dividends"] == ["XMIX"]
    assert out["gross_summary"]["complete"] is False


def test_same_provider_regular_plus_special_does_not_trigger_cross_provider_rule(db):
    # Dos filas FMP el mismo dia (ordinario + especial) siguen sumandose: la
    # regla cross-provider exige al menos dos proveedores distintos.
    company = _company(db, ticker="XSPC")
    _position(db, company, quantity="10")
    _fx(db, rate="1")
    ex = date.today() - timedelta(days=30)
    _src_dividend(db, company, ex, "0.50", "fmp")
    _src_dividend(db, company, ex, "2.00", "fmp")

    out = DividendProjectionService().project(db, months=12)

    assert out["coverage"]["uncertain_dividends"] == []
    assert [p["ticker"] for p in out["positions"]] == ["XSPC"]
    assert out["positions"][0]["gross_native"] == pytest.approx(25.0)


def test_yahoo_and_fmp_on_different_dates_are_both_counted(db):
    company = _company(db, ticker="XDIF")
    _position(db, company, quantity="10")
    _fx(db, rate="1")
    today = date.today()
    _src_dividend(db, company, today - timedelta(days=30), "0.50", "yahoo_finance")
    _src_dividend(db, company, today - timedelta(days=120), "0.50", "fmp")

    out = DividendProjectionService().project(db, months=12)

    assert out["coverage"]["uncertain_dividends"] == []
    assert out["positions"][0]["gross_native"] == pytest.approx(10.0)


def test_cross_provider_in_other_currency_does_not_conflict(db):
    # GBX (peniques) y GBP son divisas distintas: no se agrupan ni se convierten
    # aqui. Solo cuentan las filas de la divisa de la posicion.
    company = _company(db, ticker="XGBP", currency="GBP", country="GB")
    _position(db, company, quantity="100", currency="GBP")
    _fx(db, quote="GBP", rate="1.15")
    ex = date.today() - timedelta(days=40)
    _src_dividend(db, company, ex, "0.20", "fmp", currency="GBP")
    _src_dividend(db, company, ex, "20", "yahoo_finance", currency="GBX")

    out = DividendProjectionService().project(db, months=12)

    assert out["coverage"]["uncertain_dividends"] == []
    assert out["positions"][0]["gross_native"] == pytest.approx(20.0)  # 0.20 * 100, GBX ignorado


def test_cross_provider_future_ex_date_conflict_is_not_reported_as_trailing_uncertain(db):
    company = _company(db, ticker="XFUT")
    _position(db, company)
    _fx(db)
    today = date.today()
    _src_dividend(db, company, today - timedelta(days=60), "0.50", "fmp")
    _src_dividend(db, company, today + timedelta(days=10), "0.20", "yahoo_finance")
    _src_dividend(db, company, today + timedelta(days=10), "0.80", "fmp")

    out = DividendProjectionService().project(db, months=12)

    assert out["coverage"]["uncertain_dividends"] == []
    assert out["positions"][0]["frequency_last_year"] == 1
