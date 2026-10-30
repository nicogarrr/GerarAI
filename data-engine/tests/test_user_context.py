"""Contexto personal del Cerebro: cartera, watchlist, tesis, avisos, diario y plan.

Base sembrada con los tickers reales de Nico (``tests/cerebro_seed.py``).
Las cifras esperadas están calculadas a mano en cada aserción.
"""

from __future__ import annotations

import pytest

from app.services.user_context import build_user_context, margin_of_safety, num_es
from tests.cerebro_seed import (
    NOW,
    PORTFOLIO,
    TODAY,
    WATCHLIST,
    fake_dca_reader,
    no_dca_engine,
    seeded_session,
)


@pytest.fixture
def db():
    session = seeded_session()
    yield session
    session.close()


def _ctx(db, **kw):
    kw.setdefault("today", TODAY)
    kw.setdefault("now", NOW)
    kw.setdefault("dca_reader", fake_dca_reader)
    ctx = build_user_context(db, **kw)
    assert ctx is not None
    return ctx


def test_formato_es_y_margen_de_graham():
    assert num_es(1234.5) == "1.234,50"
    # (V − P) / V con V = 400 y P = 300 → 25 %.
    assert margin_of_safety(400, 300) == pytest.approx(0.25)
    assert margin_of_safety(None, 300) is None
    assert margin_of_safety(0, 300) is None


def test_contiene_toda_la_cartera_con_peso_y_pnl(db):
    text = _ctx(db).render()
    for ticker in PORTFOLIO:
        assert f"- {ticker} (" in text
    # ASTS: 4.000 / 10.000 = 40 %; P&L 4.000 − 2.500 = +1.500 EUR (+60 %).
    assert "ASTS (AST SpaceMobile), peso 40,0 %, valor 4.000,00 EUR, P&L +1.500,00 EUR (+60,0 %)" in text
    # Total: 10.000 EUR; P&L 10.000 − 7.850 = +2.150 EUR (+27,4 %).
    assert "Valor total 10.000,00 EUR" in text
    assert "P&L latente +2.150,00 EUR (+27,4 % sobre coste)" in text
    assert "divisa base EUR" in text
    assert "SECRET" not in text


def test_watchlist_con_margen_y_nivel_dca(db):
    ctx = _ctx(db)
    text = ctx.render()
    for ticker in WATCHLIST:
        assert f"- {ticker}" in text
    # POOL: (400 − 300) / 400 = +25 %; 4X DCA.
    assert "POOL (Pool Corporation), cierre 300,00 USD (2026-10-24), valor justo 400,00 USD" in text
    assert "margen de seguridad +25,0 %, nivel DCA 4X DCA" in text
    # KKR: (160 − 120) / 160 = +25 %; AAPL: (200 − 260) / 200 = −30 %, recorte ligero.
    assert "margen de seguridad -30,0 %, nivel DCA RECORTE LIGERO" in text
    rows = {row["ticker"]: row for row in ctx.blocks["watchlist"].rows}
    assert rows["KKR"]["mos"] == pytest.approx(0.25)
    assert rows["AAPL"]["mos"] == pytest.approx(-0.30)
    # IBRX no tiene ficha: se dice, no se inventa.
    assert "IBRX: aún sin ficha en GerarAI" in text
    # CGEO.L: 4.200 sin unidad declarada en Londres (GBp o GBP): no hay
    # precio verificable, ni se rotula «4.200,00 GBP» ni hay margen.
    assert rows["CGEO.L"]["mos"] is None
    assert rows["CGEO.L"]["price"] is None
    assert "CGEO.L (Georgia Capital), precio guardado sin unidad verificable" in text
    assert "4.200,00 GBP" not in text


def test_watchlist_londres_en_peniques_se_compara_en_libras(db):
    from sqlalchemy import select

    from app.models import Company, MarketPrice

    company = db.scalar(select(Company).where(Company.ticker == "CGEO.L"))
    for price in db.scalars(select(MarketPrice).where(MarketPrice.company_id == company.id)):
        price.quote_currency = "GBp"
    db.flush()
    ctx = _ctx(db)
    text = ctx.render()
    rows = {row["ticker"]: row for row in ctx.blocks["watchlist"].rows}
    # 4.200 GBp = 42,00 GBP; valor justo 42,55 GBP -> (42,55 − 42) / 42,55 = +1,29 %.
    assert rows["CGEO.L"]["price"] == pytest.approx(42.0)
    assert rows["CGEO.L"]["mos"] == pytest.approx((42.55 - 42) / 42.55)
    assert "cierre 42,00 GBP" in text
    assert "margen de seguridad +1,3 %" in text


