"""Visibilidad de documentos: las re-ingestas del mismo filing de la SEC no se duplican.

document_visibility no tenia tests propios; lo usan la ficha de empresa, la
vista global de fuentes y los eventos de empresa.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, Document, Tenant
from app.services.document_visibility import (
    is_immutable_archive_url,
    without_archive_duplicates,
)

ARCHIVE = "https://www.sec.gov/Archives/edgar/data/320193/000032019325000079/aapl-20250927.htm"


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        tenant = Tenant(external_id="visibilidad", name="visibilidad")
        session.add(tenant)
        session.flush()
        session.info["tenant_id"] = tenant.id
        yield session


def _company(db: Session, ticker: str) -> Company:
    company = Company(
        ticker=ticker, name=f"{ticker} Inc", exchange="NASDAQ", currency="USD",
        sector="Tech", industry="Tech", company_type="standard",
        valuation_model="standard_dcf", special_sources=[], special_risks=[],
        factor_tags=[],
    )
    db.add(company)
    db.flush()
    return company


def _doc(db: Session, company: Company, title: str, url: str | None, published: datetime | None) -> Document:
    doc = Document(
        company_id=company.id, title=title, source_type="sec_filing",
        source_url=url, published_at=published,
    )
    db.add(doc)
    db.flush()
    return doc


def _visible_titles(db: Session) -> list[str]:
    return sorted(db.scalars(without_archive_duplicates(select(Document.title))))


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (ARCHIVE, True),
        ("http://www.sec.gov/Archives/edgar/data/1/2.txt", True),
        ("https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany", False),
        ("https://example.com/www.sec.gov/Archives/x", False),
        ("", False),
        (None, False),
    ],
)
def test_solo_las_urls_de_archivo_de_la_sec_son_inmutables(url, expected):
    assert is_immutable_archive_url(url) is expected


def test_reingesta_del_mismo_filing_se_muestra_una_vez_la_mas_reciente(db):
    aapl = _company(db, "AAPL")
    _doc(db, aapl, "10-K antiguo", ARCHIVE, datetime(2025, 10, 31, tzinfo=UTC))
    _doc(db, aapl, "10-K reingesta", ARCHIVE, datetime(2025, 11, 1, tzinfo=UTC))
    assert _visible_titles(db) == ["10-K reingesta"]


def test_misma_fecha_desempata_por_la_ingesta_mas_reciente(db):
    aapl = _company(db, "AAPL")
    when = datetime(2025, 10, 31, tzinfo=UTC)
    _doc(db, aapl, "primera", ARCHIVE, when)
    _doc(db, aapl, "segunda", ARCHIVE, when)
    assert _visible_titles(db) == ["segunda"]


def test_sin_fecha_no_gana_a_una_fila_fechada(db):
    aapl = _company(db, "AAPL")
    _doc(db, aapl, "fechada", ARCHIVE, datetime(2025, 10, 31, tzinfo=UTC))
    _doc(db, aapl, "sin fecha", ARCHIVE, None)
    assert _visible_titles(db) == ["fechada"]


def test_urls_que_no_son_de_archivo_y_sin_url_nunca_se_ocultan(db):
    aapl = _company(db, "AAPL")
    live = "https://investor.apple.com/news"
    _doc(db, aapl, "noticia 1", live, datetime(2025, 10, 30, tzinfo=UTC))
    _doc(db, aapl, "noticia 2", live, datetime(2025, 10, 31, tzinfo=UTC))
    _doc(db, aapl, "nota manual", None, None)
    assert _visible_titles(db) == ["nota manual", "noticia 1", "noticia 2"]


def test_el_mismo_filing_en_dos_empresas_no_se_colapsa(db):
    aapl = _company(db, "AAPL")
    msft = _company(db, "MSFT")
    when = datetime(2025, 10, 31, tzinfo=UTC)
    _doc(db, aapl, "copia AAPL", ARCHIVE, when)
    _doc(db, msft, "copia MSFT", ARCHIVE, when)
    assert _visible_titles(db) == ["copia AAPL", "copia MSFT"]


@pytest.mark.parametrize("scope_size", [0, 1, 2])
def test_company_scope_preserves_archive_winners_and_live_rows(db, scope_size):
    companies = [_company(db, ticker) for ticker in ["AAPL", "MSFT", "KO"]]
    when = datetime(2025, 10, 31, tzinfo=UTC)
    for company in companies:
        _doc(db, company, f"{company.ticker} old", ARCHIVE, None)
        _doc(db, company, f"{company.ticker} winner", ARCHIVE, when)
        _doc(db, company, f"{company.ticker} live1", "https://example.com/ir", when)
        _doc(db, company, f"{company.ticker} live2", "https://example.com/ir", when)
        _doc(db, company, f"{company.ticker} no url", None, None)
    ids = [company.id for company in companies[:scope_size]]
    original = without_archive_duplicates(
        select(Document.id).where(Document.company_id.in_(ids))
    )
    scoped = without_archive_duplicates(select(Document.id), company_ids=ids)
    assert sorted(db.scalars(scoped)) == sorted(db.scalars(original))
    assert len(db.scalars(scoped).all()) == 4 * scope_size


def test_company_scope_filters_ranking_before_window():
    from sqlalchemy.dialects import postgresql

    stmt = without_archive_duplicates(select(Document.id), company_ids=[7, 8])
    sql = str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert sql.count("documents.company_id IN (7, 8)") == 2


def test_company_scope_keeps_tenant_partition_independent(db):
    company = _company(db, "AAPL")
    when = datetime(2025, 10, 31, tzinfo=UTC)
    own = _doc(db, company, "own", ARCHIVE, when)
    other = Tenant(external_id="other", name="other")
    db.add(other)
    db.flush()
    own_tenant_id = db.info["tenant_id"]
    db.info["tenant_id"] = other.id
    db.add(Document(company_id=company.id, tenant_id=other.id,
                    title="other tenant", source_type="sec_filing",
                    source_url=ARCHIVE, published_at=when))
    db.flush()
    db.info["tenant_id"] = own_tenant_id
    statement = select(Document.id).where(Document.tenant_id == own_tenant_id)
    assert db.scalars(without_archive_duplicates(statement, company_ids=[company.id])).all() == [own.id]
