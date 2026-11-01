"""Ramas de la venta hipotética del Cerebro (IRPF con lotes del usuario) sin test.

Solo tests: números con formato español, fechas en todos sus formatos (y las
imposibles), lotes descartados, precio de venta inválido, «la mitad», sin
cotización y los tres huecos de tipo de cambio que deben bloquear la cuota.
"""
from datetime import date
from decimal import Decimal as D

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, FXRate, MarketPrice
from app.services.sale_hypothetical import (
    HypoLot,
    parse_number,
    parse_purchase_lots,
    parse_sale_price,
    simulate_hypothetical_sale,
)

TODAY = date(2026, 10, 27)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = 1
        yield session
    engine.dispose()


def _company(db, ticker="TEST", currency="EUR"):
    company = Company(ticker=ticker, name="Synthetic", exchange="XETRA", currency=currency,
                      company_type="holding", valuation_model="unassigned")
    db.add(company)
    db.flush()
    return company


def _fx(db, day, rate, quote="USD"):
    db.add(FXRate(base_currency="EUR", quote_currency=quote, rate_date=day, rate=D(rate), source="test"))
    db.flush()


@pytest.mark.parametrize(("raw", "expected"), [
    ("1.234,5", D("1234.5")),
    ("150,5", D("150.5")),
    ("1.500", D("1500")),
    ("1.234.567", D("1234567")),
    ("150.25", D("150.25")),
    ("abc", None),
    ("", None),
])
def test_parse_number_formato_espanol(raw, expected):
    assert parse_number(raw) == expected


@pytest.mark.parametrize(("text", "expected", "approx"), [
    ("compré 10 a 150 $ el 3/4/2024", date(2024, 4, 3), False),
    ("compré 10 a 150 $ el 2024-04-03", date(2024, 4, 3), False),
    ("compré 10 a 150 $ en marzo de 2024", date(2024, 3, 1), True),
    ("compré 10 a 150 $ el 5 de enero de 2023", date(2023, 1, 5), False),
])
def test_fechas_de_compra_en_todos_los_formatos(text, expected, approx):
    [lot] = parse_purchase_lots(text)
    assert lot.trade_date == expected
    assert lot.approx_date is approx
    assert lot.currency == "USD"


@pytest.mark.parametrize("text", [
    "compré 10 a 150 $ el 31 de febrero de 2024",
    "compré 10 a 150 $ el 32/13/2024",
])
def test_una_fecha_imposible_queda_sin_fecha_no_se_inventa(text):
    [lot] = parse_purchase_lots(text)
    assert lot.trade_date is None


def test_lotes_con_cantidad_cero_se_descartan_y_los_demas_conservan_formato():
    assert parse_purchase_lots("tengo 0 acciones a 150 €") == []
    lots = parse_purchase_lots(
        "compré 10 acciones a 1.234,50 € el 5 de enero de 2023 y otras 5 a 1.300 € el 1/2/2024"
    )
    assert [(lot.quantity, lot.price, lot.currency, lot.trade_date) for lot in lots] == [
        (D("10"), D("1234.50"), "EUR", date(2023, 1, 5)),
        (D("5"), D("1300"), "EUR", date(2024, 2, 1)),
    ]


def test_precio_de_venta_cero_no_es_un_precio():
    assert parse_sale_price("vendo a 0 €") is None
    assert parse_sale_price("si vendo a 180 €") == (D("180"), "EUR")


@pytest.mark.parametrize("question", [
    "¿y si vendo la mitad a 150 €?",
    "vendo la mitad a 150 €",
    "vender la mitad a 150 euros",
    "si vendo la mitad de mis TEST a 150 €",
    "vendo mitad por 150 €",
])
def test_vender_la_mitad_a_un_precio_respeta_el_precio_del_usuario(question):
    # Antes: «vendo la mitad a 150 €» no reconocía el precio. Sin empresa el
    # Cerebro pedía un precio que el usuario ya había dado; con posición o
    # cotización usaba EN SILENCIO el precio de mercado en lugar del suyo.
    assert parse_sale_price(question) == (D("150"), "EUR")


