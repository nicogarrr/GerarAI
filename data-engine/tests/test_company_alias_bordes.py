"""company_alias_sources: business_text sobre SQLite real, resolve_qid con
``get`` doblado (sin red), frescura de cache y utilidades puras.

No se prueba aqui: fetch_wikidata completo (orquestacion de SPARQL y
homonimos), _candidate_rows/_own_labels, store/load_cached (metadata de
tenant), build_record/ensure_aliases, collapse_series ni homonym_weight.
Sin red: toda llamada HTTP va por un ``get`` falso o por fetch_public_url
doblado. Compañías y documentos sinteticos.
"""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.entities import Base, Company, Document, DocumentChunk
from app.services import company_alias_sources as cas
from app.services.company_alias_sources import (
    AliasRecord,
    AliasTerm,
    _default_get,
    _exchange_tokens,
    business_text,
    resolve_qid,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as session:
        session.info["tenant_id"] = "tenant-test"
        yield session
    engine.dispose()


def _company(db, ticker="ITX", name="Inditex"):
    company = Company(
        ticker=ticker, name=name, exchange="BME", currency="EUR",
        sector="S", industry="I", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def _doc(db, company_id, source_type, published, tombstoned=False):
    doc = Document(
        title=f"Informe {source_type}",
        source_type=source_type,
        company_id=company_id,
        published_at=published,
        retention_tombstoned_at=datetime(2026, 11, 1, tzinfo=UTC) if tombstoned else None,
    )
    db.add(doc)
    db.flush()
    return doc


def _chunk(db, doc, index, text):
    db.add(DocumentChunk(document_id=doc.id, chunk_index=index, text=text))


def test_business_text_sin_documento(db):
    company = _company(db)
    assert business_text(db, company.id) == (None, None)


def test_business_text_elige_el_informe_mas_reciente_y_su_fuente(db):
    company = _company(db)
    viejo = _doc(db, company.id, "sec_10k", datetime(2026, 1, 15, tzinfo=UTC))
    _chunk(db, viejo, 0, "viejo")
    nuevo = _doc(db, company.id, "esef", datetime(2026, 3, 1, tzinfo=UTC))
    _chunk(db, nuevo, 1, "Beta")
    _chunk(db, nuevo, 0, "Alpha")
    db.commit()
    texto, fuente = business_text(db, company.id)
    assert texto == "Alpha\nBeta"
    assert fuente == "esef"


def test_business_text_ignora_documentos_tombstoned(db):
    company = _company(db)
    viejo = _doc(db, company.id, "sec_10k", datetime(2026, 1, 15, tzinfo=UTC))
    _chunk(db, viejo, 0, "texto valido")
    borrado = _doc(db, company.id, "esef", datetime(2026, 3, 1, tzinfo=UTC), tombstoned=True)
    _chunk(db, borrado, 0, "no debe salir")
    db.commit()
    assert business_text(db, company.id) == ("texto valido", "sec_10k")


def test_business_text_respeta_el_limite_de_caracteres(db):
    company = _company(db)
    doc = _doc(db, company.id, "annual_report", datetime(2026, 2, 1, tzinfo=UTC))
    _chunk(db, doc, 0, "Alpha")
    _chunk(db, doc, 1, "Beta")
    db.commit()
    texto, fuente = business_text(db, company.id, limit_chars=7)
    assert texto == "Alpha\nB"
    assert fuente == "annual_report"


def _fake_get(bindings=None, search=None):
    def get(url, params):
        if "query" in params:
            return {"results": {"bindings": bindings or []}}
        return {"search": search or []}

    return get


def test_resolve_qid_por_isin():
    company = SimpleNamespace(isin="es0123456784", ticker="", name=None, exchange=None)
    get = _fake_get(bindings=[{"item": {"value": "http://www.wikidata.org/entity/Q95"}}])
    assert resolve_qid(company, get) == "Q95"


def test_resolve_qid_isin_ambiguo_sigue_por_nombre():
    company = SimpleNamespace(isin="ES0123456784", ticker="", name="Space Exploration", exchange=None)
    get = _fake_get(
        bindings=[
            {"item": {"value": "http://www.wikidata.org/entity/Q95"}},
            {"item": {"value": "http://www.wikidata.org/entity/Q96"}},
        ],
        search=[{"id": "Q42", "label": "Space Exploration", "match": {"text": "SpaceX"}}],
    )
    assert resolve_qid(company, get) == "Q42"


def test_resolve_qid_por_ticker_desempata_por_nombre():
    company = SimpleNamespace(
        isin=None, ticker="ZPH", name="Zephyr Quantum", exchange=None
    )
    get = _fake_get(bindings=[
        {"item": {"value": "http://www.wikidata.org/entity/Q2"},
         "itemLabel": {"value": "Quantum Dynamics"}, "exLabel": {"value": "NASDAQ"}},
        {"item": {"value": "http://www.wikidata.org/entity/Q1"},
         "itemLabel": {"value": "Zephyr Quantum Systems"}, "exLabel": {"value": "NASDAQ"}},
    ])
    assert resolve_qid(company, get) == "Q1"


def test_resolve_qid_frase_sin_coincidencia_devuelve_none():
    company = SimpleNamespace(isin=None, ticker="", name="Space Exploration", exchange=None)
    get = _fake_get(search=[{"id": "Q42", "label": "Otra Cosa", "match": {"text": "nada"}}])
    assert resolve_qid(company, get) is None


def test_is_fresh_reglas():
    ahora = datetime(2026, 11, 9, tzinfo=UTC)
    assert AliasRecord(ticker="T").is_fresh(ahora) is False
    assert AliasRecord(ticker="T", fetched_at="no-es-fecha").is_fresh(ahora) is False
    # Naive se interpreta como UTC.
    reciente = (ahora - timedelta(days=1)).replace(tzinfo=None).isoformat()
    assert AliasRecord(ticker="T", fetched_at=reciente).is_fresh(ahora) is True
    viejo = (ahora - timedelta(days=cas.CACHE_TTL_DAYS + 1)).isoformat()
    assert AliasRecord(ticker="T", fetched_at=viejo).is_fresh(ahora) is False
    # Con error, el TTL es el de reintento (1 dia), no el de cache (30).
    ayer = (ahora - timedelta(days=cas.ERROR_RETRY_DAYS + 1)).isoformat()
    assert AliasRecord(ticker="T", fetched_at=ayer, error="sin_qid").is_fresh(ahora) is False
    hace_horas = (ahora - timedelta(hours=2)).isoformat()
    assert AliasRecord(ticker="T", fetched_at=hace_horas, error="sin_qid").is_fresh(ahora) is True


def test_alias_term_ambiguous_deriva_de_requiere():
    assert AliasTerm(termino="Starlink", tipo="producto", fuente="wikidata").ambiguous is False
    con_contexto = AliasTerm(
        termino="BlueBird", tipo="producto", fuente="wikidata", requiere=("satellite",)
    )
    assert con_contexto.ambiguous is True


def test_exchange_tokens_normaliza_bolsas():
    assert "nasdaq" in _exchange_tokens("NASDAQ")
    assert {"new", "york"} <= _exchange_tokens("NYSE")
    assert "madrid" in _exchange_tokens("BME")
    assert "london" in _exchange_tokens("LSE")
    assert "euronext" in _exchange_tokens("Euronext Amsterdam")
    assert _exchange_tokens(None) == set()


def test_default_get_solo_wikidata_y_parsea_json(monkeypatch):
    llamadas = {}

    def fake_fetch(url, max_bytes, timeout, allowed_url, user_agent):
        llamadas["url"] = url
        llamadas["allowed"] = allowed_url
        return b'{"ok": true}', "application/json", url

    monkeypatch.setattr("app.services.public_fetch.fetch_public_url", fake_fetch)
    assert _default_get(cas.WIKIDATA_SPARQL, {"query": "SELECT 1", "format": "json"}) == {"ok": True}
    assert "query=SELECT+1" in llamadas["url"]
    assert llamadas["allowed"]("https://query.wikidata.org/sparql") is True
    assert llamadas["allowed"]("https://www.wikidata.org/w/api.php") is True
    assert llamadas["allowed"]("https://example.com") is False
