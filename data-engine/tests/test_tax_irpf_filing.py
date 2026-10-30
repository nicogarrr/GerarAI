"""Capa IRPF (casillas Modelo 100 + deducción por doble imposición).

Verificado contra fuentes oficiales:
- Diseño de casillas: anexo del Modelo 100 en la Orden HAC/277/2026
  (BOE-A-2026-7041): 0327 denominación, 0328 transmisión global, 0331
  adquisición global, 0336/0338 resultados, 0339/0340 sumas; 0029
  dividendos; 0588 doble imposición internacional; 0597 retenciones por
  rendimientos del capital mobiliario.
- Escala del ahorro 2025: Ley 7/2024 (19/21/23/27/30; sede AEAT,
  "Principales novedades Ley 7/2024").

Hermético: SQLite en memoria, sin red.
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, FXRate, Portfolio, Tenant, Transaction
from app.services.tax_irpf_filing import (
    CASILLAS_BASIS,
    build_casillas,
    build_double_taxation,
    calculate_savings_tax,
)
from app.services.tax_report_service import TaxReportService


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _eur_portfolio(db: Session) -> None:
    db.add(Portfolio(name="Main", base_currency="EUR", is_default=True))
    db.commit()


def _company(db: Session, ticker: str, country: str | None = None) -> Company:
    company = Company(
        ticker=ticker, name=ticker, exchange="NASDAQ", currency="USD",
        sector="S", industry="I", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[],
        factor_tags=[], domicile_country=country,
    )
    db.add(company)
    db.commit()
    return company


def _fx(db: Session, quote: str, rate_date: date, rate: str) -> None:
    db.add(FXRate(
        base_currency="EUR", quote_currency=quote,
        rate=Decimal(rate), rate_date=rate_date, source="test",
    ))
    db.commit()


def _tx(db, company, day, action, qty, price, currency="USD", fees="0"):
    db.add(Transaction(
        company_id=company.id, trade_date=day, action=action,
        quantity=Decimal(str(qty)), price=Decimal(str(price)),
        fees=Decimal(str(fees)), currency=currency,
    ))
    db.commit()


# --- Escala del ahorro ------------------------------------------------------

def test_savings_tax_2025_brackets():
    # 19% primeros 6.000 + 21% hasta 50.000: 6.000*0.19 + 4.000*0.21
    assert calculate_savings_tax(Decimal("10000"), 2025) == Decimal("1980.00")
    # Tramo >300.000 al 30% (Ley 7/2024), no 28%:
    # 1.140 + 9.240 + 34.500 + 27.000 + 100.000*0.30 = 101.880
    assert calculate_savings_tax(Decimal("400000"), 2025) == Decimal("101880.00")


def test_savings_tax_historical_scales():
    # 2023-2024: tramo >300.000 al 28%
    assert calculate_savings_tax(Decimal("400000"), 2024) == Decimal("99880.00")
    # 2021-2022: 19/21/23/26
    assert calculate_savings_tax(Decimal("400000"), 2022) == Decimal("96880.00")


def test_savings_tax_zero_or_negative():
    assert calculate_savings_tax(Decimal("0"), 2025) == Decimal("0")
    assert calculate_savings_tax(Decimal("-100"), 2025) == Decimal("0")


# --- Casillas Modelo 100 ----------------------------------------------------

def _sale(ticker, date_s, proceeds, cost, gain):
    return {
        "ticker": ticker,
        "currency": "USD",
        "sales": [{
            "date": date_s,
            "proceeds_base": proceeds,
            "cost_base": cost,
            "gain_base": gain,
        }],
    }


def test_casillas_gains_losses_split():
    realized = [
        _sale("WIN", "2025-03-01", 1500.0, 1000.0, 500.0),
        _sale("LOSE", "2025-04-01", 600.0, 1000.0, -400.0),
    ]
    casillas = build_casillas([], realized, 2025)
    block = casillas["acciones_negociadas"]
    assert casillas["available"] is True
    assert casillas["basis"] == CASILLAS_BASIS
    assert block["0328_transmision_global"] == 2100.0
    assert block["0331_adquisicion_global"] == 2000.0
    assert block["0339_suma_ganancias"] == 500.0
    assert block["0340_suma_perdidas"] == 400.0
    assert block["incomplete"] is False
    assert len(block["rows"]) == 2


def test_casillas_totals_are_the_sum_of_the_rows_in_cents():
    """Modelo 100 (Renta 2025, Orden HAC/277/2026), página 14 III: each
    transmission is keyed in Renta Web in euros with two decimals and the
    program adds those rows into 0328/0331/0339/0340. The totals must be
    the sum of the ROUNDED rows, or the report disagrees with Renta Web.
    Hand example: three sales of 10,004 € proceeds / 5,004 € cost / 5,000 €
    gain -> each row 10,00 / 5,00 / 5,00; totals 30,00 / 15,00 / 15,00
    (summing the raw amounts gave 30,01 / 15,01)."""
    realized = [
        _sale("A", "2025-03-01", 10.004, 5.004, 5.0),
        _sale("B", "2025-03-02", 10.004, 5.004, 5.0),
        _sale("C", "2025-03-03", 10.004, 5.004, 5.0),
    ]
    block = build_casillas([], realized, 2025)["acciones_negociadas"]
    assert [r["transmission_base"] for r in block["rows"]] == [10.0, 10.0, 10.0]
    assert block["0328_transmision_global"] == 30.0
    assert block["0331_adquisicion_global"] == 15.0
    assert block["0339_suma_ganancias"] == 15.0
    # Losses too: three -0,005 € rows round to -0,01 each -> 0,03.
    losses = [_sale(t, "2025-04-01", 1.0, 1.005, -0.005) for t in ("D", "E", "F")]
    assert build_casillas([], losses, 2025)["acciones_negociadas"]["0340_suma_perdidas"] == 0.03


def test_casillas_missing_fx_marks_incomplete_and_nulls_totals():
    realized = [_sale("NOFX", "2025-03-01", None, None, None)]
    casillas = build_casillas([], realized, 2025)
    block = casillas["acciones_negociadas"]
    assert block["incomplete"] is True
    assert block["0328_transmision_global"] is None
    assert block["0339_suma_ganancias"] is None
    # La fila sigue visible con Nones honestos.
    assert block["rows"][0]["gain_base"] is None


def test_casillas_unavailable_for_unverified_year():
    casillas = build_casillas([], [], 2024)
    assert casillas["available"] is False
    assert "2025" in casillas["unavailable_reason"]


def test_casillas_dividends_box_0029():
    dividends = [{
        "ticker": "AAPL", "dividends_base": 90.0, "withholding_base": 13.5,
        "missing_fx": False,
    }]
    casillas = build_casillas(dividends, [], 2025)
    assert casillas["dividendos"]["0029_ingresos_integros"] == 90.0


# --- Doble imposición (art. 80 LIRPF, casilla 0588) --------------------------

def test_double_taxation_us_treaty_cap_15pct():
    # Retenido 30% (sin W-8BEN): tope de convenio 15%, exceso reclamable en
    # origen. Sin TME de la declaración completa la deducción NO se publica.
    dividends = [{
        "ticker": "AAPL", "dividends_base": 100.0, "withholding_base": 30.0,
        "missing_fx": False, "payments": [],
    }]
    result = build_double_taxation(dividends, {"AAPL": "US"}, 2025)
    us = result["countries"][0]
    assert us["treaty_cap_base"] == 15.0            # tope convenio
    assert us["excess_reclaimable_base"] == 15.0    # a reclamar en origen
    assert us["deduction_base"] is None
    assert us["status"] == "pendiente_tme"
    assert us["treaty_rate_source"].startswith("BOE-A-1990-30940")
    assert result["excess_withholding_reclaimable"] is True
    assert result["total_deduction_base"] is None
    assert result["status"] == "pendiente_tme"


def test_double_taxation_treaty_cap_is_per_dividend_not_per_country():
    """Tope del convenio por DIVIDENDO (art. 10.2.b convenio España-EE.UU.,
    BOE-A-1990-30940; art. 80.1.a LIRPF), no por país.

    A mano: AAPL bruto 1.000 con 300 retenidos (30 %, sin W-8BEN) y KO bruto
    500 con 50 retenidos (10 %), TME 20 %.
      Tope por dividendo: min(300, 150) + min(50, 75) = 150 + 50 = 200.
      Cuota española: 1.500 × 20 % = 300 → deducción = min(200, 300) = 200.
    Agrupando por país saldría min(350, 1.500 × 15 % = 225) = 225: la
    retención baja de KO "hacía hueco" al exceso de AAPL (25 € de más).
    """
    dividends = [
        {"ticker": "AAPL", "dividends_base": 1000.0, "withholding_base": 300.0,
         "missing_fx": False, "payments": []},
        {"ticker": "KO", "dividends_base": 500.0, "withholding_base": 50.0,
         "missing_fx": False, "payments": []},
    ]
    result = build_double_taxation(
        dividends, {"AAPL": "US", "KO": "US"}, 2025, tme=Decimal("0.20"))
    us = result["countries"][0]
    assert us["treaty_cap_base"] == 200.0
    assert us["deduction_base"] == 200.0
    assert us["excess_reclaimable_base"] == 150.0   # 350 retenidos − 200
    assert result["total_deduction_base"] == 200.0


def _div(day, amount):
    return {"date": day, "type": "dividend", "raw_action": "Dividend",
            "amount_native": amount, "amount_base": amount}


def _wht(day, amount):
    return {"date": day, "type": "withholding", "raw_action": "Withholding Tax",
            "amount_native": amount, "amount_base": amount}


def test_double_taxation_treaty_cap_per_payment_within_one_ticker():
    """Dentro de un mismo valor, cada pago tiene su propio tope.

    A mano: dos dividendos de 100. El primero con 30 retenidos (30 %, antes de
    entregar el W-8BEN) y el segundo con 10 (10 %).
      Por dividendo: min(30, 15) + min(10, 15) = 15 + 10 = 25.
      Por valor (suma): min(40, 200 × 15 % = 30) = 30 → 5 € de más.
    """
    dividends = [{
        "ticker": "MSFT", "dividends_base": 200.0, "withholding_base": 40.0,
        "missing_fx": False,
        "payments": [_div("2025-03-13", 100.0), _wht("2025-03-13", 30.0),
                     _div("2025-06-12", 100.0), _wht("2025-06-12", 10.0)],
    }]
    result = build_double_taxation(dividends, {"MSFT": "US"}, 2025)
    us = result["countries"][0]
    assert us["treaty_cap_base"] == 25.0
    assert us["excess_reclaimable_base"] == 15.0


def test_double_taxation_late_withholding_row_goes_to_previous_dividend():
    """Una retención registrada al día siguiente se imputa al dividendo
    anterior más cercano: 100 de bruto con 15 retenidos → tope 15 (no 0)."""
    dividends = [{
        "ticker": "JNJ", "dividends_base": 100.0, "withholding_base": 15.0,
        "missing_fx": False,
        "payments": [_div("2025-03-11", 100.0), _wht("2025-03-12", 15.0)],
    }]
    result = build_double_taxation(dividends, {"JNJ": "US"}, 2025)
    assert result["countries"][0]["treaty_cap_base"] == 15.0


def test_double_taxation_with_manual_tme_computes_deduction():
    # Con TME del borrador (entrada manual): deducción = min(tope, bruto×TME).
    dividends = [{
        "ticker": "MSFT", "dividends_base": 100.0, "withholding_base": 15.0,
        "missing_fx": False, "payments": [],
    }]
    # TME 19%: cuota española 19 > tope 15 → deducción = 15
    result = build_double_taxation(dividends, {"MSFT": "US"}, 2025, tme=Decimal("0.19"))
    assert result["countries"][0]["deduction_base"] == 15.0
    assert result["total_deduction_base"] == 15.0
    assert result["status"] == "calculada_con_tme_manual"
    assert result["partial"] is False
    # TME 10%: cuota española 10 < tope 15 → deducción = 10
    result = build_double_taxation(dividends, {"MSFT": "US"}, 2025, tme=Decimal("0.10"))
    assert result["countries"][0]["deduction_base"] == 10.0


def test_double_taxation_country_without_verified_treaty_is_manual_review():
    dividends = [{
        "ticker": "KRZ", "dividends_base": 100.0, "withholding_base": 25.0,
        "missing_fx": False, "payments": [],
    }]
    # Irlanda: tipo no fijado por el texto del convenio (BOE-A-1994-28597
    # art. 10.1.b/c) -> sigue en revisión manual. (NL ya está verificado.)
    result = build_double_taxation(dividends, {"KRZ": "IE"}, 2025)
    assert result["countries"] == []
    assert result["manual_review"][0]["ticker"] == "KRZ"
    assert "convenio" in result["manual_review"][0]["reason"]
    assert result["partial"] is True
    assert result["total_deduction_base"] is None


def test_double_taxation_special_payment_types_are_manual_review():
    dividends = [{
        "ticker": "XYZ", "dividends_base": 50.0, "withholding_base": 7.5,
        "missing_fx": False,
        "payments": [
            {"type": "dividend", "raw_action": "Payment In Lieu Of Dividends",
             "date": "2025-03-01", "amount_native": 50.0, "amount_base": 50.0},
        ],
    }]
    result = build_double_taxation(dividends, {"XYZ": "US"}, 2025)
    assert result["countries"] == []
    assert result["manual_review"][0]["ticker"] == "XYZ"
    assert "especial" in result["manual_review"][0]["reason"]
    assert result["partial"] is True


def test_double_taxation_spanish_withholding_goes_to_0597_not_0588():
    dividends = [{
        "ticker": "IBE", "dividends_base": 100.0, "withholding_base": 19.0,
        "missing_fx": False, "payments": [],
    }]
    result = build_double_taxation(dividends, {"IBE": "ES"}, 2025)
    assert result["countries"] == []                 # ES nunca es crédito 0588
    assert result["total_deduction_base"] is None    # sin TME no hay total
    assert result["spanish_withholding_base"]["casilla"] == "0597"
    assert result["spanish_withholding_base"]["amount"] == 19.0


def test_double_taxation_unknown_country_is_manual_review():
    dividends = [{
        "ticker": "XYZ", "dividends_base": 50.0, "withholding_base": 7.5,
        "missing_fx": False, "payments": [],
    }]
    result = build_double_taxation(dividends, {}, 2025)   # sin domicilio
    assert result["total_deduction_base"] is None
    assert result["manual_review"][0]["ticker"] == "XYZ"
    assert "desconocido" in result["manual_review"][0]["reason"]
    assert result["partial"] is True


def test_double_taxation_missing_fx_is_manual_review():
    dividends = [{
        "ticker": "NOFX", "dividends_base": None, "withholding_base": None,
        "missing_fx": True, "payments": [],
    }]
    result = build_double_taxation(dividends, {"NOFX": "US"}, 2025)
    assert result["manual_review"][0]["ticker"] == "NOFX"
    assert result["total_deduction_base"] is None
    assert result["partial"] is True


# --- Integración con el informe ---------------------------------------------

def test_compute_report_attaches_filing_layer(db):
    _eur_portfolio(db)
    aapl = _company(db, "AAPL", country="US")
    pay_day = date(2025, 5, 15)
    _fx(db, "USD", pay_day, "0.90")
    _tx(db, aapl, pay_day, "dividend", 0, 100)     # bruto 100 USD
    _tx(db, aapl, pay_day, "withholding", 0, 15)   # retención 15 USD
    _tx(db, aapl, date(2025, 1, 10), "buy", 10, 100, currency="EUR")
    _tx(db, aapl, date(2025, 6, 1), "sell", 10, 150, currency="EUR")  # +500 EUR

    report = TaxReportService().compute_report(db, 2025)
    filing = report["filing"]
    casillas = filing["casillas"]
    assert casillas["available"] is True
    assert casillas["basis"] == "orden-hac-277-2026-renta-2025"
    block = casillas["acciones_negociadas"]
    assert block["0328_transmision_global"] == 1500.0
    assert block["0331_adquisicion_global"] == 1000.0
    assert block["0339_suma_ganancias"] == 500.0
    assert block["0340_suma_perdidas"] == 0.0
    assert casillas["dividendos"]["0029_ingresos_integros"] == pytest.approx(90.0)

    dt = filing["double_taxation"]
    assert dt["casilla"] == "0588"
    assert dt["countries"][0]["country"] == "US"
    # Sin TME del borrador no hay deducción publicada: solo el tope de
    # convenio (13,5 retenidos < 15% de 90 = 13,5 → tope = retenido).
    assert dt["countries"][0]["treaty_cap_base"] == pytest.approx(13.5)
    assert dt["countries"][0]["deduction_base"] is None
    assert dt["status"] == "pendiente_tme"
    assert dt["total_deduction_base"] is None
    assert filing["available"] is True


def test_irpf_in_eur_even_when_portfolio_base_is_usd(db):
    # La divisa base es una preferencia de visualizacion: con la cartera en
    # USD el IRPF se sigue calculando en EUR al tipo BCE de cada operacion, y
    # las casillas no se bloquean por la divisa base.
    db.add(Portfolio(name="Main", base_currency="USD", is_default=True))
    db.commit()
    c = _company(db, "AAPL", country="US")
    _tx(db, c, date(2025, 1, 10), "buy", 10, 100, currency="USD")
    _tx(db, c, date(2025, 6, 1), "sell", 10, 150, currency="USD")

    report = TaxReportService().compute_report(db, 2025)
    assert report["summary"]["base_currency"] == "EUR"
    filing = report["filing"]
    assert "divisa base" not in (filing.get("reason") or "")


# --- Integración importación IBKR → informe: pagos especiales (fail-closed) --

PIL_XML = """<?xml version="1.0" encoding="UTF-8"?>
<FlexQueryResponse queryName="test">
  <FlexStatements>
    <FlexStatement accountId="U123456">
      <OpenPosition symbol="AAPL" position="10" markPrice="180" positionValue="1800" costBasisPrice="150" currency="USD" reportDate="2025-12-31"/>
      <CashTransaction type="Payment In Lieu Of Dividends" symbol="AAPL" trxID="PL1" amount="90" dateTime="2025-03-15" currency="USD"/>
      <CashTransaction type="Return Of Capital" symbol="AAPL" trxID="RC1" amount="10" dateTime="2025-04-15" currency="USD"/>
      <CashTransaction type="Dividends" symbol="AAPL" trxID="D1" amount="50" dateTime="2025-05-15" currency="USD"/>
    </FlexStatement>
  </FlexStatements>
