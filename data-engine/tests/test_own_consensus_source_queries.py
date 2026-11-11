"""Las fuentes del consenso no provocan una query por hecho financiero."""
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.models.entities import Base, Company, Document, FinancialFact
from app.services.own_consensus import _facts


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.info["tenant_id"] = 1
    company = Company(ticker="SOURCE", name="Source", exchange="NASDAQ", currency="USD",
                      company_type="operating", valuation_model="unassigned")
    session.add(company)
    session.flush()
    company_id = company.id
    yield session, engine, company_id
    session.close()
    engine.dispose()


def _fact(db, company_id, *, year, source_id=None, tenant=1, metric="revenue"):
    db.add(FinancialFact(
        tenant_id=tenant, company_id=company_id, metric=metric,
        period=f"FY{year}", fiscal_year=year, value=Decimal(year),
        unit="USD", filed=date(year + 1, 2, 1), source_id=source_id,
    ))


@pytest.mark.parametrize("count", [4, 40])
def test_sources_do_not_add_one_query_per_fact(db, count):
    session, engine, cid = db
    expected = []
    for i in range(count):
        year = 1980 + i
        url = f"https://example.org/filing/{year}"
        document = Document(tenant_id=1, company_id=cid, title=str(year),
                            source_type="test", source_url=url)
        session.add(document)
        session.flush()
        _fact(session, cid, year=year, source_id=document.id)
        expected.append((f"FY{year}", float(year), date(year + 1, 2, 1), url, year))
    session.commit()
    session.expunge_all()  # fuentes no precargadas en el identity map
    statements = []
    event.listen(engine, "before_cursor_execute", lambda *a: statements.append(a[2]))
    result = _facts(session, SimpleNamespace(id=cid), "revenue")
    assert sorted(result) == expected
    # Constante con 4 o 40 hechos: hechos + UNA lectura de documentos (IN),
    # sin JOIN que repita el documento por fila (perf r5 11-nov-2026).
    assert len(statements) == 2, statements


def test_missing_sources_and_filtered_urls_preserve_rows(db):
    session, _engine, cid = db
    document = Document(tenant_id=1, company_id=cid, title="Legacy ESEF",
                        source_type="test",
                        source_url="https://filings.xbrl.org/api/filings (fxo_id=123)")
    session.add(document)
    session.flush()
    _fact(session, cid, year=2020, source_id=document.id)
    _fact(session, cid, year=2021)
    session.commit()
    session.expunge_all()
    assert sorted(_facts(session, SimpleNamespace(id=cid), "revenue")) == [
        ("FY2020", 2020.0, date(2021, 2, 1), None, 2020),
        ("FY2021", 2021.0, date(2022, 2, 1), None, 2021),
    ]
    assert _facts(session, SimpleNamespace(id=cid), "absent_metric") == []


def test_company_metric_and_tenant_scope_preserved(db):
    session, _engine, cid = db
    other = Company(ticker="OTHER", name="Other", exchange="NASDAQ", company_type="operating", valuation_model="unassigned")
    session.add(other)
    session.flush()
    _fact(session, cid, year=2020)
    _fact(session, other.id, year=2021)
    _fact(session, cid, year=2022, metric="net_income")
    session.commit()
    session.info["tenant_id"] = 2
    _fact(session, cid, year=2023, tenant=2)
    session.commit()
    session.info["tenant_id"] = 1
    session.expunge_all()
    assert _facts(session, SimpleNamespace(id=cid), "revenue") == [
        ("FY2020", 2020.0, date(2021, 2, 1), None, 2020),
    ]


def test_foreign_tenant_source_is_not_exposed(db):
    session, _engine, cid = db
    session.info["tenant_id"] = 2
    document = Document(tenant_id=2, company_id=cid, title="Foreign document",
                        source_type="test", source_url="https://example.org/private")
    session.add(document)
    session.flush()
    doc_id = document.id
    session.commit()
    session.info["tenant_id"] = 1
    _fact(session, cid, year=2020, source_id=doc_id)
    session.commit()
    session.expunge_all()
    assert _facts(session, SimpleNamespace(id=cid), "revenue") == [
        ("FY2020", 2020.0, date(2021, 2, 1), None, 2020),
    ]


def test_unreadable_source_keeps_fact_with_missing_url():
    class UnreadableSource:
        period = "FY2020"
        value = Decimal("42")
        filed = date(2021, 2, 1)

        @property
        def source_url(self):
            raise RuntimeError("source unavailable")

    session = SimpleNamespace(scalars=lambda _stmt: SimpleNamespace(all=lambda: [UnreadableSource()]))
    assert _facts(session, SimpleNamespace(id=1), "revenue") == [
        ("FY2020", 42.0, date(2021, 2, 1), None, None),
    ]
