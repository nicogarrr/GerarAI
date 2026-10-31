"""Guardas de routes/memory.py: enums cerrados (400 fijo, no basura persistida),
resolucion de compania (404), filtro de visibilidad del feed de cambios de
tesis y 404s de versiones/sesiones.

Los enums viajan como str libre en los schemas: la ruta es quien cierra el
contrato. Y el feed de cambios descarta captacion de despachos, tarjetas sin
relacion con la tesis y duplicados por ingesta multiple.
"""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.routes import memory as mem
from app.models.entities import (
    Base,
    Claim,
    Company,
    MemoryItem,
    ResearchSession,
    ThesisSection,
    ThesisVersion,
)
from app.schemas import ClaimCreate, MemoryItemCreate, ThesisChangeCreate


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _company(db: Session, ticker: str = "ACME") -> Company:
    company = Company(
        ticker=ticker, name="Acme Corp", exchange="NASDAQ", currency="USD",
        sector="Tech", industry="Tech", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def _version(db: Session, company: Company, version: int = 1) -> ThesisVersion:
    tv = ThesisVersion(
        company_id=company.id, version=version, thesis_markdown="# t",
        executive_summary="s",
    )
    db.add(tv)
    db.commit()
    return tv


# -- enums cerrados -----------------------------------------------------------


def test_memory_item_enums_invalidos_400_fijo():
    base = dict(scope="portfolio", memory_type="note", status="active", source_type="user")
    for field, bad in [
        ("scope", "global"), ("memory_type", "fact"), ("status", "deleted"), ("source_type", "api"),
    ]:
        with pytest.raises(HTTPException) as exc:
            mem.validate_memory_item_enums(**{**base, field: bad})
        assert exc.value.status_code == 400
        assert exc.value.detail == f"Invalid memory {field}"
    mem.validate_memory_item_enums(**base)  # valido: no lanza


# -- resolucion de compania ---------------------------------------------------


def test_company_by_ticker_404_y_encontrada(db):
    with pytest.raises(HTTPException) as exc:
        mem._company_by_ticker(db, "NOEXISTE")
    assert exc.value.status_code == 404
    company = _company(db)
    assert mem._company_by_ticker(db, "ACME").id == company.id


def test_resolve_company_id_ticker_company_id_y_404(db):
    company = _company(db)
    assert mem._resolve_company_id(db, "ACME", None) == company.id
    assert mem._resolve_company_id(db, None, company.id) == company.id
    assert mem._resolve_company_id(db, None, None) is None
    with pytest.raises(HTTPException) as exc:
        mem._resolve_company_id(db, None, 9999)
    assert exc.value.status_code == 404


# -- feed de cambios de tesis --------------------------------------------------


def test_change_dedupe_key_normaliza():
    assert mem._change_dedupe_key("¡Hola, Mundo!  2024") == "hola mundo 2024"
    assert mem._change_dedupe_key(None) == ""


def _change(summary, claims=(1,), metrics=()):
    return SimpleNamespace(summary=summary, affected_claim_ids=list(claims), affected_metrics=list(metrics))


def test_visible_thesis_changes_filtra_y_deduplica():
    rows = [
        _change("Rosen Law Firm announces investigation on behalf of investors"),   # captacion: fuera
        _change("No structural thesis node matched with sufficient confidence."),   # sin relacion: fuera
        _change("Tarjeta sin claims ni metricas", claims=(), metrics=()),           # sin relacion: fuera
        _change("Sube el margen bruto un 5%"),
        _change("  Sube el margen bruto un 5%!! "),                                  # duplicado: fuera
        _change("Baja la deuda neta un 10%"),
    ]
    visible = mem._visible_thesis_changes(rows, limit=50)
    assert [v.summary.strip() for v in visible] == ["Sube el margen bruto un 5%", "Baja la deuda neta un 10%"]


def test_visible_thesis_changes_aplica_el_limite():
    rows = [_change(f"Cambio numero {i}") for i in range(10)]
    assert len(mem._visible_thesis_changes(rows, limit=3)) == 3


# -- endpoints: validaciones y persistencia -------------------------------------


def test_create_memory_item_enum_invalido_no_persiste(db):
    payload = MemoryItemCreate(scope="global", content="contenido valido")
    with pytest.raises(HTTPException) as exc:
        mem.create_memory_item(payload, db=db)
    assert exc.value.status_code == 400
    assert db.query(MemoryItem).count() == 0  # nada persistido


def test_create_memory_item_vincula_sesion(db):
    session = ResearchSession(title="t", question="q")
    db.add(session)
    db.commit()
    payload = MemoryItemCreate(content="recuerdo importante", research_session_id=session.id)
    item = mem.create_memory_item(payload, db=db)
    assert item.id is not None
    db.refresh(session)
    assert session.memory_item_ids == [item.id]  # la sesion enlaza el item


def test_create_memory_item_sesion_inexistente_404(db):
    payload = MemoryItemCreate(content="recuerdo importante", research_session_id=9999)
    with pytest.raises(HTTPException) as exc:
        mem.create_memory_item(payload, db=db)
    assert exc.value.status_code == 404


def test_list_memory_items_scope_invalido_400(db):
    with pytest.raises(HTTPException) as exc:
        mem.list_memory_items(scope="global", db=db)
    assert exc.value.status_code == 400


def test_create_claim_version_inexistente_404(db):
    _company(db)
    payload = ClaimCreate(ticker="ACME", statement="El margen crece", thesis_version_id=9999)
    with pytest.raises(HTTPException) as exc:
        mem.create_claim(payload, db=db)
    assert exc.value.status_code == 404
    assert db.query(Claim).count() == 0


def test_create_claim_happy_path_resuelve_compania(db):
    company = _company(db)
    payload = ClaimCreate(ticker="ACME", statement="El margen crece")
    claim = mem.create_claim(payload, db=db)
    assert claim.company_id == company.id
    assert db.scalar(db.query(Claim).filter_by(id=claim.id).statement) is not None


def test_get_claim_404(db):
    with pytest.raises(HTTPException) as exc:
        mem.get_claim(9999, db=db)
    assert exc.value.status_code == 404


def test_create_thesis_change_versiones_inexistentes_404(db):
    _company(db)
    payload = ThesisChangeCreate(ticker="ACME", summary="Cambio de tesis", from_version_id=9999)
    with pytest.raises(HTTPException) as exc:
        mem.create_thesis_change(payload, db=db)
    assert exc.value.status_code == 404
    payload = ThesisChangeCreate(ticker="ACME", summary="Cambio de tesis", to_version_id=9999)
    with pytest.raises(HTTPException) as exc:
        mem.create_thesis_change(payload, db=db)
    assert exc.value.status_code == 404


def test_list_thesis_sections_sin_tesis_404_y_orden(db):
    _company(db)
    with pytest.raises(HTTPException) as exc:
        mem.list_thesis_sections("ACME", db=db)
    assert exc.value.status_code == 404

    company = _company(db, ticker="OTRA")
    v1 = _version(db, company, version=1)
    db.add(ThesisSection(thesis_version_id=v1.id, company_id=company.id, section_key="b", title="B", order_index=2))
    db.add(ThesisSection(thesis_version_id=v1.id, company_id=company.id, section_key="a", title="A", order_index=1))
    db.commit()
    sections = mem.list_thesis_sections("OTRA", db=db)
    assert [s.section_key for s in sections] == ["a", "b"]  # orden por order_index
