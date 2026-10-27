"""Seleccion de comparables: el numero de queries no crece con el universo.

Antes, ``_find_peers`` lanzaba una query de market cap POR CADA compania de
la tabla ``companies`` (maestro + stubs del buscador + importaciones IBKR):
con 16 companias /peers/comparison pasaba de 359 a 811 sentencias frente a 4.
Ahora el market cap de todos los candidatos sale de una sola query con
row_number por compania. Este test fija que el coste de la seleccion no
depende de cuantas companias haya y que el valor elegido (ultimo ejercicio,
luego el mas reciente) es el mismo que devolvia la consulta unitaria.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.models.entities import Base, Company, FinancialFact
from app.services.peer_comparison_service import PeerComparisonService


def _company(ticker: str) -> Company:
    return Company(
        ticker=ticker, name=ticker, exchange="NASDAQ", currency="USD",
        sector="Technology", industry="Software", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[],
        factor_tags=["growth"],
    )


def _cap(company_id: int, year: int, value: str, tenant_id: int = 1) -> FinancialFact:
    return FinancialFact(
        tenant_id=tenant_id, company_id=company_id, metric="market_cap",
        period=f"FY{year}", fiscal_year=year, value=Decimal(value),
        unit="USD", source_type="test",
    )


def _session(n_companies: int):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    db.info["tenant_id"] = 1
    companies = [_company(f"PEER{i:03d}") for i in range(n_companies)]
    db.add_all(companies)
    db.flush()
    for i, company in enumerate(companies):
        db.add(_cap(company.id, 2023, str(1000 + i)))
        db.add(_cap(company.id, 2024, str(2000 + i)))
    db.commit()
    return engine, db, companies


def _count_find_peers(n_companies: int) -> tuple[int, list]:
    engine, db, companies = _session(n_companies)
    statements: list[str] = []
    event.listen(engine, "before_cursor_execute", lambda *a: statements.append(a[2]))
    peers, _basis, trace = PeerComparisonService()._find_peers(db, companies[0], limit=8)
    db.close()
    return len(statements), trace["candidates"]


def test_seleccion_de_peers_no_escala_con_el_universo():
    pocas, _ = _count_find_peers(4)
    muchas, candidatos = _count_find_peers(40)
    assert muchas == pocas, (pocas, muchas)
    assert pocas <= 4
    assert len(candidatos) == 39


def test_market_cap_por_lotes_elige_el_ultimo_ejercicio_y_respeta_tenant():
    engine, db, companies = _session(3)
    target, other, sin_cap = companies
    # Otro tenant con un ejercicio mas reciente: no puede ganar el ranking.
    db.info["tenant_id"] = 2
    db.add(_cap(other.id, 2030, "999999", tenant_id=2))
    db.commit()
    db.info["tenant_id"] = 1
    db.query(FinancialFact).filter(
        FinancialFact.company_id == sin_cap.id
    ).delete()
    db.commit()
    service = PeerComparisonService()
    caps = service._latest_market_caps(db, [target.id, other.id, sin_cap.id])
    assert caps == {target.id: Decimal("2000"), other.id: Decimal("2001")}
    for company_id in (target.id, other.id, sin_cap.id):
        assert service._latest_market_cap(db, company_id) == caps.get(company_id)
    db.close()
