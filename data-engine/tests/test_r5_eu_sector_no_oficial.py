"""Sector de reserva NO OFICIAL (Wikidata → Yahoo) para emisores sin clasificación oficial (r5-eu, 11-nov-2026).

Antes: Airbus, Intertek o SGS (sin sector, industria ni SIC de la SEC) salían de Piotroski/Altman con «Sector sin
clasificar» aunque sus cifras ESEF ya tengan fuente. Nico aprobó (11-nov 23:45) una clasificación de fuente gratuita
SOLO cuando no hay oficial, guardada con fuente y fecha y marcada «no oficial». Respuestas reales del 11-nov-2026:
Wikidata P452 de Airbus (NL0000235190) = spaceflight, arms industry, aviation, aircraft construction; Intertek
(GB0031638363) y SGS (CH0002497458) sin P452; Yahoo assetProfile ITRK.L sectorKey «industrials».
"""
import json
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, ConnectorState
from app.services import unofficial_sector as us
from app.services.financial_health import HealthFact, calculate_health

TODAY = date(2026, 11, 11)
NOW = datetime(2026, 11, 11, 22, 0, tzinfo=UTC)
AIRBUS_P452 = [("Q5916", "spaceflight"), ("Q392933", "arms industry"), ("Q765633", "aviation"),
               ("Q1434048", "aircraft construction")]


def _facts():
    values = {
        2023: {"total_assets": 100},
        2024: {"total_assets": 110, "net_income": 5, "long_term_debt": 30,
               "current_assets": 50, "current_liabilities": 30, "gross_profit": 30, "revenue": 100},
        2025: {"total_assets": 120, "net_income": 12, "long_term_debt": 20,
               "operating_cash_flow": 15, "current_assets": 70, "current_liabilities": 30,
               "gross_profit": 44, "revenue": 130, "common_stock_issued": 0,
               "retained_earnings": 40, "income_before_tax": 16, "interest_expense": 2,
               "total_equity": 70, "total_liabilities": 50},
    }
    out = []
    for year, metrics in values.items():
        for metric, value in metrics.items():
            out.append(HealthFact(len(out) + 1, metric, year, value, "GBP", date(year, 12, 31),
                                  "https://filings.xbrl.org/test", "ESEF", 1))
    return out


def _basis(sector="Industrials", source="Wikidata", reason=None):
    return us.health_basis({"sector": sector, "source": source, "source_url": "https://www.wikidata.org/wiki/Q2311",
                            "industry": "aviation", "checked_at": "2026-11-11", "reason": reason,
                            "rules_version": us.RULES_VERSION})


# -- reglas puras -------------------------------------------------------------------------------------------------

def test_wikidata_airbus_es_industrials_y_determinista():
    a = us.verdict_from_wikidata(AIRBUS_P452)
    b = us.verdict_from_wikidata(list(reversed(AIRBUS_P452)))
    assert a == b
    assert a["status"] == "ok" and a["sector"] == "Industrials"


def test_wikidata_ambigua_y_vacia_no_eligen():
    amb = us.verdict_from_wikidata([("Q1", "software industry"), ("Q2", "banking")])
    assert amb["status"] == "ambiguous" and amb["sector"] is None
    assert amb["candidates"] == ["Financials", "Information Technology"]
    # Una sola etiqueta que encaja en dos sectores también es ambigua.
    assert us.verdict_from_wikidata([("Q3", "coal mining")])["status"] == "ambiguous"
    assert us.verdict_from_wikidata([])["status"] == "missing"
    assert us.verdict_from_wikidata([("Q4", "activities of head offices")])["status"] == "missing"


def test_yahoo_por_sector_key():
    assert us.verdict_from_yahoo({"sectorKey": "industrials", "industry": "Specialty Business Services"})["sector"] \
        == "Industrials"
    assert us.verdict_from_yahoo({"sectorKey": "technology"})["sector"] == "Information Technology"
    assert us.verdict_from_yahoo({"sectorKey": "raro"})["status"] == "missing"
    assert us.verdict_from_yahoo(None)["status"] == "missing"


