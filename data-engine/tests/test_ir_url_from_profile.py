"""weburl de Finnhub profile2 -> Company.ir_url (via oficial de informes).

Sin ir_url la ficha de un emisor sin SEC (Fairfax FFH.TO, Sagicor SFC.TO)
no tiene informes oficiales: issuer_reports responde «sin_ir_url» y la tesis
se queda sin documentos del emisor. profile2 ya se pide a diario (backfill)
y en el alta (enrich) y devuelve la web oficial del emisor; se descartaba.

Reglas (identidad primero, como el resto de la capa):
- Solo se promueve si el perfil es del LISTADO pedido: Finnhub devuelve en
  ``ticker`` el instrumento que resolvio; si difiere del pedido (ADR, otro
  emisor) la web seria de otro.
- Con bolsa placeholder el listado no esta verificado (homonimos: ALM de
  Almirall -> Almonty): no se promueve; el backfill la deja en
  ``adr_candidates`` para revision.
- Nunca pisa una ir_url existente; sin weburl http(s) valida no hay cambio.
"""


import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, Document
from app.services.company_enrichment_service import CompanyEnrichmentService, profile_ir_url
from app.services.finnhub_profile_backfill import FinnhubProfileBackfill


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


class _Resp:
    def __init__(self, data, status=200):
        self._data = data
        self.status_code = status

    def json(self):
        return self._data


class _Client:
    def __init__(self, profiles=None, quotes=None):
        self.profiles = profiles or {}
        self.quotes = quotes or {}

    def get(self, url, params=None):
        ticker = (params or {}).get("symbol", "")
        if "/quote" in url:
            return _Resp(self.quotes.get(ticker) or {})
        return _Resp(self.profiles.get(ticker) or {})

    def close(self):
        pass


class _Settings:
    finnhub_api_key = "test-key"


TSX_PROFILE = {
    "ticker": "FFH.TO", "name": "Fairfax Financial Holdings Ltd",
    "exchange": "TORONTO STOCK EXCHANGE", "currency": "CAD", "country": "CA",
    "finnhubIndustry": "Insurance", "weburl": "https://www.fairfax.ca/",
}


def _company(db: Session, ticker: str, **overrides) -> Company:
    company = Company(
        ticker=ticker, name=ticker, exchange="UNKNOWN", currency="USD",
        sector="", industry="", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    for key, value in overrides.items():
        setattr(company, key, value)
    db.add(company)
    db.commit()
    return company


# -- helper puro ---------------------------------------------------------------

def test_profile_ir_url_exige_eco_del_ticker_pedido():
    assert profile_ir_url(TSX_PROFILE, "FFH.TO") == "https://www.fairfax.ca/"
    # El perfil resolvio OTRO instrumento (ADR americano de Fairfax).
    assert profile_ir_url({**TSX_PROFILE, "ticker": "FRFHF"}, "FFH.TO") is None
    # Sin eco de ticker no hay prueba de identidad.
    assert profile_ir_url({k: v for k, v in TSX_PROFILE.items() if k != "ticker"}, "FFH.TO") is None


def test_profile_ir_url_exige_http_y_cabe_en_la_columna():
    assert profile_ir_url({**TSX_PROFILE, "weburl": "ftp://fairfax.ca"}, "FFH.TO") is None
    assert profile_ir_url({**TSX_PROFILE, "weburl": ""}, "FFH.TO") is None
    assert profile_ir_url({**TSX_PROFILE, "weburl": "https://x.co/" + "a" * 600}, "FFH.TO") is None
    assert profile_ir_url(None, "FFH.TO") is None


# -- backfill diario -----------------------------------------------------------

def _backfill(db, company, profiles):
    client = _Client(profiles=profiles)
    service = FinnhubProfileBackfill(settings=_Settings(), client=client)
    return service.backfill(db, max_companies=5, sleep_between_calls=0), client


def test_backfill_promueve_weburl_con_listado_verificado(db):
    company = _company(db, "FFH.TO", exchange="TORONTO STOCK EXCHANGE", currency="CAD",
                       name="Fairfax Financial Holdings Ltd")
    stats, _ = _backfill(db, company, {"FFH.TO": TSX_PROFILE})
    db.refresh(company)
    assert company.ir_url == "https://www.fairfax.ca/"
    doc = db.scalar(select(Document).where(Document.source_type == "finnhub_profile"))
    assert "ir_url" in doc.metadata_["fields"]


def test_backfill_con_bolsa_placeholder_no_promueve_y_deja_candidato(db):
    company = _company(db, "FFH.TO", exchange="UNKNOWN")
    _backfill(db, company, {"FFH.TO": TSX_PROFILE})
    db.refresh(company)
    assert company.ir_url is None
    doc = db.scalar(select(Document).where(Document.source_type == "finnhub_profile"))
    assert doc.metadata_["adr_candidates"].get("weburl") == "https://www.fairfax.ca/"


def test_backfill_no_pisa_ir_url_existente(db):
    company = _company(db, "FFH.TO", exchange="TORONTO STOCK EXCHANGE", currency="CAD",
                       name="Fairfax Financial Holdings Ltd", ir_url="https://ir.fairfax.example/")
    _backfill(db, company, {"FFH.TO": TSX_PROFILE})
    db.refresh(company)
    assert company.ir_url == "https://ir.fairfax.example/"


def test_backfill_perfil_de_otro_instrumento_no_promueve(db):
    company = _company(db, "FFH.TO", exchange="TORONTO STOCK EXCHANGE", currency="CAD",
                       name="Fairfax Financial Holdings Ltd")
    _backfill(db, company, {"FFH.TO": {**TSX_PROFILE, "ticker": "FRFHF"}})
    db.refresh(company)
    assert company.ir_url is None


# -- enrich en el alta ----------------------------------------------------------

def test_enrich_promueve_weburl_con_bolsa_verificada(db):
    company = _company(db, "FFH.TO", exchange="TORONTO STOCK EXCHANGE", currency="CAD",
                       name="Fairfax Financial Holdings Ltd", sector="Unknown")
    service = CompanyEnrichmentService(settings=_Settings(), client=_Client(profiles={"FFH.TO": TSX_PROFILE}))
    assert service.needs_enrichment(company)  # sector en placeholder
    service.enrich(db, company)
    # enrich no commitea (decision del caller); el atributo queda en la sesion.
    assert company.ir_url == "https://www.fairfax.ca/"


def test_enrich_con_bolsa_placeholder_no_promueve_aunque_fije_la_bolsa(db):
    company = _company(db, "FFH.TO", exchange="UNKNOWN")
    service = CompanyEnrichmentService(settings=_Settings(), client=_Client(profiles={"FFH.TO": TSX_PROFILE}))
    service.enrich(db, company)
    assert company.exchange == "TORONTO STOCK EXCHANGE"
    assert company.ir_url is None