def test_la_mitad_a_un_precio_no_se_sustituye_por_la_cotizacion(db):
    company = _company(db)
    db.add(MarketPrice(company_id=company.id, date=date(2026, 10, 10), close=D("120"), source="test"))
    db.flush()
    lots = [HypoLot(quantity=D("10"), price=D("100"), currency="EUR", trade_date=date(2024, 1, 2))]
    sale = simulate_hypothetical_sale(db, lots=lots, question="¿y si vendo la mitad a 150 €?", company=company, today=TODAY)
    assert sale.sale_price_source == "usuario"
    assert sale.sale_price == D("150")
    assert sale.quantity == D("5")
    assert sale.gain_eur == D("250")


def test_vender_la_mitad_usa_la_mitad_de_lo_comprado(db):
    lots = [HypoLot(quantity=D("10"), price=D("100"), currency="EUR", trade_date=date(2024, 1, 2))]
    sale = simulate_hypothetical_sale(db, lots=lots, question="¿y si vendo la mitad a 150 €?", company=None, today=TODAY)
    assert sale.quantity == D("5")
    assert sale.gain_eur == D("250")
    assert sale.tax_eur is not None and sale.tax_eur > 0


def test_sin_precio_ni_cotizacion_pide_el_precio_y_no_calcula(db):
    company = _company(db)
    lots = [HypoLot(quantity=D("10"), price=D("100"), currency="EUR", trade_date=date(2024, 1, 2))]
    sale = simulate_hypothetical_sale(db, lots=lots, question="¿cuánto IRPF pagaría si vendo?", company=company, today=TODAY)
    assert sale.sale_price is None
    assert sale.missing == ["el precio al que venderías"]
    assert sale.tax_eur is None


def test_sin_precio_usa_la_ultima_cotizacion_real_y_no_la_semilla(db):
    company = _company(db)
    db.add(MarketPrice(company_id=company.id, date=date(2026, 10, 20), close=D("999"), source="seed"))
    db.add(MarketPrice(company_id=company.id, date=date(2026, 10, 10), close=D("120"), source="test"))
    db.flush()
    lots = [HypoLot(quantity=D("10"), price=D("100"), currency="EUR", trade_date=date(2024, 1, 2))]
    sale = simulate_hypothetical_sale(db, lots=lots, question="¿cuánto IRPF pagaría si vendo?", company=company, today=TODAY)
    assert sale.sale_price_source == "cotización"
    assert sale.sale_price == D("120")
    assert sale.sale_price_date == date(2026, 10, 10)
    assert sale.gain_eur == D("200")


def test_lote_en_dolares_sin_fecha_se_calcula_al_cambio_de_hoy(db):
    """DGT V0152-26 (criterion of the tax report): the gain in the share's
    currency is converted at the SALE-date rate, so an undated lot sold in its
    own currency does not need a purchase-date rate: 500 $ × 0,9 = 450 €.
    The FIFO order of undated lots is still disclosed (``undated``)."""
    _fx(db, TODAY, "0.9")
    lots = [HypoLot(quantity=D("10"), price=D("100"), currency="USD", trade_date=None)]
    sale = simulate_hypothetical_sale(db, lots=lots, question="si vendo a 150 $", company=None, today=TODAY)
    assert sale.missing == []
    assert sale.undated is True
    assert sale.native_gain == D("500")
    assert sale.gain_eur == D("450")


def test_sin_tipo_de_cambio_de_la_compra_basta_el_de_la_venta(db):
    """DGT V0152-26: only the sale-date rate is needed (1.000 $ cost × 0,9)."""
    _fx(db, TODAY, "0.9")
    lots = [HypoLot(quantity=D("10"), price=D("100"), currency="USD", trade_date=date(2020, 1, 2))]
    sale = simulate_hypothetical_sale(db, lots=lots, question="si vendo a 150 $", company=None, today=TODAY)
    assert sale.missing == []
    assert sale.cost_eur == D("900")
    assert sale.gain_eur == D("450")


def test_lote_en_otra_divisa_sin_su_tipo_de_compra_no_hay_cuota(db):
    """A lot in a currency other than the sale's keeps its purchase-date rate."""
    _fx(db, TODAY, "0.9")
    lots = [HypoLot(quantity=D("10"), price=D("100"), currency="GBP", trade_date=date(2020, 1, 2))]
    sale = simulate_hypothetical_sale(db, lots=lots, question="si vendo a 150 $", company=None, today=TODAY)
    assert sale.missing == ["el tipo de cambio de la fecha de compra"]
    assert sale.tax_eur is None


