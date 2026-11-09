"""company_alias_sources (2.ª tanda de bordes): guardas puras, resolve_qid
con filas sin QID y plan B por nombre, fetch_wikidata sin QID, store/_tenant
sin tenant, catalog_terms sin ticker, ensure_aliases sin tenant y con
``business_text`` que falla (rollback), collapse_series con serie sin número
y alias_hit con texto vacío.

Sin red: toda llamada HTTP va por un ``get`` falso inyectado. SQLite real
para las rutas con BD (tenant en ``db.info``). Compañías sintéticas
(SimpleNamespace), como en test_company_alias_sources.py.
"""

from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.entities import Base, Tenant
from app.services import company_alias_sources as cas
from app.services.company_alias_sources import AliasRecord, AliasTerm


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return factory()


def _get_vacio(url, params):
    """Wikidata sin resultados: ni SPARQL ni búsqueda devuelven nada."""
    if (params or {}).get("action") == "wbsearchentities":
        return {"search": []}
    return {"results": {"bindings": []}}


# --- guardas puras ---------------------------------------------------------


def test_reject_reason_termino_qid_sin_etiqueta():
    # Un término que ES un QID no vale como alias: no tiene etiqueta legible.
    assert cas.reject_reason("Q12345", company_ticker="AAA", company_name="Acme Corp") == "sin_etiqueta"


def test_qid_guardas():
    assert cas._qid(None) is None
    assert cas._qid("") is None
    # URI cuya cola no es un QID → None.
    assert cas._qid("http://www.wikidata.org/entity/ABC") is None
    assert cas._qid("http://www.wikidata.org/entity/Q42") == "Q42"


def test_alias_hit_texto_vacio():
    term = AliasTerm(termino="acme", tipo="nombre", fuente="wikidata")
    assert cas.alias_hit("", [term]) is None


# --- resolve_qid: filas sin QID y plan B por nombre ------------------------


def test_resolve_qid_fila_sin_qid_continua_y_sin_frase_devuelve_none():
    def get(url, params):
        # La fila SPARQL tiene item cuya URI no termina en QID → se descarta.
        return {"results": {"bindings": [{"item": {"value": "http://www.wikidata.org/entity/ABC"}}]}}

    company = SimpleNamespace(ticker="AAA", name=None, exchange=None, isin=None)
    assert cas.resolve_qid(company, get) is None


def test_resolve_qid_plan_b_por_nombre_exacto():
    def get(url, params):
        if (params or {}).get("action") == "wbsearchentities":
            return {"search": [{"id": "Q9", "label": "Acme", "match": {"text": "Acme Corp"}}]}
        return {"results": {"bindings": []}}

    company = SimpleNamespace(ticker="AAA", name="Acme Corp", exchange=None, isin=None)
    assert cas.resolve_qid(company, get) == "Q9"


def test_own_labels_fila_sin_etiqueta_se_salta():
    def get(url, params):
        return {
            "results": {
                "bindings": [
                    {"l": {"value": ""}, "k": {"value": "a"}},
                    {"l": {"value": "Apple"}, "k": {"value": "p"}},
                ]
            }
        }

    assert cas._own_labels("Q1", get) == [("Apple", True)]


def test_resolve_qid_empate_sin_ganador_cae_al_plan_b():
    # Dos filas SPARQL con QID pero puntuación empatada e insuficiente →
    # condición de ganador falsa → plan B por nombre (que aquí tampoco da nada).
    def get(url, params):
        if (params or {}).get("action") == "wbsearchentities":
            return {"search": []}
        return {
            "results": {
                "bindings": [
                    {
                        "item": {"value": "http://www.wikidata.org/entity/Q1"},
                        "itemLabel": {"value": "Zzz"},
                        "exLabel": {"value": "Xetra"},
                    },
                    {
                        "item": {"value": "http://www.wikidata.org/entity/Q2"},
                        "itemLabel": {"value": "Yyy"},
                        "exLabel": {"value": "Xetra"},
                    },
                ]
            }
        }

    company = SimpleNamespace(ticker="AAA", name="Acme Corp", exchange="NASDAQ", isin=None)
    assert cas.resolve_qid(company, get) is None


# --- fetch_wikidata sin QID ------------------------------------------------


