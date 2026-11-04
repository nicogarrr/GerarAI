"""Comparables atípicos: el respaldo por múltiplos no publica cifras absurdas.

Caso real (BABA, nov-2026): sin ``peer_relationships`` el selector multifactor
rellena el grupo con empresas que solo comparten sector, divisa o tamaño, y una
mediana de PER de 369x convertía el respaldo orientativo del holding en ~3x el
precio. La regla es general (sin tickers): fuera del rango plausible de cada
múltiplo o a más de ``PEER_OUTLIER_K`` veces la mediana del grupo, el par se
descarta con su motivo; con menos de ``MIN_VALID_PEERS`` válidos no hay cifra.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Company, FinancialFact, MarketPrice, PeerRelationship
from app.models.entities import Base
from app.services import valuation_service as vs
from app.valuation.engines.relative_multiples import RelativeMultiplesEngine
from app.valuation.relative_multiples import (
    MIN_VALID_PEERS,
    MULTIPLE_KINDS,
    PEER_MULTIPLE_PLAUSIBLE_RANGE,
    PEER_OUTLIER_K,
    PeerMultiple,
    screen_peer_outliers,
)

PRICE_DAY = date(2025, 12, 31)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _company(db, ticker):
    row = Company(
        ticker=ticker, name=f"{ticker} test", exchange="TEST", currency="USD",
        sector="Technology", industry="Software", company_type="standard",
        valuation_model="standard_dcf", special_sources=[], special_risks=[],
        factor_tags=["software"],
    )
    db.add(row)
    db.flush()
    return row


def _facts(db, company, values):
    for metric, value in values.items():
        db.add(FinancialFact(
            company_id=company.id, metric=metric, value=Decimal(str(value)), unit="USD",
            period="FY2025", fiscal_year=2025, fiscal_quarter="FY", source_type="outlier_test",
            is_reported=True, confidence=Decimal("0.90"),
        ))
    db.commit()


def _price(db, company, price):
    db.add(MarketPrice(company_id=company.id, date=PRICE_DAY, close=Decimal(str(price)),
                       adj_close=Decimal(str(price)), source="outlier_test"))
    db.commit()


def _peer(db, ticker, pe):
    """Par con EPS 2: precio = PER x 2; el resto de múltiplos escala igual."""
    peer = _company(db, ticker)
    _facts(db, peer, {"eps": 2.0, "revenue": 1000.0, "free_cash_flow": 100.0, "total_debt": 200.0,
                      "cash_and_equivalents": 50.0, "shares_diluted": 100.0, "book_value": 400.0})
    _price(db, peer, pe * 2.0)
    return peer


def _subject(db, ticker="SUBJ"):
    company = _company(db, ticker)
    _facts(db, company, {"eps": 2.0, "revenue": 1000.0, "free_cash_flow": 100.0, "total_debt": 200.0,
                         "cash_and_equivalents": 50.0, "shares_diluted": 100.0, "book_value": 400.0,
                         "ebitda": 150.0})
    _price(db, company, 20.0)
    return company


def _value(db, company, price=20.0):
    engine = RelativeMultiplesEngine()
    return engine.value(engine.build_context(db, company, price))


def _pm(ticker, value, kind="pe"):
    return PeerMultiple(ticker=ticker, kind=kind, value=value, source="t", as_of="2025-12-31", method="t")


# --- la regla, sin base de datos -------------------------------------------------


def test_constantes_declaradas_para_cada_multiplo():
    assert set(PEER_MULTIPLE_PLAUSIBLE_RANGE) == set(MULTIPLE_KINDS)
    for low, high in PEER_MULTIPLE_PLAUSIBLE_RANGE.values():
        assert 0 < low < high
    assert PEER_OUTLIER_K > 1
    assert MIN_VALID_PEERS >= 3


def test_filtro_quita_fuera_de_rango_y_lejos_de_la_mediana_con_motivo():
    peers = [_pm("A", 20.0), _pm("B", 22.0), _pm("C", 25.0), _pm("D", 0.94), _pm("E", 369.0),
             _pm("F", 28.0), _pm("G", 3.0)]
    kept, rejected = screen_peer_outliers("pe", peers)
    assert [p.ticker for p in kept] == ["A", "B", "C", "F"]
    reasons = {r["ticker"]: r for r in rejected}
    assert set(reasons) == {"D", "E", "G"}
    assert reasons["D"]["status"] == "outside_plausible_range"
    assert reasons["E"]["status"] == "outside_plausible_range"
    assert reasons["G"]["status"] == "outlier_vs_peer_median"
    assert all(r["value"] is not None and r["reason"] for r in rejected)


def test_filtro_no_toca_un_grupo_normal():
    peers = [_pm(t, v) for t, v in zip("ABCDEF", (8.0, 10.0, 12.0, 14.0, 16.0, 18.0))]
    kept, rejected = screen_peer_outliers("pe", peers)
    assert kept == peers and rejected == []


# --- el motor ---------------------------------------------------------------------


def test_un_par_atipico_sale_de_la_mediana_y_queda_en_la_traza(db):
    company = _subject(db)
    for index, pe in enumerate((8.0, 10.0, 12.0, 14.0, 16.0, 400.0)):
        _peer(db, f"P{index}", pe)
    result = _value(db, company)
    assert result["trace"]["headline_multiple"] == "pe"
    # sin el atípico: mediana de 8/10/12/14/16 = 12 -> 12 x EPS 2 = 24 (antes 13 x 2 = 26)
    assert result["base_value"] == pytest.approx(24.0)
    block = next(b for b in result["trace"]["peer_multiples"] if b["multiple"] == "pe")
    assert block["peer_set_size"] == 5
    assert any(r["ticker"] == "P5" and r["status"] == "outside_plausible_range" for r in block["rejected_peers"])


def test_grupo_normal_sin_cambios(db):
    company = _subject(db)
    for index, pe in enumerate((8.0, 10.0, 12.0, 14.0, 16.0, 18.0)):
        _peer(db, f"P{index}", pe)
    result = _value(db, company)
    assert result["base_value"] == pytest.approx(26.0)
    assert result["trace"]["peer_set_size"] == 6


def test_grupo_de_respaldo_sin_relaciones_queda_etiquetado(db):
    company = _subject(db)
    for index, pe in enumerate((8.0, 10.0, 12.0, 14.0, 16.0, 18.0)):
        _peer(db, f"P{index}", pe)
    result = _value(db, company)
    assert result["trace"]["peer_set"]["fallback_only"] is True


def test_grupo_con_relaciones_curadas_no_es_de_respaldo(db):
    company = _subject(db)
    peers = [_peer(db, f"P{index}", pe) for index, pe in enumerate((8.0, 10.0, 12.0, 14.0, 16.0, 18.0))]
    for peer in peers:
        db.add(PeerRelationship(company_id=company.id, peer_company_id=peer.id, score=Decimal("0.9"),
                                selected=True, rationale=["manual"], selection_trace={}))
    db.commit()
    result = _value(db, company)
    assert result["trace"]["peer_set"]["fallback_only"] is False


def test_caso_tipo_baba_sin_relaciones_y_pares_atipicos_no_da_cifra(db):
    """Sin peer_relationships y un grupo de respaldo dominado por PER de ~370x:
    tras filtrar quedan 2 pares -> no hay valor orientativo, con el motivo."""
    company = _subject(db)
    for index, pe in enumerate((350.0, 369.0, 380.0, 400.0, 20.0, 25.0)):
        _peer(db, f"P{index}", pe)
    result = _value(db, company)
    assert result["status"] == "insufficient_data"
    assert result["base_value"] is None and result["expected_value"] is None
    assert "pares insuficientes tras filtrar atípicos" in result["trace"]["reason"]
    assert result["trace"]["peer_set"]["fallback_only"] is True
    assert result["trace"]["peer_outlier_filter"]["min_valid_peers"] == MIN_VALID_PEERS


# --- el respaldo sectorial (holding sin segmentos) ----------------------------------


def _insufficient():
    return {"status": "insufficient_data", "publishable": False,
            "missing_inputs": ["net_debt", "segment_*_operating_metric"], "base_value": None,
            "expected_value": None, "trace": {"engine": "holding_company", "reason": "SOTP requires ..."}}


def test_respaldo_sectorial_baba_real_no_publica_300(db):
    """Holding sin SOTP -> respaldo por múltiplos sobre el motor real: sin cifra."""
    company = _subject(db, "HOLD")
    for index, pe in enumerate((350.0, 369.0, 380.0, 400.0, 20.0, 25.0)):
        _peer(db, f"P{index}", pe)
    engine = RelativeMultiplesEngine()
    context = engine.build_context(db, company, 20.0)
    original = _insufficient()
    out = vs._sector_fallback(db, company, context, original, to_listing=None,
                              price_currency="USD", reporting_currency="USD")
    assert out.get("expected_value") is None and out.get("base_value") is None
    assert out["status"] == "insufficient_data"


def test_respaldo_sectorial_muy_por_encima_del_precio_se_retiene(monkeypatch, db):
    from app.services.valuation_service import INDICATIVE_MAX_PRICE_RATIO

    # valor orientativo 3x+ el precio (margen de seguridad 0,958 => 24x)
    cross = {"status": "partial", "base_value": 295.0, "expected_value": 300.0, "bear_value": 255.0,
             "bull_value": 331.0, "margin_of_safety": 0.958, "headline_multiple": "pe", "peer_median": 369.0}
    monkeypatch.setattr(vs, "_relative_multiples_cross_check", lambda *a, **k: dict(cross))
    out = vs._sector_fallback(db, _company(db, "HOLD2"), object(), _insufficient(), to_listing=None,
                              price_currency="USD", reporting_currency="USD")
    assert out.get("expected_value") is None
    assert out["status"] == "insufficient_data"
    withheld = out["trace"]["sector_engine_fallback_withheld"]
    assert withheld["max_price_ratio"] == INDICATIVE_MAX_PRICE_RATIO
    assert withheld["value_to_price_ratio"] == pytest.approx(1 / (1 - 0.958))
    assert "orientativo" in withheld["reason"]


def test_respaldo_sectorial_razonable_sigue_saliendo_y_etiqueta_el_grupo(monkeypatch, db):
    cross = {"status": "ok", "base_value": 24.0, "expected_value": 25.0, "bear_value": 20.0,
             "bull_value": 30.0, "margin_of_safety": 0.2, "headline_multiple": "pe", "peer_median": 12.0,
             "peer_set_fallback_only": True}
    monkeypatch.setattr(vs, "_relative_multiples_cross_check", lambda *a, **k: dict(cross))
    out = vs._sector_fallback(db, _company(db, "HOLD3"), object(), _insufficient(), to_listing=None,
                              price_currency="USD", reporting_currency="USD")
    assert out["expected_value"] == 25.0
    assert out["trace"]["sector_engine_fallback"]["peer_set_fallback_only"] is True