def test_sin_motor_dca_degrada_limpio(db):
    text = _ctx(db, dca_reader=no_dca_engine).render()
    assert "nivel DCA no disponible" in text
    assert "4X" not in text


def test_lector_dca_por_defecto_no_rompe_si_falta_el_modulo(db):
    # En main sin #2321 el módulo no existe; con él, la tabla no está migrada aquí.
    ctx = build_user_context(db, today=TODAY, now=NOW)
    assert ctx is not None
    assert "nivel DCA" in ctx.render()


def test_tesis_avisos_diario_y_plan(db):
    text = _ctx(db).render()
    assert "KKR v2: estado publicada, rating compra" in text
    assert "se invalida si: Las comisiones recurrentes caen por debajo del 60 % de los ingresos" in text
    assert "ONDS: ONDS cae un 12 % en una sesión (gravedad high" in text
    assert "1 avisos abiertos; 1 reglas de aviso activas" in text
    assert "2026-10-02 BN: compra a 55,00 USD (abierta)" in text
    assert "Aportación mensual 300,00 EUR; horizonte 20 años" in text
    assert "Ahorro futuro: simulación solo de aportaciones" in text
    assert "121.741,35 EUR en 20 años" in text
    assert "DCA reparte la cuota, no mejora esta hipótesis" in text
    assert "Asignación objetivo: POOL 50,0 %; UBER 50,0 %" in text


def test_secciones_a_la_carta_y_fiscal_solo_si_se_pide(db):
    ctx = _ctx(db, sections=["watchlist"])
    assert list(ctx.blocks) == ["watchlist"]
    assert "fiscal" not in _ctx(db).blocks
    fiscal = _ctx(db, sections=["fiscal"], fiscal_year=2025).render()
    assert "Ejercicio 2025" in fiscal


def test_acotado_en_longitud(db):
    ctx = _ctx(db)
    short = ctx.render(max_chars=600)
    assert len(short) <= 700
    assert ctx.truncated
    assert "contexto recortado" in short


def test_sin_tenant_no_hay_contexto(db):
    db.info["tenant_id"] = None
    assert build_user_context(db) is None


def test_otro_tenant_no_ve_nada_de_nico(db):
    db.info["tenant_id"] = 2
    text = _ctx(db).render()
    assert "ASTS" not in text and "POOL" not in text
    assert "SECRET" in text


def test_dated_portfolio_notice_keeps_qualifiers_in_cerebro_context(db):
    from sqlalchemy import select

    from app.models import ResearchAlert
    alert = db.scalar(select(ResearchAlert))
    alert.alert_type = 'portfolio_data_review'
    alert.title = 'Revisa la caja registrada en EUR'
    alert.message = 'Saldo -100 EUR fechado 2026-10-23. No confirma deuda ni caja disponible hoy.'
    db.commit()
    text = _ctx(db).render()
    assert 'fechado 2026-10-23' in text
    assert 'No confirma deuda ni caja disponible hoy' in text
    assert 'dato registrado, no instrucción' in text


def test_other_alert_bodies_are_not_added_to_context(db):
    from sqlalchemy import select

    from app.models import ResearchAlert
    alert = db.scalar(select(ResearchAlert))
    alert.message = 'BODY_NOT_FOR_CONTEXT'
    db.commit()
    assert 'BODY_NOT_FOR_CONTEXT' not in _ctx(db).render()


def test_plan_notice_detail_bounded(db):
    from sqlalchemy import select

    from app.models import ResearchAlert
    alert = db.scalar(select(ResearchAlert))
    alert.alert_type = 'savings_plan_review'
    alert.message = 'CURRENCY_PENDING ' + 'x' * 2000 + 'TRAILING_NOT_INCLUDED'
    db.commit()
    text = _ctx(db).render()
    assert 'CURRENCY_PENDING' in text
    assert 'TRAILING_NOT_INCLUDED' not in text
