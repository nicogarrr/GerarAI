"""Puesto relativo por valor justo / precio en el monitor de watchlist (sustituye a la etiqueta binaria)."""
import asyncio
from datetime import date, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.routes import watchlist
from app.models.entities import (
    Base,
    Company,
    FundamentalModelVersion,
    MarketPrice,
    ThesisVersion,
    ValuationModel,
    ValuationOutput,
)
from app.valuation.relative_rank import MIN_PEERS, rank_against


def test_quintile_one_is_the_cheapest_fifth():
    peers = [0.1 * i for i in range(1, 101)]  # 0,1 .. 10,0
    assert rank_against(9.95, peers)["quintile"] == 1
    assert rank_against(0.15, peers)["quintile"] == 5
    assert rank_against(5.05, peers)["quintile"] == 3
    top = rank_against(20.0, peers)
    assert top == {"quintile": 1, "cheaper_than_pct": 100, "peers": 100}


def test_rank_ignores_the_level_of_the_method():
    # Recalibrar el valor justo (todo ×1,6) no cambia el puesto: se ordena por cociente.
    peers = [0.3 + 0.02 * i for i in range(60)]
    before = rank_against(0.61, peers)
    after = rank_against(0.61 * 1.6, [p * 1.6 for p in peers])
    assert before == after


def test_few_peers_or_no_ratio_gives_no_rank():
    assert rank_against(1.0, [1.0] * (MIN_PEERS - 1)) is None
    assert rank_against(None, [1.0] * 100) is None


def _db_with_peers(n_peers: int) -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    today = date.today()
    # Comparables: última corrida del motor con valor y el precio con el que se calculó.
    for index in range(n_peers):
        company = Company(ticker=f"PEER{index}", name="Peer", exchange="NYSE", currency="USD",
                          company_type="listed", valuation_model="dcf")
        db.add(company)
        db.flush()
        model = ValuationModel(company_id=company.id, model_type="dcf", version=2, status="final")
        db.add(model)
        db.flush()
        # cociente valor/precio de 0,30 a 1,50 (como el método hoy: casi todas «sobrevaloradas»)
        value = 30 + 120 * index / max(n_peers - 1, 1)
        db.add(ValuationOutput(valuation_model_id=model.id, scenario="base",
                               output_payload={"expected_value": value, "current_price": 100.0}))
        # Una corrida vieja con un valor absurdo no cuenta: manda la última.
        old = ValuationModel(company_id=company.id, model_type="dcf", version=1, status="final")
        db.add(old)
        db.flush()
        db.add(ValuationOutput(valuation_model_id=old.id, scenario="base",
                               output_payload={"expected_value": 9999.0, "current_price": 100.0}))
    for ticker, thesis_value in (("CHEAP", 140.0), ("DEAR", 35.0)):
        company = Company(ticker=ticker, name=ticker, exchange="NYSE", currency="USD",
                          company_type="listed", valuation_model="dcf")
        db.add(company)
        db.flush()
        db.add(ThesisVersion(company_id=company.id, version=1, status="published",
                             expected_value=thesis_value, thesis_markdown="t", executive_summary="s"))
        db.add(FundamentalModelVersion(
            company_id=company.id, version=1, engine_version="test", algorithm_version="test",
            framework_key="dcf", horizon_years=10, status="ok", publishable=True,
            input_fingerprint="input", forecast_fingerprint="forecast",
            market_snapshot_fingerprint="market", valuation_snapshot_fingerprint="valuation",
        ))
        db.add(MarketPrice(company_id=company.id, date=today - timedelta(days=1), close=100))
    db.commit()
    return db


def test_monitor_ranks_against_engine_peers_not_the_binary_side():
    db = _db_with_peers(50)
    items = asyncio.run(watchlist.watchlist_monitor(tickers="CHEAP,DEAR", db=db))["items"]
    # CHEAP: valor 1,4x el precio, entre el 20 % más barato de 50.
    assert items["CHEAP"]["valuation_rank"]["quintile"] == 1
    assert items["CHEAP"]["valuation_rank"]["peers"] == 50
    # DEAR: 0,35x, entre el 20 % más caro (la binaria decía lo mismo que a cualquier otra por debajo de 1x).
    assert items["DEAR"]["valuation_rank"]["quintile"] == 5
    assert items["DEAR"]["valuation_rank"]["cheaper_than_pct"] < 20
    db.close()


def test_monitor_without_enough_peers_has_no_rank():
    db = _db_with_peers(5)
    items = asyncio.run(watchlist.watchlist_monitor(tickers="CHEAP", db=db))["items"]
    assert items["CHEAP"]["valuation_rank"] is None
    assert items["CHEAP"]["fair_value"] == 140.0
    db.close()