</FlexQueryResponse>"""


def test_import_special_payments_fail_closed(db):
    # Ruta real: Flex XML → importador → informe. El detector debe ver el
    # type ORIGINAL de IBKR (raw_payload), no la acción normalizada.
    from app.services.ibkr_import_service import IBKRImportService

    _eur_portfolio(db)
    IBKRImportService().import_flex_xml(db, PIL_XML)
    _fx(db, "USD", date(2025, 3, 15), "0.9")
    _fx(db, "USD", date(2025, 4, 15), "0.9")
    _fx(db, "USD", date(2025, 5, 15), "0.9")

    report = TaxReportService().compute_report(db, 2025)
    filing = report["filing"]
    assert filing["available"] is True

    dt = filing["double_taxation"]
    review = [m for m in dt["manual_review"] if m["ticker"] == "AAPL"]
    assert review, "el bloque AAPL debe caer en revisión manual"
    assert "lieu" in review[0]["reason"]
    assert "return of capital" in review[0]["reason"]
    # Nada de deducción automática para un bloque con pagos especiales.
    assert dt["countries"] == []

    # La 0029 solo recoge el dividendo ordinario (50 × 0,9 = 45): los pagos
    # especiales no son ingresos íntegros de dividendos y se listan aparte.
    casillas = filing["casillas"]
    assert casillas["dividendos"]["0029_ingresos_integros"] == 45.0
    assert casillas["dividendos"]["special_payment_tickers"] == ["AAPL"]

    # Y el pago ordinario conserva el tipo original en el rastro.
    bucket = next(b for b in report["dividends"] if b["ticker"] == "AAPL")
    raw_types = sorted(p["raw_action"] for p in bucket["payments"])
    assert raw_types == [
        "Dividends", "Payment In Lieu Of Dividends", "Return Of Capital"
    ]
    assert len(bucket["special_payments"]) == 2
    assert bucket["dividends_base"] == pytest.approx(45.0)
# --- Compensación de pérdidas de ejercicios anteriores (art. 49 LIRPF) ------

from app.services.tax_irpf_filing import build_loss_compensation  # noqa: E402


def test_loss_compensation_same_category_first():
    # Pérdida 2024 (-400) contra ganancia 2025 (+500): se integra entera en
    # la 0442; no queda resto ni arrastre.
    result = build_loss_compensation(
        [{"year": 2024, "net_gyp_base": -400.0, "incomplete": False}],
        Decimal("500"), Decimal("0"), 2025,
    )
    item = result["prior_losses"][0]
    # Derivado del libro (sin anexo C.3 declarado): estimativo, sin casillas.
    assert result["estimativo"] is True
    assert item["source"] == "libro-estimativo"
    assert item["casilla_integracion"] is None
    assert "anexo C.3" in result["estimativo_reason"]
    assert item["applied_to_gains_base"] == 400.0
    assert item["applied_to_income_base"] == 0.0
    assert item["remaining_base"] == 0.0
    assert result["applied_to_gains_total_base"] == 400.0
    assert result["remaining_to_carry_base"] == 0.0


def test_loss_compensation_cross_25pct_limit():
    # Pérdida 2023 (-1000), ganancia 2025 de solo 100: 900 de resto; con 200
    # de dividendos el límite cruzado es 50 → se aplican 50 y arrastran 850.
    result = build_loss_compensation(
        [{"year": 2023, "net_gyp_base": -1000.0, "incomplete": False}],
        Decimal("100"), Decimal("200"), 2025,
    )
    item = result["prior_losses"][0]
    assert item["casilla_integracion"] is None  # estimativo (libro)
    assert item["casilla_resto"] is None
    assert item["applied_to_gains_base"] == 100.0
    assert result["cross_limit_base"] == 50.0
    assert result["cross_used_by_current_year_base"] == 0.0
    assert item["applied_to_income_base"] == 50.0
    assert item["remaining_base"] == 850.0
    assert result["remaining_to_carry_base"] == 850.0


def test_loss_compensation_oldest_year_first():
    result = build_loss_compensation(
        [
            {"year": 2024, "net_gyp_base": -100.0, "incomplete": False},
            {"year": 2022, "net_gyp_base": -100.0, "incomplete": False},
        ],
        Decimal("150"), Decimal("0"), 2025,
    )
    y2022, y2024 = result["prior_losses"]
    assert y2022["applied_to_gains_base"] == 100.0   # el más antiguo se agota antes
    assert y2024["applied_to_gains_base"] == 50.0
    assert y2024["remaining_base"] == 50.0


def test_loss_compensation_window_is_four_years():
    # 2020 queda fuera de la ventana para la Renta 2025 (expirada).
    result = build_loss_compensation(
        [{"year": 2020, "net_gyp_base": -999.0, "incomplete": False}],
        Decimal("500"), Decimal("0"), 2025,
    )
    assert result["prior_losses"] == []
    assert result["applied_to_gains_total_base"] == 0.0


def test_loss_compensation_incomplete_prior_year_excluded():
    result = build_loss_compensation(
        [{"year": 2024, "net_gyp_base": None, "incomplete": True}],
        Decimal("500"), Decimal("0"), 2025,
    )
    assert result["prior_losses"] == []
    assert result["excluded_years"][0]["year"] == 2024
    assert result["applied_to_gains_total_base"] == 0.0


def test_loss_compensation_no_casillas_outside_2025():
    result = build_loss_compensation(
        [{"year": 2023, "net_gyp_base": -100.0, "incomplete": False}],
        Decimal("500"), Decimal("0"), 2024,
    )
    assert result["prior_losses"][0]["casilla_integracion"] is None
    assert "orden-hac" not in result["basis"]


def test_compute_report_loss_compensation_end_to_end(db):
    _eur_portfolio(db)
    c = _company(db, "OLD", country="ES")
    # 2024: pérdida computable de 400 (sin recompra en ±2 meses).
    _tx(db, c, date(2024, 2, 10), "buy", 10, 100, currency="EUR")
    _tx(db, c, date(2024, 6, 1), "sell", 10, 60, currency="EUR")
    # 2025: ganancia de 500.
    _tx(db, c, date(2025, 3, 10), "buy", 10, 100, currency="EUR")
    _tx(db, c, date(2025, 9, 1), "sell", 10, 150, currency="EUR")

    report = TaxReportService().compute_report(db, 2025)
    comp = report["filing"]["loss_compensation"]
    assert comp["basis"] == "art-49-lirpf"
    assert comp["estimativo"] is True
    assert comp["prior_losses"][0]["year"] == 2024
    assert comp["prior_losses"][0]["applied_to_gains_base"] == 400.0
    assert comp["prior_losses"][0]["casilla_integracion"] is None
    assert comp["applied_to_gains_total_base"] == 400.0
    assert comp["remaining_to_carry_base"] == 0.0
    # Y el informe de 2024 en sí sigue limpio (sin filing recursivo roto).
    report_2024 = TaxReportService().compute_report(db, 2024)
    assert report_2024["summary"]["total_realized_gain_base"] == -400.0


def test_loss_compensation_declared_pending_publishes_casillas():
    # Con los saldos del anexo C.3 declarados, la fuente es autoritativa y
    # se publican las casillas del anexo (Renta 2025).
    result = build_loss_compensation(
        [{"year": 2024, "net_gyp_base": -400.0, "incomplete": False}],
        Decimal("500"), Decimal("0"), 2025,
        declared_pending={2024: Decimal("250")},
    )
    assert result["estimativo"] is False
    assert result["basis"] == "art-49-lirpf+orden-hac-277-2026"
    item = result["prior_losses"][0]
    assert item["source"] == "anexo-c3-manual"
    assert item["pending_start_base"] == 250.0
    assert item["applied_to_gains_base"] == 250.0
    assert item["remaining_base"] == 0.0
    assert item["casilla_integracion"] == "0442"


def test_loss_compensation_joint_25_limit_reserves_current_year():
    # Ejemplo del dictamen: GyP 2025 = -100, dividendos 400, saldo previo
    # 500. El límite del 25% (100) es CONJUNTO: la pérdida del propio
    # ejercicio (0446) consume los 100 y el arrastre no cruza nada.
    result = build_loss_compensation(
        [{"year": 2024, "net_gyp_base": -500.0, "incomplete": False}],
        Decimal("-100"), Decimal("400"), 2025,
    )
    assert result["cross_limit_base"] == 100.0
    assert result["cross_used_by_current_year_base"] == 100.0
    assert result["current_year_cross"]["negative_gyp_base"] == 100.0
    assert result["current_year_cross"]["applied_to_income_base"] == 100.0
    assert result["current_year_cross"]["casilla"] == "0446"
    assert result["applied_to_gains_total_base"] == 0.0
    assert result["applied_to_income_total_base"] == 0.0
    assert result["remaining_to_carry_base"] == 500.0


def _seed_loss_then_gain(db, portfolio_kwargs=None):
    """Pérdida computable en 2024 (-400) y ganancia en 2025 (+500)."""
    if portfolio_kwargs is None:
        _eur_portfolio(db)
    else:
        db.add(Portfolio(name="Main", base_currency="EUR", is_default=True, **portfolio_kwargs))
        db.commit()
    c = _company(db, "OLD", country="ES")
    _tx(db, c, date(2024, 2, 10), "buy", 10, 100, currency="EUR")
    _tx(db, c, date(2024, 6, 1), "sell", 10, 60, currency="EUR")
    _tx(db, c, date(2025, 3, 10), "buy", 10, 100, currency="EUR")
    _tx(db, c, date(2025, 9, 1), "sell", 10, 150, currency="EUR")


def test_declared_pending_from_tenant_metadata_publishes_casillas(db):
    # Los saldos declarados (anexo C.3) viven en la metadata del TENANT:
    # son datos fiscales personales, nunca configuración global del proceso.
    tenant = Tenant(external_id="t-fiscal", name="Fiscal")
    db.add(tenant)
    db.flush()
    db.info["tenant_id"] = tenant.id  # contexto de escritura del tenant
    _seed_loss_then_gain(db, portfolio_kwargs={"tenant_id": tenant.id})
    tenant.metadata_ = {"tax_prior_losses_pending": {"2024": "250"}}
    db.commit()

    report = TaxReportService().compute_report(db, 2025)
    comp = report["filing"]["loss_compensation"]
    assert comp["estimativo"] is False
    prior = comp["prior_losses"][0]
    assert prior["source"] == "anexo-c3-manual"
    assert prior["pending_start_base"] == 250.0
    assert prior["applied_to_gains_base"] == 250.0
    assert prior["casilla_integracion"] == "0442"


def test_declared_pending_from_other_tenant_does_not_leak(db):
    # Otro tenant con saldos declarados NO contamina la declaración del
    # tenant activo (aislamiento multiusuario).
    other = Tenant(
        external_id="t-otro",
        name="Otro",
        metadata_={"tax_prior_losses_pending": {"2024": "999"}},
    )
    db.add(other)
    db.commit()
    _seed_loss_then_gain(db)  # portfolio del tenant activo, sin metadata

    report = TaxReportService().compute_report(db, 2025)
    comp = report["filing"]["loss_compensation"]
    assert comp["estimativo"] is True
    assert comp["prior_losses"][0]["casilla_integracion"] is None
    # El saldo es el del libro (-400), no los 999 declarados por otro tenant.
    assert comp["prior_losses"][0]["pending_start_base"] == 400.0

# Integración del TME manual desde la pestaña Impuestos.
def test_manual_tme_preview_is_read_only_and_not_reused(db):
    _eur_portfolio(db)
    company = _company(db, 'TME', 'US')
    _tx(db, company, date(2025, 5, 15), 'dividend', 0, 100, currency='EUR')
    _tx(db, company, date(2025, 5, 15), 'withholding', 0, 15, currency='EUR')
    from sqlalchemy import select

    from app.models.entities import TaxReport
    service = TaxReportService()
    preview = service.get_report(db, 2025, tme=Decimal('0.10'))
    assert preview['filing']['tme_percent_manual'] == 10
    assert preview['filing']['double_taxation']['total_deduction_base'] == 10
    assert db.scalars(select(TaxReport)).all() == []
    normal = service.get_report(db, 2025)
    assert normal['filing']['tme_percent_manual'] is None
    assert normal['filing']['double_taxation']['total_deduction_base'] is None
    assert normal['filing']['double_taxation']['status'] == 'pendiente_tme'


@pytest.mark.parametrize('value', ['-0.01', '100.01', 'NaN', 'Infinity', '19.123'])
def test_preview_rejects_invalid_tme(value):
    from pydantic import ValidationError

    from app.api.routes.taxes import FilingPreviewInput
    with pytest.raises(ValidationError):
        FilingPreviewInput(tme_percent=value)


def test_preview_endpoint_accepts_zero_and_validates_year(db):
    from fastapi import HTTPException

    from app.api.routes.taxes import FilingPreviewInput, preview_tax_filing
    _eur_portfolio(db)
    result = preview_tax_filing(2025, FilingPreviewInput(tme_percent='0'), db)
    assert result['filing']['tme_percent_manual'] == 0
    assert result['filing']['double_taxation']['total_deduction_base'] == 0
    with pytest.raises(HTTPException) as exc:
        preview_tax_filing(1999, FilingPreviewInput(tme_percent='19'), db)
    assert exc.value.status_code == 400


def test_manual_tme_does_not_publish_partial_total(db):
    _eur_portfolio(db)
    unknown = _company(db, 'UNKNOWN', None)
    _tx(db, unknown, date(2025, 5, 15), 'dividend', 0, 100, currency='EUR')
    _tx(db, unknown, date(2025, 5, 15), 'withholding', 0, 15, currency='EUR')
    result = TaxReportService().get_report(db, 2025, tme=Decimal('0.19'))
    assert result['filing']['double_taxation']['partial'] is True
    assert result['filing']['double_taxation']['total_deduction_base'] is None


def _es_bucket(**over):
    base = {
        "ticker": "SAN",
        "dividends_base": Decimal("100"),
        "withholding_base": Decimal("19"),
        "missing_fx": False,
        "ambiguous_cash": False,
        "payments": [],
    }
    base.update(over)
    return base


def test_0597_is_null_when_spanish_withholding_is_incomplete():
    for bucket in (
        _es_bucket(withholding_base=None, missing_fx=True),
        _es_bucket(dividends_base=None, missing_fx=True),
        _es_bucket(withholding_base=None),
    ):
        out = build_double_taxation([bucket], {"SAN": "ES"}, 2025)
        base = out["spanish_withholding_base"]
        assert base["amount"] is None and base["status"] == "SIN_DATOS"


def test_0597_is_published_when_spanish_withholding_is_complete():
    out = build_double_taxation([_es_bucket()], {"SAN": "ES"}, 2025)
    base = out["spanish_withholding_base"]
    assert base["amount"] == 19.0 and base["status"] == "calculada"


def test_0597_ignores_incomplete_foreign_buckets():
    foreign = _es_bucket(ticker="NESN", withholding_base=None, missing_fx=True)
    out = build_double_taxation([_es_bucket(), foreign], {"SAN": "ES", "NESN": "CH"}, 2025)
    assert out["spanish_withholding_base"]["amount"] == 19.0


def test_casillas_over_sell_row_is_nd_not_computable():
    """Venta sin compras que la cubran: la base de adquisición no se conoce,
    así que la fila da N/D en adquisición y resultado (nunca el importe con
    coste cero inventado) y las globales quedan anuladas."""
    sale = _sale("OVS", "2025-03-01", 600.0, 0.0, 600.0)
    sale["sales"][0]["over_sell"] = True
    block = build_casillas([], [sale], 2025)["acciones_negociadas"]
    assert block["incomplete"] is True
    assert block["0328_transmision_global"] is None
    assert block["0331_adquisicion_global"] is None
    assert block["0339_suma_ganancias"] is None
    row = block["rows"][0]
    assert row["transmission_base"] == 600.0  # transmisión observada
    assert row["acquisition_base"] is None
    assert row["gain_base"] is None
    assert row["over_sell"] is True


def test_casillas_over_sell_does_not_hide_other_rows():
    realized = [
        _sale("WIN", "2025-03-01", 1500.0, 1000.0, 500.0),
        _sale("OVS", "2025-04-01", 600.0, 0.0, 600.0),
    ]
    realized[1]["sales"][0]["over_sell"] = True
    block = build_casillas([], realized, 2025)["acciones_negociadas"]
    assert block["incomplete"] is True
    win, ovs = block["rows"]
    assert win["gain_base"] == 500.0 and win["over_sell"] is False
    assert ovs["gain_base"] is None and ovs["over_sell"] is True