def test_decide_orden_y_discrepancia():
    wd_ok = us.verdict_from_wikidata(AIRBUS_P452)
    yh_tech = us.verdict_from_yahoo({"sectorKey": "technology"})
    assert us.decide(wd_ok, yh_tech)["source"] == "Wikidata"  # Wikidata primero
    missing = us.verdict_from_wikidata([])
    got = us.decide(missing, us.verdict_from_yahoo({"sectorKey": "industrials"}))
    assert got["sector"] == "Industrials" and got["source"] == "Yahoo Finance"
    amb = us.verdict_from_wikidata([("Q1", "software industry"), ("Q2", "banking")])
    assert us.decide(amb, yh_tech)["sector"] == "Information Technology"  # Yahoo deshace dentro de los candidatos
    out = us.decide(amb, us.verdict_from_yahoo({"sectorKey": "energy"}))
    assert out["sector"] is None and "discrepan" in out["reason"]
    none = us.decide(missing, us.verdict_from_yahoo(None))
    assert none["sector"] is None and "Wikidata" in none["reason"] and "Yahoo" in none["reason"]


# -- salud: la oficial manda, la no oficial se ve -----------------------------------------------------------------

def test_salud_con_sector_no_oficial_se_evalua_y_lo_dice():
    out = calculate_health(_facts(), sector="Unknown", company_type="operating", today=TODAY, industry="Unknown",
                           sic_sector=None, unofficial_sector=_basis())
    assert out["piotroski"]["score"] == 9
    assert out["altman"]["score"] is not None
    assert out["sector_basis"]["official"] is False and out["sector_basis"]["source"] == "Wikidata"
    assert "Sector no oficial: Industrials (según Wikidata, consultado el 11/11/2026)" in out["notice"]


def test_salud_la_oficial_manda_sobre_la_no_oficial():
    out = calculate_health(_facts(), sector="Financials", company_type="operating", today=TODAY,
                           unofficial_sector=_basis("Industrials"))
    assert out["reason"] == "Modelo no aplicable a financieras, REIT o empresas preingresos"
    assert "sector_basis" not in out and "no oficial" not in out["notice"]
    out = calculate_health(_facts(), sector="Unknown", company_type="operating", today=TODAY,
                           industry="Technology", unofficial_sector=_basis("Financials"))
    assert out["piotroski"]["score"] == 9 and "sector_basis" not in out


def test_salud_no_oficial_financiera_excluye_con_su_fuente():
    out = calculate_health(_facts(), sector="Unknown", company_type="operating", today=TODAY,
                           unofficial_sector=_basis("Financials", "Yahoo Finance"))
    assert out["reason"].startswith("Modelo no aplicable a financieras")
    assert "según Yahoo Finance" in out["reason"]


def test_salud_sin_respuesta_util_sigue_sin_clasificar_con_motivo():
    basis = us.health_basis({"sector": None, "reason": "Wikidata no tiene industria (P452) para este ISIN; "
                             "Yahoo no da perfil para este símbolo", "checked_at": "2026-11-11"})
    out = calculate_health(_facts(), sector="Unknown", company_type="operating", today=TODAY, unofficial_sector=basis)
    assert out["reason"].startswith("Sector sin clasificar: Wikidata no tiene industria")
    assert out["piotroski"]["score"] is None


# -- red y caché (transporte en proceso, sin red real) -------------------------------------------------------------

@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def _company(db, ticker="AIR.PA", name="Airbus SE", isin="NL0000235190", **kw):
    c = Company(ticker=ticker, name=name, exchange="EPA", currency="EUR", sector=kw.get("sector", "Unknown"),
                industry=kw.get("industry", "Unknown"), cik=kw.get("cik"), isin=isin, factor_tags=[],
                company_type="operating", valuation_model="unassigned", special_sources=[], special_risks=[])
    db.add(c)
    db.commit()
    return c


