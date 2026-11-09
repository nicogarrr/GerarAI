"""Resolución de CIKs del monitor de insiders: una query, no una por ticker.

Antes, ``resolve_ciks`` buscaba la Company de CADA ticker de la watchlist con
una query (60 sentencias con 60 tickers en cada pasada del monitor y del
13D/G). Ahora todas las empresas salen de una sola query con IN. Este test
fija el coste plano y la paridad con el bucle anterior: CIK propio gana,
emisor extranjero sin CIK se salta (no resuelve homónimos de EDGAR), sin CIK
doméstico cae a la red y se persiste, y un ticker sin empresa no escribe
nada. La resolución de red va stubada para aislar el recuento.
"""

from __future__ import annotations

import uuid

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

import app.services.insider_monitor as insider_monitor
from app.models import Company, Tenant
from app.models.entities import Base


def _session(n_tickers: int):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    tenant = Tenant(external_id=f"im-{uuid.uuid4().hex[:8]}", name="T", status="active")
    db.add(tenant)
    db.flush()
    db.info["tenant_id"] = tenant.id
    for i in range(n_tickers):
        ticker = f"IM{i:04d}"
        db.add(
            Company(
                ticker=ticker, name=ticker, exchange="NASDAQ", currency="USD",
                cik=f"000{i:06d}"[:10], sector="T", industry="T",
                company_type="standard", valuation_model="standard_dcf",
            )
        )
    db.commit()
    return engine, db


def _count_and_run(n_tickers: int) -> tuple[int, dict]:
    engine, db = _session(n_tickers)
    statements: list[str] = []
    event.listen(engine, "before_cursor_execute", lambda *a: statements.append(a[2]))
    resolved = insider_monitor.resolve_ciks(db, [f"IM{i:04d}" for i in range(n_tickers)], client=None)
    db.close()
    return len(statements), resolved


def test_resolve_ciks_no_escala_por_ticker():
    pocas, r3 = _count_and_run(3)
    muchas, r60 = _count_and_run(60)
    assert muchas == pocas == 1, (pocas, muchas)
    assert len(r3) == 3 and len(r60) == 60
    assert r3["IM0000"] == f"000{0:06d}"[:10]


def test_resolve_ciks_paridad_extranjero_red_y_fantasma(monkeypatch):
    engine, db = _session(0)
    db.add(
        Company(
            ticker="FRGN", name="F", exchange="BME", currency="EUR", cik=None,
            sector="T", industry="T", company_type="standard", valuation_model="standard_dcf",
        )
    )
    db.add(
        Company(
            ticker="NOC", name="N", exchange="NASDAQ", currency="USD", cik=None,
            sector="T", industry="T", company_type="standard", valuation_model="standard_dcf",
        )
    )
    db.commit()
    monkeypatch.setattr(
        insider_monitor, "_cik_for_ticker",
        lambda ticker, client=None: {"NOC": "0009999999", "GHOST": "0008888888"}.get(ticker),
    )
    resolved = insider_monitor.resolve_ciks(db, ["FRGN", "NOC", "GHOST"], client=None)
    # El extranjero sin CIK no resuelve por homónimo; el doméstico sí y se
    # persiste en la ficha; el fantasma resuelve pero no escribe nada.
    assert resolved == {"NOC": "0009999999", "GHOST": "0008888888"}
    assert db.query(Company).filter_by(ticker="NOC").one().cik == "0009999999"
    assert db.query(Company).filter_by(ticker="FRGN").one().cik is None
    db.close()