def test_sin_tipo_de_cambio_de_hoy_no_hay_cuota(db):
    _fx(db, date(2024, 1, 2), "0.92")
    lots = [HypoLot(quantity=D("10"), price=D("100"), currency="USD", trade_date=date(2024, 1, 2))]
    sale = simulate_hypothetical_sale(db, lots=lots, question="si vendo a 150 $", company=None, today=TODAY)
    assert sale.missing == ["el tipo de cambio de hoy"]
    assert sale.tax_eur is None


def test_lote_en_dolares_con_tipos_de_ambos_dias_calcula_en_euros(db):
    _fx(db, date(2024, 1, 2), "0.92")
    _fx(db, TODAY, "0.90")
    lots = [HypoLot(quantity=D("10"), price=D("100"), currency="USD", trade_date=date(2024, 1, 2))]
    sale = simulate_hypothetical_sale(db, lots=lots, question="si vendo a 150 $", company=None, today=TODAY)
    assert sale.missing == []
    # DGT V0152-26: coste 1.000 $ al cambio de la venta (0,90), no al de compra (0,92).
    assert sale.cost_eur == D("900")
    assert sale.value_eur == D("1350")
    assert sale.gain_eur == D("450")
    assert sale.tax_eur is not None


def test_una_perdida_no_tiene_cuota(db):
    lots = [HypoLot(quantity=D("10"), price=D("100"), currency="EUR", trade_date=date(2024, 1, 2))]
    sale = simulate_hypothetical_sale(db, lots=lots, question="si vendo a 80 €", company=None, today=TODAY)
    assert sale.gain_eur == D("-200")
    assert sale.tax_eur is None


def test_chat_con_posicion_vender_la_mitad_a_un_precio_usa_el_precio_del_usuario(monkeypatch):
    """Ruta de la posición guardada del Cerebro: antes «vendo la mitad a 20 €» usaba
    el valor de mercado guardado (9 €/acción) en vez de los 20 € del usuario."""
    import asyncio

    import app.services.chat_service as chat
    from app.models.entities import Portfolio, Position, Transaction
    from app.services.chat_service import ChatService

    class Clock(date):
        @classmethod
        def today(cls):
            return TODAY

    class NoLLM:
        name = "no-llm"

        async def complete(self, *args, **kwargs):
            raise AssertionError("la estimación de venta no llama a ningún modelo")

    monkeypatch.setattr(chat, "date", Clock)
    monkeypatch.setattr(chat, "local_today", Clock.today)
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.info["tenant_id"] = 1
        company = _company(db)
        db.add(Portfolio(tenant_id=1, name="P", base_currency="EUR", is_default=True))
        db.add(Transaction(tenant_id=1, company_id=company.id, trade_date=date(2024, 1, 2), action="buy",
                           quantity=D("100"), price=D("10"), fees=D("0"), currency="EUR"))
        db.add(Position(tenant_id=1, company_id=company.id, quantity=D("100"), average_cost=D(10),
                        market_value=D("900"), market_value_base=D("900"), market_value_native=D("900"),
                        cost_basis_base=D("1000"), cost_basis_native=D("1000"),
                        currency="EUR", base_currency="EUR", as_of=TODAY))
        db.commit()
        response = asyncio.run(ChatService(provider=NoLLM()).answer(
            db, "¿cuánto IRPF pagaría si vendo la mitad de TEST a 20 €?", "global", None,
        ))
    engine.dispose()
    assert response.llm_trace.get("sale_price_source") == "usuario"
    # 50 acciones × (20 − 10) = 500 € de ganancia; con el valor guardado sería una pérdida.
    assert "500" in response.answer