def _transport(calls, *, wikidata=None, yahoo=None, wikidata_status=200):
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.host)
        if request.url.host == "query.wikidata.org":
            if wikidata_status != 200:
                return httpx.Response(wikidata_status, headers={"Retry-After": "120"})
            rows = [{"item": {"value": "http://www.wikidata.org/entity/Q2311"},
                     **({"ind": {"value": f"http://www.wikidata.org/entity/{q}"}, "indLabel": {"value": lbl}}
                        if q else {})} for q, lbl in (wikidata or [(None, None)])]
            return httpx.Response(200, json={"results": {"bindings": rows}})
        if request.url.host == "fc.yahoo.com":
            return httpx.Response(404)
        if request.url.path.endswith("/getcrumb"):
            return httpx.Response(200, text="abcCRUMB1")
        if "quoteSummary" in request.url.path:
            return httpx.Response(200, json={"quoteSummary": {"result": [yahoo]}})
        return httpx.Response(500)
    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.fixture(autouse=True)
def _sin_paradas():
    us._HALTED.clear()
    yield
    us._HALTED.clear()


def test_refresh_guarda_fuente_y_fecha_y_usa_cache(db):
    c = _company(db)
    calls: list[str] = []
    client = _transport(calls, wikidata=AIRBUS_P452)
    got = us.refresh(db, c, client=client, now=NOW)
    assert got["sector"] == "Industrials" and got["source"] == "Wikidata" and got["official"] is False
    assert got["checked_at"] == "2026-11-11" and got["source_url"] == "https://www.wikidata.org/wiki/Q2311"
    assert calls == ["query.wikidata.org"]  # Wikidata decide: Yahoo ni se consulta
    db.commit()
    assert us.refresh(db, c, client=client, now=NOW + timedelta(days=10))["sector"] == "Industrials"
    assert calls == ["query.wikidata.org"]  # caché: ninguna consulta más
    assert us.stored(db, [c.id])[c.id]["sector"] == "Industrials"
    company_row = db.get(Company, c.id)
    assert company_row is not None and company_row.sector == "Unknown"  # nunca escribe el sector oficial


def test_refresh_cae_a_yahoo_con_identidad(db):
    c = _company(db, "ITRK.L", "Intertek Group plc", "GB0031638363")
    calls: list[str] = []
    yahoo = {"assetProfile": {"sectorKey": "industrials", "industry": "Specialty Business Services"},
             "price": {"longName": "Intertek Group plc"}}
    got = us.refresh(db, c, client=_transport(calls, wikidata=None, yahoo=yahoo), now=NOW)
    assert got["sector"] == "Industrials" and got["source"] == "Yahoo Finance"
    assert got["industry"] == "Specialty Business Services"
    assert got["source_url"] == "https://finance.yahoo.com/quote/ITRK.L/profile"


def test_refresh_yahoo_de_otra_empresa_no_vale(db):
    c = _company(db, "ITRK.L", "Intertek Group plc", "GB0031638363")
    yahoo = {"assetProfile": {"sectorKey": "technology"}, "price": {"longName": "Otra Cosa Ltd"}}
    got = us.refresh(db, c, client=_transport([], wikidata=None, yahoo=yahoo), now=NOW)
    assert got["sector"] is None and "otra empresa" in got["reason"]


def test_refresh_429_para_la_fuente_sin_reintentar(db):
    c = _company(db)
    calls: list[str] = []
    yahoo = {"assetProfile": {"sectorKey": "industrials"}, "price": {"longName": "Airbus SE"}}
    client = _transport(calls, yahoo=yahoo, wikidata_status=429)
    got = us.refresh(db, c, client=client, now=NOW)
    assert got["sector"] == "Industrials" and got["source"] == "Yahoo Finance"
    assert calls.count("query.wikidata.org") == 1  # una sola petición, sin bucle
    other = _company(db, "SGSN.SW", "SGS SA", "CH0002497458")
    us.refresh(db, other, client=client, now=NOW)
    assert calls.count("query.wikidata.org") == 1  # fuente detenida tras el 429


