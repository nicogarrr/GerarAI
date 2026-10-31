"""Contratos de CompanyEnrichmentService que faltaban: consulta a Finnhub
(profile2 con fallback a /search), cooldown/marca de intento, enrich_all,
fill_default_currency y ensure_company_stub.

Los clientes HTTP son fakes que solo graban llamadas; el contrato probado es
el real: sin clave no hay llamada, un profile2 sin datos cae a /search, y la
divisa de reserva sale del sufijo del ticker sin pisar la declarada.
"""

from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company
from app.services.company_enrichment_service import (
    CompanyEnrichmentService,
    ensure_company_stub,
    fill_default_currency,
    sector_for_industry,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


class _Settings:
    finnhub_api_key = "test-key"


class _NoKeySettings:
    finnhub_api_key = None


class _Resp:
    def __init__(self, data, status=200):
        self._data = data
        self.status_code = status

    def json(self):
        return self._data


class _Client:
    """Fake por URL: profile2/search devuelven lo configurado y graban llamadas."""

    def __init__(self, profile=None, search=None, profile_status=200, search_status=200, boom=False):
        self._profile = profile
        self._search = search
        self._profile_status = profile_status
        self._search_status = search_status
        self._boom = boom
        self.calls = []
        self.closed = False

    def get(self, url, params=None):
        self.calls.append((url, params))
        if self._boom:
            raise httpx.ConnectError("red caida", request=httpx.Request("GET", url))
        if "profile2" in url:
            return _Resp(self._profile, self._profile_status)
        return _Resp(self._search, self._search_status)

    def close(self):
        self.closed = True


def _company(db: Session, **kw) -> Company:
    defaults = dict(
        ticker="XYZ", name="XYZ", exchange="UNKNOWN", currency="",
        sector="Unknown", industry="Unknown", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    defaults.update(kw)
    company = Company(**defaults)
    db.add(company)
    db.commit()
    return company


def test_sector_for_industry_none_y_desconocida():
    assert sector_for_industry(None) is None
    assert sector_for_industry("") is None
    assert sector_for_industry("Industria No Mapeada") is None


def test_close_cierra_el_cliente():
    client = _Client()
    svc = CompanyEnrichmentService(settings=_Settings(), client=client)
    svc.close()
    assert client.closed is True


def test_profile_sin_clave_no_llama_a_la_api():
    client = _Client(profile={"name": "X"})
    svc = CompanyEnrichmentService(settings=_NoKeySettings(), client=client)
    assert svc._finnhub_profile("XYZ") is None
    assert client.calls == []


def test_profile_sin_datos_cae_a_search():
    client = _Client(
        profile={},
        search={"result": [{"symbol": "ADUR", "description": "Aduro Clean Technologies Inc"}]},
    )
    svc = CompanyEnrichmentService(settings=_Settings(), client=client)
    assert svc._finnhub_profile("ADUR") == {"name": "Aduro Clean Technologies Inc"}
    urls = [u for u, _ in client.calls]
    assert any("profile2" in u for u in urls) and any("search" in u for u in urls)


def test_profile_error_http_cae_a_search():
    client = _Client(profile_status=500, search={"result": [{"symbol": "X", "description": "X Corp"}]})
    svc = CompanyEnrichmentService(settings=_Settings(), client=client)
    assert svc._finnhub_profile("X") == {"name": "X Corp"}


def test_profile_error_de_red_cae_a_search():
    client = _Client(boom=True)
    svc = CompanyEnrichmentService(settings=_Settings(), client=client)
    assert svc._finnhub_profile("XYZ") is None  # profile2 y search fallan: sin datos


def test_search_requiere_symbol_exacto_y_descripcion():
    client = _Client(profile={}, search={"result": [
        {"symbol": "OTRO", "description": "Otra Empresa"},
        {"symbol": "XYZ", "description": "   "},
    ]})
    svc = CompanyEnrichmentService(settings=_Settings(), client=client)
    assert svc._finnhub_profile("XYZ") is None  # ni simbolo distinto ni descripcion vacia valen


def test_search_no_200_es_none():
    client = _Client(profile={}, search_status=403)
    svc = CompanyEnrichmentService(settings=_Settings(), client=client)
    assert svc._finnhub_profile("XYZ") is None


def test_enrich_sin_perfil_marca_intento_y_no_cambia(db):
    client = _Client(profile={}, search={"result": []})
    svc = CompanyEnrichmentService(settings=_Settings(), client=client)
    company = _company(db)
    assert svc.enrich(db, company) is False
    assert company.enrichment_attempted_at is not None  # el intento fallido tambien cuenta
    assert company.name == "XYZ" and company.exchange == "UNKNOWN"


def test_enrich_rellena_exchange_y_divisa_en_placeholder(db):
    client = _Client(profile={"name": "Acme Corp", "exchange": "NASDAQ", "currency": "USD"})
    svc = CompanyEnrichmentService(settings=_Settings(), client=client)
    company = _company(db, name="Acme Corp", ticker="ACME")  # nombre ya bueno; exchange/divisa no
    assert svc.enrich(db, company) is True
    assert company.exchange == "NASDAQ"
    assert company.currency == "USD"
    assert company.name == "Acme Corp"


def test_enrich_no_pisa_divisa_declarada(db):
    client = _Client(profile={"name": "Acme Corp", "exchange": "NASDAQ", "currency": "GBX"})
    svc = CompanyEnrichmentService(settings=_Settings(), client=client)
    company = _company(db, ticker="ACME", currency="DKK")
    svc.enrich(db, company)
    assert company.currency == "DKK"  # la divisa del proveedor no pisa la existente


def test_enrich_all_cuenta_y_commitea(db, monkeypatch):
    ok = _company(db, ticker="OK1", name="Ok Corp", exchange="NYSE", currency="USD", sector="Tech", industry="Tech")
    _company(db, ticker="E1", name="E1")          # enriquecible
    _company(db, ticker="N1", name="N1")          # sin datos en la API
    client = _Client(
        profile={"name": "E Uno Corp", "exchange": "NASDAQ", "currency": "USD"},
        search={"result": []},
    )

    class _PerTicker:
        def __init__(self):
            self.svc = CompanyEnrichmentService(settings=_Settings(), client=client)

        def get(self, url, params=None):
            if (params or {}).get("symbol") == "N1" or (params or {}).get("q") == "N1":
                return _Resp({}, 200) if "profile2" in url else _Resp({"result": []}, 200)
            return client.get(url, params=params)

        def close(self):
            pass

    svc = CompanyEnrichmentService(settings=_Settings(), client=_PerTicker())
    out = svc.enrich_all(db, sleep_between=0)
    assert out == {"total": 3, "enriched": 1, "already_ok": 1, "api_sin_datos": 1}
    db.expire_all()
    assert db.scalar(db.query(Company).filter_by(ticker="E1").statement).name == "E Uno Corp"


def test_enrich_all_todo_ok_no_commitea_ni_llama(db):
    _company(db, ticker="OK1", name="Ok Corp", exchange="NYSE", currency="USD", sector="Tech", industry="Tech")
    client = _Client(profile={"name": "X"})
    svc = CompanyEnrichmentService(settings=_Settings(), client=client)
    out = svc.enrich_all(db, sleep_between=0)
    assert out == {"total": 1, "enriched": 0, "already_ok": 1, "api_sin_datos": 0}
    assert client.calls == []  # needs_enrichment False: la API no se consulta


def test_fill_default_currency_por_sufijo_y_no_pisa():
    company = Company(
        ticker="MAERSK-B.CO", name="Maersk", exchange="CPH", currency="",
        sector="Industrials", industry="Marine", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    fill_default_currency(company)
    assert company.currency == "DKK"
    company2 = Company(
        ticker="CGEO.L", name="CGEO", exchange="LSE", currency="",
        sector="Financials", industry="Asset Management", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    fill_default_currency(company2)
    assert company2.currency == "GBX"
    company3 = Company(
        ticker="PLAIN", name="Plain", exchange="NYSE", currency="",
        sector="Tech", industry="Tech", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    fill_default_currency(company3)
    assert company3.currency == "USD"
    company3.currency = "EUR"
    fill_default_currency(company3)
    assert company3.currency == "EUR"  # nunca pisa la divisa ya puesta


def test_ensure_company_stub_devuelve_la_existente(db):
    existing = _company(db, ticker="EXISTE", name="Ya existe Corp")
    assert ensure_company_stub(db, "  existe  ") is existing  # strip + upper


def test_ensure_company_stub_crea_stub_y_divisa_de_reserva(db):
    company = ensure_company_stub(db, "NUEVO1")
    assert company.ticker == "NUEVO1"
    assert company.name == "NUEVO1"          # placeholder: el enriquecimiento lo rellena
    assert company.exchange == "UNKNOWN"
    # divisa de reserva por sufijo (sin sufijo conocido -> USD): nunca queda vacia
    assert company.currency == "USD"
    assert company.company_type == "research_candidate"
    assert db.scalar(db.query(Company).filter_by(ticker="NUEVO1").statement) is not None


def test_ensure_company_stub_divisa_por_sufijo_del_ticker(db):
    company = ensure_company_stub(db, "MAERSK-B.CO")
    assert company.currency == "DKK"         # el sufijo manda, no un USD por defecto


def test_ensure_company_stub_sobrevive_a_enrich_fallido(db, monkeypatch):
    def boom(self, db_, company):
        raise RuntimeError("finnhub caido")

    monkeypatch.setattr(CompanyEnrichmentService, "enrich", boom)
    company = ensure_company_stub(db, "NUEVO2")  # el ensure nunca falla por el proveedor
    assert company.ticker == "NUEVO2"