@pytest.mark.parametrize(("question", "expected"), [
    ("¿cuánto IRPF pagaría si vendo SHEL.L a 30 £?", (D("30"), "GBP")),
    ("si vendo todo AAPL a 200 $", (D("200"), "USD")),
    ("si vendo mis acciones de TEST a 150 €", (D("150"), "EUR")),
    ("vendo todas mis acciones de TEST por 150 euros", (D("150"), "EUR")),
    ("si vendo TEST hoy a 150 €", (D("150"), "EUR")),
])
def test_vender_un_ticker_sin_cantidad_a_un_precio_respeta_el_precio(question, expected):
    # Antes el ticker solo se aceptaba detras de una cantidad («vendo 10 TEST a
    # 150 €»): «si vendo TEST a 150 €» no reconocia el precio y el IRPF del
    # chat se calculaba EN SILENCIO con la cotizacion guardada.
    assert parse_sale_price(question) == expected


def test_vender_sin_precio_sigue_sin_precio():
    assert parse_sale_price("si vendo TEST mañana a las 10") is None
    assert parse_sale_price("cuánto IRPF si vendo todo TEST") is None


def test_lote_con_mis_n_acciones_que_compre_a():
    """«si vendo mis 50 acciones de AAPL que compré a 150 $»: el lote son 50, no se pierde."""
    lots = parse_purchase_lots(
        "cuánto pagaría si vendo mis 50 acciones de AAPL que compré a 150 $ el 3 de marzo de 2024"
    )
    assert [(lot.quantity, lot.price, lot.currency, lot.trade_date) for lot in lots] == [
        (D("50"), D("150"), "USD", date(2024, 3, 3))
    ]


def test_porcentaje_de_venta_no_es_cantidad_del_lote():
    """«vendo 15 % de lo que compré a 100 €»: 15 es un porcentaje, no 15 acciones del lote."""
    assert parse_purchase_lots("si vendo 15% de las que compré a 100 € el 2 de enero de 2025") == []


@pytest.mark.parametrize(("text", "expected"), [
    ("1,234.56", D("1234.56")),
    ("12,345,678.9", D("12345678.9")),
    ("1.234,56", D("1234.56")),
    ("100.000,00", D("100000.00")),
])
def test_con_los_dos_separadores_el_ultimo_es_el_decimal(text, expected):
    """«1,234.56 $» (formato US) se leía 1,23456: el último separador es el decimal."""
    assert parse_number(text) == expected


def test_lote_con_precio_en_formato_us():
    lots = parse_purchase_lots("si vendo 10 acciones de AAPL que compré a 1,234.56 $ el 3 de marzo de 2024")
    assert [(lot.quantity, lot.price, lot.currency) for lot in lots] == [
        (D("10"), D("1234.56"), "USD")
    ]


@pytest.mark.parametrize(("text", "expected"), [
    # El precio de COMPRA no es el de venta: antes «compradas a 100 € por 90 €» vendía a 100.
    ("si vendo 10 acciones compradas a 100 € por 90 €", (D("90"), "EUR")),
    ("Si vendo 10 acciones de Apple que compré a 100 $ el 1 de junio de 2023 a 200 $", (D("200"), "USD")),
    ("si vendo 10 a 150 € las que compré a 100 €", (D("150"), "EUR")),
    ("si vendo la mitad a 150 €", (D("150"), "EUR")),
    ("si vendo 10 a 150 €", (D("150"), "EUR")),
])
def test_precio_de_venta_no_es_el_de_compra(text, expected):
    assert parse_sale_price(text) == expected


def test_sin_precio_de_venta_el_de_compra_no_cuenta():
    assert parse_sale_price("si vendo las 10 que compré a 100 €") is None


def test_el_ano_de_la_fecha_no_es_un_lote():
    """«…que compré a 100 $ el 1 de junio de 2023 a 200 $»: «2023 a 200 $» se leía
    como un lote de 2023 acciones a 200 $ (y la ganancia salía 0)."""
    lots = parse_purchase_lots(
        "Si vendo 10 acciones de Apple que compré a 100 $ el 1 de junio de 2023 a 200 $"
    )
    assert [(lot.quantity, lot.price, lot.currency, lot.trade_date) for lot in lots] == [
        (D("10"), D("100"), "USD", date(2023, 6, 1))
    ]
    lots = parse_purchase_lots("compré 5 acciones a 40 € el 3/4/2024 a 60 € si las vendo")
    assert [(lot.quantity, lot.price) for lot in lots] == [(D("5"), D("40"))]
