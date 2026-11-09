"""Sincronización Form 4 (investor_portfolio): las queries no crecen por línea.

Antes, la fase 2 de ``sync_form4`` comprobaba SI YA EXISTE cada transacción
con una query por línea (64 sentencias con 8 filings × 8 líneas en cada
pasada del monitor). Ahora los pares (accession, línea) ya persistidos salen
de una sola consulta con tuple IN. Este test fija el coste plano en estado
estacionario y la idempotencia: la segunda pasada no crea nada y el total de
filas coincide con las transacciones no derivadas. Red y parseo stubados.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

import app.services.investor_portfolio as investor_portfolio
from app.models import Tenant
from app.models.entities import Base, InvestorMovement
from app.services.connectors import form4


def _filings(n_filings: int) -> list[dict]:
    return [
        {
            "accession_number": f"acc-{f:03d}", "document_url": f"https://x/{f}",
            "filing_date": "2026-01-10", "form": "4", "index_url": f"https://idx/{f}",
        }
        for f in range(n_filings)
    ]


def _parsed(n_lines: int) -> dict:
    return {
        "reporters": [{"cik": "947033"}], "issuer_name": "X", "ticker": "X",
        "transactions": [
            {"is_derivative": False, "type": "P", "shares": 100, "date": "2026-01-09", "price": 10.0}
            for _ in range(n_lines)
        ],
    }


@pytest.fixture()
def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    tenant = Tenant(external_id=f"ip-{uuid.uuid4().hex[:8]}", name="T", status="active")
    db.add(tenant)
    db.flush()
    db.info["tenant_id"] = tenant.id
    return engine, db


def _count_steady(session, monkeypatch, n_filings: int, n_lines: int) -> tuple[int, int, int]:
    engine, db = session
    db.query(InvestorMovement).delete()
    db.commit()
    monkeypatch.setattr(form4, "parse_form4_xml", lambda xml: _parsed(n_lines))
    fl = _filings(n_filings)
    first = investor_portfolio.sync_form4(db, "trump", filings=fl, fetch=lambda url: "<xml/>")
    db.expire_all()
    statements: list[str] = []
    event.listen(engine, "before_cursor_execute", lambda *a: statements.append(a[2]))
    second = investor_portfolio.sync_form4(db, "trump", filings=fl, fetch=lambda url: "<xml/>")
    return len(statements), first, second


def test_sync_form4_estacionario_no_escala_por_linea(monkeypatch, _session):
    pocas, f2, s2 = _count_steady(_session, monkeypatch, 2, 8)
    muchas, f8, s8 = _count_steady(_session, monkeypatch, 8, 8)
    assert muchas == pocas, (pocas, muchas)
    assert pocas <= 3
    assert (f2, s2) == (16, 0)
    assert (f8, s8) == (64, 0)


def test_sync_form4_respeta_derivadas_e_idempotencia(monkeypatch, _session):
    engine, db = _session
    parsed = _parsed(6)
    parsed["transactions"].append(
        {"is_derivative": True, "type": "A", "shares": 5, "date": "2026-01-09", "price": 1.0}
    )
    monkeypatch.setattr(form4, "parse_form4_xml", lambda xml: parsed)
    first = investor_portfolio.sync_form4(db, "trump", filings=_filings(1), fetch=lambda url: "<xml/>")
    second = investor_portfolio.sync_form4(db, "trump", filings=_filings(1), fetch=lambda url: "<xml/>")
    # La derivada no se persiste; la segunda pasada no duplica.
    assert (first, second) == (6, 0)
    assert db.query(InvestorMovement).count() == 6
    db.close()
