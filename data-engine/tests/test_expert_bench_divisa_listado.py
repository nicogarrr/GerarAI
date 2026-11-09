"""Registro de previsiones: precio y divisa del LISTADO, no de los informes ni de un USD por defecto.

Caso real (benchmarks/prediccion_log_2026-11-08.jsonl): FFH.TO cotiza en CAD en Toronto y presenta en USD.
El registro guardaba el precio ya pasado a USD (1.900,39 USD) con la etiqueta USD, y forecast-score lo
comparaba con el cierre guardado en CAD (~2.670 CAD): un +40 % de rentabilidad que no existió.
"""

from __future__ import annotations

import importlib.util
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models import Company, MarketPrice, Tenant
from app.services import expert_bench as eb

ROOT = Path(__file__).resolve().parents[1]


def _script():
    spec = importlib.util.spec_from_file_location("expert_bench_script_divisa", ROOT / "scripts" / "expert_bench.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _rec(price: float, currency: str, **extra):
    scen = {k: {"horizons": {"5": {"irr": v}, "10": {"irr": v}}} for k, v in (("bear", 0.03), ("base", 0.09), ("bull", 0.14))}
    return eb.forecast_record(
        ticker="FFH.TO",
        as_of=date(2026, 11, 8),
        price=price,
        currency=currency,
        scenarios=scen,
        weighted=None,
        method="tir_pb",
        probability_choice=None,
        kill_switches=[],
        claims=[],
        thesis_fingerprint=None,
        commit=None,
        **extra,
    )


def test_registro_lleva_el_listado_y_aparte_la_valuacion():
    rec = _rec(2673.0, "CAD", valuation_price=1900.39, valuation_currency="USD")
    assert (rec["price"], rec["currency"]) == (2673.0, "CAD")
    assert (rec["valuation_price"], rec["valuation_currency"]) == (1900.39, "USD")
    # el id solo depende de ticker, fecha, precio y TIR: no cambia por añadir la valuación
    assert rec["id"] == _rec(2673.0, "CAD")["id"]
    assert "valuation_price" not in _rec(2673.0, "CAD")


def test_divisa_distinta_no_se_puntua_y_queda_fuera_del_resumen():
    rec = _rec(1900.39, "USD")
    s = eb.score_forecast(rec, horizon_years=1, price_then=2673.0, price_then_currency="CAD")
    assert s["realized_annual"] is None and s["base_irr5"] is None
    assert "USD" in s["reason"] and "CAD" in s["reason"]
    assert eb.summarize_scores([s]) == {"n": 0}


def test_misma_divisa_puntua_sin_distinguir_mayusculas():
    rec = _rec(2673.0, "CAD")
    s = eb.score_forecast(rec, horizon_years=1, price_then=2673.0 * 1.09, price_then_currency="cad")
    assert s["realized_annual"] == pytest.approx(0.09)
    assert "reason" not in s


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Tenant(id=1, external_id="t1"))
        session.commit()
        yield session


def _company(db, ticker, currency):
    c = Company(
        ticker=ticker, name=ticker, exchange="TSX", currency=currency, sector="Financials",
        industry="Insurance", company_type="standard", valuation_model="standard_dcf",
        special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(c)
    db.flush()
    return c


@pytest.mark.parametrize("row_currency", ["CAD", "USD", ""])
def test_cierre_en_la_divisa_del_listado_aunque_la_fila_diga_usd(db, row_currency):
    """La divisa sale del listado (.TO -> CAD) y de la cotización, no de la fila ni de un USD por defecto."""
    company = _company(db, "XYZ.TO", row_currency)
    day = date(2027, 11, 8)
    db.add(MarketPrice(company_id=company.id, date=day - timedelta(days=1), open=0, high=0, low=0,
                       close=Decimal("2700"), quote_currency="CAD", source="yfinance"))
    db.flush()
    got = _script()._close_on_or_before(db, company, day)
    assert got == (pytest.approx(2700.0), "CAD")


def test_cierre_viejo_de_mas_de_una_semana_no_vale(db):
    company = _company(db, "XYZ.TO", "CAD")
    day = date(2027, 11, 8)
    db.add(MarketPrice(company_id=company.id, date=day - timedelta(days=30), open=0, high=0, low=0,
                       close=Decimal("2700"), quote_currency="CAD", source="yfinance"))
    db.flush()
    assert _script()._close_on_or_before(db, company, day) is None


def test_forecast_score_pasa_el_cierre_a_la_divisa_de_un_registro_antiguo(monkeypatch, tmp_path, capsys):
    """Un registro antiguo en USD (precio de la valuación) se puntúa con el cierre en CAD pasado a USD."""
    import json

    mod = _script()
    rec = _rec(1900.39, "USD")
    rec["score_at"] = {"1y": "2000-01-01", "3y": "2000-01-01"}
    log = tmp_path / "log.jsonl"
    log.write_text(json.dumps(rec) + "\n")
    monkeypatch.setattr(mod, "_session", lambda: SimpleNamespace())
    monkeypatch.setattr(mod, "_company", lambda db, t: SimpleNamespace(id=1, ticker=t))
    monkeypatch.setattr(mod, "_close_on_or_before", lambda db, c, d: (2700.0, "CAD"))
    monkeypatch.setattr(mod, "_dividends_between", lambda db, c, a, b: 0.0)
    import app.services.user_sotp_service as us

    monkeypatch.setattr(us, "convert_amount", lambda db, amount, src, dst, as_of=None: (amount * 0.7, "CAD→USD"))
    mod.cmd_forecast_score(SimpleNamespace(log=str(log), horizon=1))
    out = json.loads(capsys.readouterr().out)
    (s,) = out["scores"]
    assert s["realized_annual"] == pytest.approx(2700.0 * 0.7 / 1900.39 - 1)

    # sin tipo de cambio: N/D con su motivo, no una rentabilidad con divisas mezcladas
    monkeypatch.setattr(us, "convert_amount", lambda db, amount, src, dst, as_of=None: None)
    mod.cmd_forecast_score(SimpleNamespace(log=str(log), horizon=1))
    (s,) = json.loads(capsys.readouterr().out)["scores"]
    assert s["realized_annual"] is None and "CAD" in s["reason"]