def test_refresh_solo_sin_clasificacion_oficial_y_con_isin(db):
    calls: list[str] = []
    client = _transport(calls, wikidata=AIRBUS_P452)
    assert us.refresh(db, _company(db, "BVI.PA", "Bureau Veritas", "FR0006174348",
                                   industry="Commercial Services & Supplies"), client=client, now=NOW) is None
    assert us.refresh(db, _company(db, "X1", "Sin isin", None), client=client, now=NOW) is None
    assert us.refresh(db, _company(db, "TSM", "TSMC", "US8740391003"), client=client, now=NOW,
                      sic_sector="manufactura") is None
    assert calls == []


def test_enrich_llama_a_la_reserva_solo_si_se_pide(db):
    from app.services.company_enrichment_service import CompanyEnrichmentService

    c = _company(db)
    finnhub = httpx.Client(transport=httpx.MockTransport(lambda _r: httpx.Response(200, json={})))
    settings = SimpleNamespace(finnhub_api_key=None)
    CompanyEnrichmentService(settings=settings, client=finnhub, sic_lookup=lambda _c: (None, None)).enrich(db, c)
    assert db.scalars(select(ConnectorState)).all() == []  # cliente de test sin pedirlo: sin red
    calls: list[str] = []
    svc = CompanyEnrichmentService(settings=settings, client=finnhub, sic_lookup=lambda _c: (None, None),
                                   unofficial_client=_transport(calls, wikidata=AIRBUS_P452))
    svc.enrich(db, c)
    db.commit()
    state = db.scalars(select(ConnectorState).where(ConnectorState.connector == us.CONNECTOR)).one()
    assert state.metadata_["sector"] == "Industrials"
    assert db.get(Company, c.id).sector == "Unknown"
    json.dumps(state.metadata_)  # serializable


def test_build_summaries_usa_el_sector_guardado(monkeypatch):
    import app.services.valuation_summary as vs

    seen = {}

    def fake(facts, **kw):
        seen.update(kw)
        return {"status": "not_evaluable", "reason": "x", "piotroski": {}, "altman": {}, "notice": ""}

    monkeypatch.setattr(vs, "calculate_health", fake)
    monkeypatch.setattr(vs, "resolve_fair_values", lambda db, companies, today=None: {c.id: {} for c in companies})
    monkeypatch.setattr(vs, "cash_burn_base_rate", lambda *a, **k: None)
    monkeypatch.setattr(vs, "tenant_filters", lambda *a, **k: [])
    monkeypatch.setattr(vs.unofficial_sector, "stored", lambda db, ids: {1: {
        "sector": "Industrials", "source": "Wikidata", "checked_at": "2026-11-11",
        "source_url": "https://www.wikidata.org/wiki/Q2311", "rules_version": us.RULES_VERSION}})

    class _Result(list):
        def all(self):
            return list(self)

    class _DB:
        info = {}

        def scalars(self, *_a, **_k):
            return _Result()

    class _Co:
        id, ticker, sector, industry, company_type, cik = 1, "AIR.PA", "Unknown", "Unknown", "operating", None

    vs.build_summaries(_DB(), [_Co()], today=TODAY)  # type: ignore[arg-type]
    assert seen["unofficial_sector"]["sector"] == "Industrials"
    assert seen["unofficial_sector"]["official"] is False
    assert "Wikidata" in seen["unofficial_sector"]["label"]


def test_stored_lee_solo_la_version_vigente(db):
    c = _company(db)
    db.add(ConnectorState(connector=us.CONNECTOR, company_id=c.id, consecutive_errors=0,
                          metadata_={"sector": "Industrials", "rules_version": "vieja"}))
    db.commit()
    assert us.stored(db, [c.id]) == {}