def test_fetch_wikidata_sin_qid_error_sin_qid():
    company = SimpleNamespace(ticker="AAA", name="Acme Corp", exchange=None, isin=None)
    record = cas.fetch_wikidata(company, _get_vacio)
    assert record.error == "sin_qid"
    assert record.ticker == "AAA"
    assert record.fuentes == ["wikidata"]
    assert record.aliases == []


def test_fetch_wikidata_sin_check_homonyms():
    # check_homonyms=False: salta el pesaje de homónimos y va directo a
    # finalize (rama 683->694). ISIN válido resuelve el QID de una vez.
    def get(url, params):
        query = (params or {}).get("query") or ""
        if "P946" in query:
            return {"results": {"bindings": [{"item": {"value": "http://www.wikidata.org/entity/Q1"}}]}}
        if "rdfs:label" in query:
            return {"results": {"bindings": [{"l": {"value": "Acme"}, "k": {"value": "p"}}]}}
        return {"results": {"bindings": []}}

    company = SimpleNamespace(
        ticker="AAA",
        name="Acme Corp",
        exchange=None,
        isin="US0378331005",
    )
    record = cas.fetch_wikidata(company, get, check_homonyms=False)
    assert record.qid == "Q1"
    assert record.error is None


# --- collapse_series: candidato «serie» sin número se descarta --------------


def test_collapse_series_serie_sin_numero_descartada():
    candidato = AliasTerm(termino="Starlink", tipo="serie", fuente="wikidata")
    assert cas.collapse_series([candidato]) == []


# --- catalog_terms: sin ticker se salta; nombre nulo no aporta -------------


def test_catalog_terms_sin_ticker_y_nombre_nulo():
    companies = [
        SimpleNamespace(ticker="", name="Acme Corp"),
        SimpleNamespace(ticker=None, name=None),
        SimpleNamespace(ticker="AAA", name=None),
    ]
    assert cas.catalog_terms(companies) == {"aaa": {"AAA"}}


# --- _tenant / store / ensure_aliases --------------------------------------


def test_tenant_sin_info_devuelve_none():
    db = _db()
    try:
        assert cas._tenant(db) is None
    finally:
        db.close()


def test_store_sin_tenant_es_noop():
    db = _db()
    try:
        record = AliasRecord(ticker="AAA", fuentes=["wikidata"])
        cas.store(db, [record])  # sin tenant en db.info: no escribe ni rompe
        assert cas.load_cached(db) == {}
    finally:
        db.close()


def test_ensure_aliases_sin_tenant_devuelve_vacio():
    db = _db()
    try:
        company = SimpleNamespace(ticker="AAA", name="Acme Corp", isin=None, id=None)
        assert cas.ensure_aliases(db, [company], get=_get_vacio) == {}
    finally:
        db.close()


def test_ensure_aliases_business_text_falla_hace_rollback_y_guarda(monkeypatch):
    db = _db()
    try:
        tenant = Tenant(id=7, external_id="t7", metadata_={"language": "es"})
        db.add(tenant)
        db.commit()
        db.info["tenant_id"] = 7

        def business_text_que_falla(db_, company_id, *, limit_chars=60_000):
            raise RuntimeError("documentos corruptos")

        monkeypatch.setattr(cas, "business_text", business_text_que_falla)
        company = SimpleNamespace(ticker="AAA", name="Acme Corp", isin=None, id=1)
        records = cas.ensure_aliases(db, [company], get=_get_vacio)

        assert records["AAA"].error == "sin_qid"
        assert records["AAA"].fuentes == ["wikidata"]
        # Pese al fallo de business_text, el registro quedó guardado en caché.
        assert set(cas.load_cached(db)) == {"AAA"}
    finally:
        db.close()


def test_build_record_texto_sin_inferencia_no_añade_fuente():
    # Texto presente pero sin términos repetidos que inferir → no se añade
    # la fuente de texto al registro (rama `if inferred:` falsa).
    company = SimpleNamespace(ticker="AAA", name="Acme Corp", isin=None, id=None)
    record = cas.build_record(
        company,
        get=_get_vacio,
        text="texto plano sin marcas repetidas ni entidades.",
        text_source="informe anual",
    )
    assert record.error == "sin_qid"
    assert record.fuentes == ["wikidata"]
    assert record.fetched_at
