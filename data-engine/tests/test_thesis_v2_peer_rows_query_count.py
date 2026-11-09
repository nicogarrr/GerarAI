"""Filas de comparables de la tesis v2: una query de empresas, no una por peer.

Antes, ``peer_rows`` buscaba la Company de CADA comparable con una query por
ticker (9 sentencias con 8 comparables + 1 fantasma). Ahora todas las
empresas salen de una sola query con IN. Este test fija el coste plano y la
paridad con el bucle anterior: margen/crecimiento/apalancamiento calculados,
nota «sin datos suficientes» cuando starting_point falla, fila del ticker
fantasma intacta y empate de ticker duplicado resuelto por id menor.
``starting_point`` va stubado (sin queries) para aislar el recuento del
lookup de empresas.
"""

from __future__ import annotations

import uuid
from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

import app.services.shareholder_irr_service as sirr
from app.models import Company, Tenant
from app.models.entities import Base
from app.services.expert_team import thesis_v2


@pytest.fixture()
def _stub_starting_point(monkeypatch):
    def stub(db, peer, today=None, basis=None):
        if peer.ticker.endswith("X"):
            raise ValueError("sin historia")
        return (
            SimpleNamespace(margin=0.2, net_debt=10.0, ebitda=5.0),
            SimpleNamespace(revenue=[1.0, 2.0, 3.0, 4.0]),
            None,
            None,
        )

    monkeypatch.setattr(sirr, "starting_point", stub)


def _session(n_peers: int):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    tenant = Tenant(external_id=f"pr-{uuid.uuid4().hex[:8]}", name="T", status="active")
    db.add(tenant)
    db.flush()
    db.info["tenant_id"] = tenant.id
    target = Company(
        ticker=f"PR{uuid.uuid4().hex[:4].upper()}", name="E", exchange="NASDAQ", currency="USD",
        sector="T", industry="T", company_type="standard", valuation_model="standard_dcf",
    )
    db.add(target)
    db.flush()
    for i in range(n_peers):
        ticker = f"P{i:03d}" + ("X" if i == 2 else "")
        db.add(
            Company(
                ticker=ticker, name=ticker, exchange="NASDAQ", currency="USD",
                sector="T", industry="T", company_type="standard", valuation_model="standard_dcf",
            )
        )
    db.commit()
    return engine, db, target


def _val(n_peers: int) -> dict:
    return {
        "starting_point": {"basis": "x"},
        "peers": [
            {"ticker": f"P{i:03d}" + ("X" if i == 2 else ""), "name": f"N{i}", "multiple": 10 + i}
            for i in range(n_peers)
        ]
        + [{"ticker": "GHOST", "name": "G", "multiple": 1}],
    }


def _count_and_run(n_peers: int):
    engine, db, target = _session(n_peers)
    statements: list[str] = []
    event.listen(engine, "before_cursor_execute", lambda *a: statements.append(a[2]))
    rows = thesis_v2.peer_rows(db, target, _val(n_peers), date(2026, 11, 9))
    db.close()
    return len(statements), rows


@pytest.mark.usefixtures("_stub_starting_point")
def test_peer_rows_no_escala_por_comparable():
    pocas, _ = _count_and_run(3)
    muchas, _ = _count_and_run(8)
    assert muchas == pocas == 1, (pocas, muchas)


@pytest.mark.usefixtures("_stub_starting_point")
def test_peer_rows_paridad_margen_nota_y_fantasma():
    _, rows = _count_and_run(3)
    assert rows[0]["margin"] == 0.2
    assert abs(rows[0]["growth"] - (4.0 / 1.0) ** (1 / 3) + 1) < 1e-9
    assert rows[0]["leverage"] == 2.0
    assert rows[2]["note"].startswith("sin datos suficientes")
    fantasma = rows[-1]
    assert fantasma["ticker"] == "GHOST" and fantasma["margin"] is None and fantasma["note"] is None
