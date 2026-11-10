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
    assert pocas <= 5
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


def test_prefiltro_solo_descarta_imposibles():
    """_candidate_possible: superset del conjunto que puede puntuar.

    Industria (igual o por palabras), sector (salvo emisor extranjero) y eje
    de referencia abren la puerta; el resto no puede puntuar y se descarta.
    """
    from app.services.peer_comparison_service import _candidate_possible

    target = _company("TARGET")
    other_sector = _company("X")
    other_sector.sector = "Energy"
    other_sector.industry = "Oil & Gas"

    def pos(candidate, *, foreign=False, target_ref=None, candidate_ref=None):
        return _candidate_possible(
            target, candidate,
            target_is_foreign=foreign, target_ref=target_ref, candidate_ref=candidate_ref,
        )

    misma = _company("A")
    assert pos(misma) is True  # misma industria
    subset = _company("B")
    subset.industry = "Data analytics software tools"
    subset.sector = "Energy"
    assert pos(subset) is True  # palabras de la industria contenidas
    sector = _company("C")
    sector.industry = "Oil & Gas"
    assert pos(sector) is True  # mismo sector (target no extranjero)
    assert pos(sector, foreign=True) is False  # extranjero: solo industria
    assert pos(other_sector) is False  # ni industria ni sector
    referencia = _company("D")
    referencia.sector, referencia.industry = "Energy", "Oil & Gas"
    assert pos(
        referencia,
        target_ref=("Energy", "Oil, Gas & Consumable Fuels"),
        candidate_ref=("Energy", "Oil, Gas & Consumable Fuels"),
    ) is True  # eje de referencia con misma industria
    assert pos(
        referencia,
        target_ref=("Energy", "Oil, Gas & Consumable Fuels"),
        candidate_ref=("Technology", "Software"),
    ) is False
    sin_clasificar = _company("E")
    sin_clasificar.sector = "unassigned"
    sin_clasificar.industry = ""
    assert pos(sin_clasificar) is False  # placeholders no clasifican


def test_prefiltro_acota_hidratacion_y_market_cap():
    """El candidato imposible no se hidrata ni entra en la query de market cap."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    db.info["tenant_id"] = 1
    target = _company("TARGET")
    near = _company("NEAR")
    far = _company("FAR")
    far.sector, far.industry = "Energy", "Oil & Gas"
    db.add_all([target, near, far])
    db.flush()
    for company, value in ((target, "1000"), (near, "1100"), (far, "1200")):
        db.add(_cap(company.id, 2024, value))
    db.commit()
    calls: list[tuple[str, object]] = []
    event.listen(engine, "before_cursor_execute", lambda *a: calls.append((a[2], a[3])))
    peers, _basis, _trace = PeerComparisonService()._find_peers(db, target, limit=8)
    db.close()
    assert [peer.ticker for peer in peers] == ["NEAR"]

    def _params(raw):
        if isinstance(raw, dict):
            return list(raw.values())
        if isinstance(raw, (list, tuple)):
            return list(raw)
        return [raw]

    full_company = [p for sql, p in calls if "FROM companies" in sql and " IN " in sql.upper()]
    assert full_company, calls  # la hidratación completa va con IN acotado
    for raw in full_company:
        assert far.id not in _params(raw)
        assert near.id in _params(raw)
    cap_queries = [p for sql, p in calls if "financial_facts" in sql and "row_number" in sql.lower()]
    assert cap_queries, calls
    for raw in cap_queries:
        assert far.id not in _params(raw)


def test_sql_in_chunks_helper_preserva_orden_y_lotes():
    from app.core.sql_chunks import sql_in_chunks

    assert list(sql_in_chunks([], size=3)) == []
    assert list(sql_in_chunks([1, 2], size=3)) == [[1, 2]]
    assert list(sql_in_chunks(range(7), size=3)) == [[0, 1, 2], [3, 4, 5], [6]]
    assert list(sql_in_chunks("abcd", size=2)) == [["a", "b"], ["c", "d"]]
    try:
        list(sql_in_chunks([1], size=0))
        raise AssertionError("size 0 no debe valer")
    except ValueError:
        pass


def test_in_troceado_mismo_resultado_con_lotes_de_uno(monkeypatch):
    """Con lote 1, hidratación y market cap van id a id y el resultado no cambia."""
    import app.core.sql_chunks as chunks

    engine, db, companies = _session(4)
    service = PeerComparisonService()
    ids = [c.id for c in companies]
    expected = service._latest_market_caps_usd(db, ids)
    statements: list[str] = []
    event.listen(engine, "before_cursor_execute", lambda *a: statements.append(a[2]))
    monkeypatch.setattr(chunks, "SQL_IN_CHUNK_SIZE", 1)
    assert service._latest_market_caps_usd(db, ids) == expected
    cap_queries = [sql for sql in statements if "financial_facts" in sql and "row_number" in sql.lower()]
    assert len(cap_queries) == len(ids)  # lote 1: una sentencia por id
    peers, _basis, trace = service._find_peers(db, companies[0], limit=8)
    assert [p.ticker for p in peers] == [c.ticker for c in companies[1:8]]
    assert len(trace["candidates"]) == 39 - 36
    db.close()
    monkeypatch.undo()
    # Y con el tamaño por defecto, el conteo de sentencias no escala (4 vs 40).
    assert _count_find_peers(4)[0] == _count_find_peers(40)[0]
