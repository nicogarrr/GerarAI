"""/api/valuation y /own-consensus: lecturas repetidas dentro de una misma petición.

Medido 11-nov-2026 (r5-perf2, MSI): el snapshot del DCF pedía ~17 métricas y cada una releía con
``selectinload`` los mismos documentos (18 SELECT a ``documents``, cada uno con su ``metadata`` JSON);
``/own-consensus`` leía dos veces las cifras reales de cada métrica (acierto medido y consenso).
Reglas probadas:

- en una llamada de valoración cada documento se lee una vez; la relación ``source`` queda cargada
  igual que con el ``selectinload`` (y ``None`` cuando no hay documento);
- ``own_consensus._facts`` lee una vez por métrica dentro de la caché de llamada y la ruta la instala;
  cada llamada recibe una lista nueva y sin caché se lee como siempre.
"""

from decimal import Decimal

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import sessionmaker

from app.models.entities import Base, Company, Document, FinancialFact
from app.valuation.call_cache import valuation_call_cache


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _seed(db):
    company = Company(
        ticker="ZZDOC", name="Docs Inc.", exchange="NYSE", currency="USD", sector="S", industry="I",
        company_type="research_candidate", valuation_model="unassigned", special_sources=[],
        special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.flush()
    k10 = Document(company_id=company.id, title="10-K 2025", source_type="SEC",
                   source_url="https://www.sec.gov/x.htm", metadata_={"big": "x" * 1000})
    yahoo = Document(company_id=company.id, title="Yahoo", source_type="YAHOO_FUNDAMENTALS", metadata_={})
    db.add_all([k10, yahoo])
    db.flush()
    rows = [
        ("revenue", 4.2e9, k10), ("free_cash_flow", 9e8, k10), ("operating_cash_flow", 1.1e9, k10),
        ("capital_expenditure", -2e8, k10), ("shares_diluted", 7e8, k10), ("total_debt", 2.5e8, k10),
        ("cash_and_equivalents", 1.2e9, k10), ("net_income", 5e8, yahoo), ("ebitda", 1.3e9, None),
    ]
    for metric, value, doc in rows:
        db.add(FinancialFact(
            company_id=company.id, metric=metric, value=Decimal(str(value)), unit="shares" if "shares" in metric
            else "USD", period="2025-12-31:FY", fiscal_year=2025, fiscal_quarter="FY",
            source_id=doc.id if doc else None, source_type=doc.source_type if doc else "DERIVED",
            is_reported=doc is not None, confidence=Decimal("0.9"),
        ))
    db.commit()
    db.expunge_all()
    return company


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

    def on(self, table):
        return [s for s in self.statements if f"FROM {table}" in s]


METRICS = ("revenue", "free_cash_flow", "operating_cash_flow", "capital_expenditure", "shares_diluted",
           "total_debt", "cash_and_equivalents", "net_income", "ebitda")


def test_cada_documento_se_lee_una_vez_por_llamada(db):
    from app.valuation.financial_snapshot import _facts_for_metric

    company = _seed(db)
    with valuation_call_cache(db), _Count(db) as count:
        got = {m: _facts_for_metric(db, company.id, m) for m in METRICS}
    # El 10-K y la ficha de Yahoo, cada uno UNA vez (en main: una lectura por métrica con documento, 8).
    assert len(count.on("documents")) == 2, count.on("documents")
    assert len(count.on("financial_facts")) == len(METRICS)
    for facts in got.values():
        for fact in facts:
            assert "source" in sa_inspect(fact).dict  # cargada: acceder no lanza otra consulta
    with _Count(db) as later:
        titles = {m: [f.source.title if f.source else None for f in facts] for m, facts in got.items()}
    assert later.statements == []
    assert titles["revenue"] == ["10-K 2025"] and titles["net_income"] == ["Yahoo"]
    assert titles["ebitda"] == [None]
    assert got["revenue"][0].source_url == "https://www.sec.gov/x.htm"


def test_sin_cache_misma_respuesta_que_el_selectinload(db):
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.valuation.financial_snapshot import _facts_for_metric

    company = _seed(db)
    mine = {m: [(f.id, f.source.title if f.source else None) for f in _facts_for_metric(db, company.id, m)]
            for m in METRICS}
    db.expunge_all()
    ref = {}
    for m in METRICS:
        rows = db.scalars(select(FinancialFact).options(selectinload(FinancialFact.source))
                          .where(FinancialFact.company_id == company.id, FinancialFact.metric == m)).all()
        ref[m] = [(f.id, f.source.title if f.source else None) for f in rows]
    assert mine == ref


def test_consenso_lee_cada_metrica_una_vez(monkeypatch):
    from app.services import own_consensus as oc

    reads: list[str] = []

    def fake_read(db, company, metric):
        reads.append(metric)
        return [("2025-12-31:FY", 1.0, None, None, 2025)]

    monkeypatch.setattr(oc, "_read_facts", fake_read)

    class _Db:
        info: dict = {"tenant_id": "t"}

    db, company = _Db(), type("C", (), {"id": 7})()
    with valuation_call_cache(db):  # type: ignore[arg-type]
        first = oc._facts(db, company, "revenue")
        second = oc._facts(db, company, "revenue")
        oc._facts(db, company, "operating_income")
    assert reads == ["revenue", "operating_income"]
    assert first == second and first is not second  # lista nueva: nadie altera lo cacheado
    first.clear()
    oc._facts(db, company, "revenue")  # fuera de la caché: se lee de nuevo
    assert reads == ["revenue", "operating_income", "revenue"]


def test_la_ruta_own_consensus_instala_la_cache(monkeypatch):
    from app.api.routes import estimates
    from app.services import estimate_accuracy, own_consensus

    reads: list[str] = []
    monkeypatch.setattr(own_consensus, "_read_facts",
                        lambda db, company, metric: reads.append(metric) or [])
    monkeypatch.setattr(estimates, "_company", lambda db, ticker: type("C", (), {"id": 1, "ticker": ticker})())
    monkeypatch.setattr(estimates, "_tenant", lambda db: 1)

    def accuracy(db, company, tenant):
        for metric in ("revenue", "operating_income", "eps_diluted"):
            own_consensus._facts(db, company, metric)
        return {"measured_errors": {}, "version": "v", "by_source": {}, "cases": []}

    def consensus(db, company, tenant, *, measured_errors):
        for metric in ("revenue", "operating_income", "eps_diluted"):
            own_consensus._facts(db, company, metric)
        return {}

    monkeypatch.setattr(estimate_accuracy, "company_accuracy", accuracy)
    monkeypatch.setattr(own_consensus, "build_company_consensus", consensus)

    class _Db:
        info: dict = {"tenant_id": "t"}

    db = _Db()
    estimates.own_consensus("ZZ", db)  # type: ignore[arg-type]
    assert reads == ["revenue", "operating_income", "eps_diluted"]  # en main: 6 lecturas
    assert "valuation_call_cache_v1" not in db.info  # se borra al salir
