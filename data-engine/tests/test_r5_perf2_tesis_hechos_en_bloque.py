"""/thesis-v2: ``company_facts`` sin hidratar ~800 entidades por empresa y comparables en bloque.

Medido 11-nov-2026 (r5-perf2, 10 tickers): ``company_facts`` se llama para la empresa y para cada
comparable (9 veces por ``/thesis-v2``) y era el 64 % de la llamada. Reglas probadas:

- mismo resultado que la versión de siempre (copiada aquí como referencia) en un caso con varias fuentes,
  segmentos, trimestres, saldos anuales y acciones de portada;
- los flujos que no son de ejercicio completo no se leen (SQL), y ``company_facts`` hace 2 consultas;
- ``_peer_multiples`` lee los hechos de TODOS los comparables de una vez: las consultas no crecen con el
  número de comparables, y lo precargado se consume una vez y no sobrevive a la llamada.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, desc, event, select
from sqlalchemy.orm import selectinload, sessionmaker

from app.models.entities import Base, Company, Document, FinancialFact
from app.services import shareholder_irr_service as irr


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _company(db, ticker):
    c = Company(
        ticker=ticker, name=f"{ticker} Inc.", exchange="NYSE", currency="USD", sector="S", industry="I",
        company_type="research_candidate", valuation_model="unassigned", special_sources=[],
        special_risks=[], factor_tags=[],
    )
    db.add(c)
    db.commit()
    return c


_T0 = datetime(2026, 1, 1, 12, 0, 0)


def _seed(db, company, *, scale=1.0):
    sec = Document(company_id=company.id, title="10-K", source_type="SEC",
                   source_url="https://www.sec.gov/Archives/edgar/data/1/x.htm", metadata_={})
    yahoo = Document(company_id=company.id, title="Yahoo", source_type="YAHOO_FUNDAMENTALS", metadata_={})
    seg = Document(company_id=company.id, title="segmento", source_type="SEC", metadata_={"segment": "Cloud"})
    db.add_all([sec, yahoo, seg])
    db.flush()
    n = 0

    def fact(metric, value, period, doc, source_type, *, filed=None, accession=None):
        nonlocal n
        n += 1
        db.add(FinancialFact(
            company_id=company.id, metric=metric, value=Decimal(str(value * scale)), unit="USD",
            period=period, fiscal_year=int(period[:4]), fiscal_quarter=period.split(":")[1],
            source_id=doc.id if doc else None, source_type=source_type, is_reported=source_type == "SEC",
            confidence=Decimal("0.9"), filed=filed, accession_number=accession,
            created_at=_T0 + timedelta(minutes=n),
        ))

    for year in (2022, 2023, 2024, 2025):
        p = f"{year}-12-31:FY"
        fact("revenue", 1000 + year, p, sec, "SEC", filed=date(year + 1, 2, 1), accession=f"0001-{year}")
        fact("revenue", 999 + year, p, yahoo, "YAHOO_FUNDAMENTALS")  # peor prioridad
        fact("revenue", 50, p, seg, "SEC")  # segmento: fuera
        fact("net_income", 100 + year, p, sec, "SEC")
        fact("ebitda", 300 + year, p, yahoo, "YAHOO_FUNDAMENTALS")
        fact("total_equity", 500 + year, p, sec, "SEC")
        fact("cash_and_equivalents", 40 + year, p, sec, "SEC")
        for q in ("Q1", "Q2", "Q3"):  # flujos trimestrales: nunca cuentan
            fact("revenue", 250, f"{year}-0{3 * int(q[1])}-30:{q}", sec, "SEC")
    fact("cash_and_equivalents", 77, "2026-06-30:Q2", sec, "SEC")  # saldo más reciente
    fact("total_debt", 10, "2026-06-30:Q2", yahoo, "YAHOO_FUNDAMENTALS")
    fact("total_debt", 12, "2026-06-30:Q2", sec, "SEC")  # mismo cierre, mejor fuente
    fact("shares_outstanding", 7e6, "2026-07-20:DEI", sec, "SEC")
    fact("shares_outstanding", 6e6, "2026-03-31:Q1", None, "FMP")
    db.commit()


def _reference_company_facts(db, company):
    """La implementación de siempre (main antes de r5-perf2), como oráculo."""
    from app.services.analyst_report import SOURCE_PRIORITY
    from app.services.esef_fact_quarantine import fact_quarantine_reason
    from app.services.ttm_service import _is_segment

    rows = list(db.scalars(
        select(FinancialFact)
        .where(FinancialFact.company_id == company.id, FinancialFact.metric.in_(irr._FLOW + irr._POINT))
        .options(selectinload(FinancialFact.source))
        .order_by(desc(FinancialFact.period), desc(FinancialFact.id))
    ).all())
    annual, point = {}, {}
    for fact in rows:
        if fact.value is None or _is_segment(fact) or fact_quarantine_reason(fact):
            continue
        rank = (float(SOURCE_PRIORITY.get(fact.source_type or "", 50)),
                -(fact.created_at.timestamp() if fact.created_at else 0.0))
        period = str(fact.period or "")
        if fact.metric in irr._FLOW and period.endswith(":FY"):
            year = irr._fiscal_year(period)
            if year is None:
                continue
            slot = annual.setdefault(fact.metric, {})
            if year not in slot or rank < slot[year][0]:
                slot[year] = (rank, irr._cite(fact))
        elif fact.metric in irr._POINT:
            end = irr._end(period)
            if fact.metric in irr._POINT_ANNUAL and period.endswith(":FY"):
                year = irr._fiscal_year(period)
                if year is not None:
                    slot = annual.setdefault(fact.metric, {})
                    if year not in slot or rank < slot[year][0]:
                        slot[year] = (rank, irr._cite(fact))
            cur = point.get(fact.metric)
            if cur is None or end > cur[0] or (end == cur[0] and rank < cur[1]):
                cite = irr._share_cite(fact) if fact.metric == "shares_outstanding" else irr._cite(fact)
                point[fact.metric] = (end, rank, cite)
    return ({m: {y: c for y, (_, c) in v.items()} for m, v in annual.items()},
            {m: c for m, (_, _, c) in point.items()})


class _Count:
    def __init__(self, db):
        self.statements: list[str] = []
        self._engine = db.get_bind()

    def __enter__(self):
        event.listen(self._engine, "before_cursor_execute", self._on)
        return self

    def __exit__(self, *exc):
        event.remove(self._engine, "before_cursor_execute", self._on)

    def _on(self, conn, cursor, statement, params, context, executemany):
        self.statements.append(statement)


def test_mismo_resultado_que_la_version_de_siempre(db):
    company = _company(db, "AAA")
    _seed(db, company)
    expected = _reference_company_facts(db, company)
    db.expunge_all()  # sesión limpia, como en una petición
    got = irr.company_facts(db, db.get(Company, company.id))
    assert got == expected
    annual, point = got
    assert set(annual["revenue"]) == {2022, 2023, 2024, 2025}
    assert annual["revenue"][2025]["source_type"] == "SEC" and annual["revenue"][2025]["value"] == 3025.0
    assert annual["revenue"][2025]["url"] == "https://www.sec.gov/Archives/edgar/data/1/x.htm"
    assert point["total_debt"]["value"] == 12.0 and point["cash_and_equivalents"]["value"] == 77.0


def test_dos_consultas_y_sin_flujos_trimestrales(db):
    company = _company(db, "BBB")
    _seed(db, company)
    db.expunge_all()
    company = db.get(Company, company.id)
    with _Count(db) as count:
        irr.company_facts(db, company)
    assert len(count.statements) == 2, count.statements  # hechos + sus documentos
    facts_sql = next(s for s in count.statements if "financial_facts" in s)
    assert "LIKE" in facts_sql.upper()  # los flujos no anuales se descartan en SQL


def test_comparables_en_bloque_consultas_constantes(db, monkeypatch):
    peers = [_company(db, f"P{i:02d}") for i in range(6)]
    for i, peer in enumerate(peers):
        _seed(db, peer, scale=1 + i / 10)
    target = _company(db, "TGT")
    reads: list[list[int]] = []
    real_read = irr._read_fact_rows

    def spy(session, ids):
        reads.append(sorted(ids))
        return real_read(session, ids)

    monkeypatch.setattr(irr, "_read_fact_rows", spy)
    seen: dict[int, tuple] = {}
    real_company_facts = irr.company_facts

    def starting_point(session, peer, *, today, basis=None):
        seen[peer.id] = real_company_facts(session, peer)
        raise ValueError("sin precio")  # como un comparable sin cotización: queda sin múltiplo

    monkeypatch.setattr(irr, "starting_point", starting_point)

    def peers_for(n):
        class _Svc:
            def _find_peers(self, session, company, limit):
                return peers[:n], "sector", {}

        return _Svc

    import app.services.peer_comparison_service as pcs

    counts = {}
    for n in (2, 6):
        reads.clear()
        seen.clear()
        monkeypatch.setattr(pcs, "PeerComparisonService", peers_for(n))
        db.expunge_all()
        with _Count(db) as count:
            out = irr._peer_multiples(db, db.get(Company, target.id), "ev_ebitda", date(2026, 11, 11))
        assert [row["multiple"] for row in out] == [None] * n
        assert reads == [sorted(p.id for p in peers[:n])]  # UNA lectura para todos
        counts[n] = sum("financial_facts" in s or "FROM documents" in s for s in count.statements)
        assert irr._PREFETCH_KEY not in db.info  # nada sobrevive a la llamada
        for peer in peers[:n]:
            db.expunge_all()
            assert seen[peer.id] == _reference_company_facts(db, db.get(Company, peer.id))
    assert counts[2] == counts[6] == 2


def test_lo_precargado_se_consume_una_vez(db):
    company = _company(db, "CCC")
    _seed(db, company)
    db.info[irr._PREFETCH_KEY] = irr._read_fact_rows(db, [company.id])
    try:
        first = irr.company_facts(db, company)
        assert company.id not in db.info[irr._PREFETCH_KEY]
        with _Count(db) as count:
            second = irr.company_facts(db, company)  # ya consumido: vuelve a leer
        assert len(count.statements) == 2 and first == second
    finally:
        db.info.pop(irr._PREFETCH_KEY, None)


def test_sesion_sin_info_sigue_funcionando():
    assert irr._take_prefetched_facts(SimpleNamespace(), 1) is None
