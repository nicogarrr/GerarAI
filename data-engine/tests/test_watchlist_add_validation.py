"""Alta en watchlist solo para empresas que existen (prod 3-nov-2026: «GOOGLE»).

Un símbolo que el proveedor no conoce se rechaza con 422 sin crear fila ni
encolar trabajos; los alias se guardan con su ticker canónico y, si ya estaban,
se devuelve la fila existente; un ticker válido sigue encolando la tesis.
"""
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

import main
from app.core import auth as auth_module
from app.core.database import SessionLocal, init_db
from app.models import Company, WatchItem
from app.seed import seed
from app.services import listing_identity
from app.services import watchlist_ticker_validation as wtv
from tests.auth_helpers import auth_settings, signed_request

SECRET = "watchlist-add-validation-secret"


@pytest.fixture()
def jobs(monkeypatch):
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr("app.api.routes.watchlist.enqueue_tracked_analysis",
                        lambda db, symbol: calls.append(("thesis", symbol)))
    monkeypatch.setattr("app.api.routes.watchlist.enqueue_fundamentals_seed",
                        lambda db, symbol: calls.append(("seed", symbol)))
    monkeypatch.setattr("app.api.routes.watchlist.enqueue_dca_on_add",
                        lambda db, symbols, **_: calls.append(("dca", ",".join(symbols))))
    monkeypatch.setattr("app.api.routes.watchlist.enqueue_market_data_on_add",
                        lambda db, symbol: calls.append(("data", symbol)))
    return calls


@pytest.fixture()
def probes(monkeypatch):
    """Producción simulada: la consulta al proveedor responde según ``answers``."""
    answers: dict[str, wtv.ProbeResult] = {}
    asked: list[str] = []

    def fake_probe(symbol, **_):
        asked.append(symbol)
        return answers.get(symbol, wtv.ProbeResult(exists=False))

    monkeypatch.setattr(wtv, "_network_enabled", lambda: True)
    monkeypatch.setattr(wtv, "probe_yahoo", fake_probe)
    return answers, asked


@pytest.fixture()
def call(monkeypatch):
    init_db()
    seed()
    monkeypatch.setattr(
        auth_module, "get_settings", lambda: auth_settings(strict=True, secret=SECRET, app_env="test")
    )
    suffix = uuid4().hex[:8]
    client = TestClient(main.app, raise_server_exceptions=False)

    def _call(method, path, json_body=None):
        return signed_request(client, SECRET, f"wv-{suffix}", f"user-wv-{suffix}", method, path, json_body=json_body)

    return _call


def _symbols(call) -> list[str]:
    return [item["symbol"] for item in call("GET", "/api/watchlist").json()]


def test_ticker_inexistente_da_422_sin_fila_ni_trabajos(call, jobs, probes):
    symbol = f"ZQ{uuid4().hex[:4].upper()}"
    response = call("POST", "/api/watchlist", {"symbol": symbol})
    assert response.status_code == 422, response.text
    assert response.json()["detail"] == f"No encontramos la empresa «{symbol}». Revisa el ticker."
    assert symbol not in _symbols(call)
    assert jobs == []
    assert probes[1] == [symbol]


def test_errata_de_un_ticker_del_catalogo_sugiere_el_bueno(call, jobs, probes):
    response = call("POST", "/api/watchlist", {"symbol": "NFLXX"})
    assert response.status_code == 422
    assert "¿quizá NFLX?" in response.json()["detail"]
    assert jobs == []


def test_marca_verificada_se_guarda_con_su_ticker(call, jobs, probes):
    response = call("POST", "/api/watchlist", {"symbol": "facebook"})
    assert response.status_code == 201, response.text
    assert response.json()["symbol"] == "META"
    assert _symbols(call) == ["META"]
    assert ("thesis", "META") in jobs and ("data", "META") in jobs


def test_nombre_de_empresa_del_catalogo_se_normaliza(call, jobs, probes):
    response = call("POST", "/api/watchlist", {"symbol": "NETFLIX"})
    assert response.status_code == 201, response.text
    assert response.json()["symbol"] == "NFLX"


def test_alias_de_algo_ya_seguido_devuelve_la_fila_existente(call, jobs, probes):
    first = call("POST", "/api/watchlist", {"symbol": "META"})
    assert first.status_code == 201
    jobs.clear()
    again = call("POST", "/api/watchlist", {"symbol": "FACEBOOK"})
    assert again.status_code == 201
    assert again.json()["id"] == first.json()["id"]
    assert _symbols(call) == ["META"]
    assert jobs == []  # no es un alta nueva: nada se vuelve a encolar


def test_google_apunta_a_googl():
    assert wtv._brand_targets("GOOGLE")[0] == "GOOGL"


def test_ticker_del_catalogo_no_consulta_al_proveedor_y_encola_la_tesis(call, jobs, probes):
    response = call("POST", "/api/watchlist", {"symbol": "msft"})
    assert response.status_code == 201
    assert response.json()["symbol"] == "MSFT"
    assert probes[1] == []
    assert jobs[0] == ("thesis", "MSFT")


def test_ticker_real_fuera_del_catalogo_se_acepta_y_encola_la_tesis(call, jobs, probes):
    symbol = f"ZR{uuid4().hex[:4].upper()}.MC"
    probes[0][symbol] = wtv.ProbeResult(exists=True, name="Empresa Real, S.A.")
    response = call("POST", "/api/watchlist", {"symbol": symbol})
    assert response.status_code == 201, response.text
    assert response.json()["symbol"] == symbol
    assert ("thesis", symbol) in jobs and ("seed", symbol) in jobs


def test_proveedor_caido_no_bloquea_el_alta(call, jobs, probes):
    symbol = f"ZS{uuid4().hex[:4].upper()}"
    probes[0][symbol] = wtv.ProbeResult(exists=None)
    assert call("POST", "/api/watchlist", {"symbol": symbol}).status_code == 201
    assert ("thesis", symbol) in jobs


def test_fuera_de_produccion_no_hay_red_y_se_acepta_como_antes(call, jobs, monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("sin red fuera de producción")

    monkeypatch.setattr(wtv, "probe_yahoo", boom)
    symbol = f"ZT{uuid4().hex[:4].upper()}"
    assert call("POST", "/api/watchlist", {"symbol": symbol}).status_code == 201
    assert symbol in _symbols(call)


def test_ficha_minima_con_isin_revisado_va_al_listado(call, jobs, probes, monkeypatch):
    base = f"ZB{uuid4().hex[:4].upper()}"
    isin = f"XX{uuid4().hex[:10].upper()}"
    listing = listing_identity.ListingIdentity(
        isin=isin, name="Listado Revisado N.V.", ticker=f"{base}.AS", exchange="EURONEXT AMSTERDAM",
        currency="EUR", yahoo=f"{base}.AS", stooq="", source="test",
    )
    monkeypatch.setitem(listing_identity.BY_ISIN, isin, listing)
    db = SessionLocal()
    try:
        db.add(Company(
            ticker=base, name=base, exchange="UNKNOWN", currency="USD", isin=isin,
            sector="Unknown", industry="Unknown", company_type="imported_holding",
            valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
        ))
        db.commit()
        response = call("POST", "/api/watchlist", {"symbol": base})
        assert response.status_code == 201, response.text
        assert response.json()["symbol"] == f"{base}.AS"
        assert probes[1] == []
    finally:
        db.query(WatchItem).filter(WatchItem.symbol == f"{base}.AS").delete()
        company = db.scalar(select(Company).where(Company.ticker == base))
        if company is not None:
            db.delete(company)
        db.commit()
        db.close()


def test_ficha_minima_sin_precios_no_cuenta_como_empresa_real(call, jobs, probes):
    symbol = f"ZG{uuid4().hex[:4].upper()}"
    db = SessionLocal()
    try:
        db.add(Company(
            ticker=symbol, name=symbol, exchange="UNKNOWN", currency="", sector="Unknown",
            industry="Unknown", company_type="research_candidate", valuation_model="unassigned",
            special_sources=[], special_risks=[], factor_tags=[],
        ))
        db.commit()
        assert call("POST", "/api/watchlist", {"symbol": symbol}).status_code == 422
        assert jobs == []
    finally:
        company = db.scalar(select(Company).where(Company.ticker == symbol))
        if company is not None:
            db.delete(company)
        db.commit()
        db.close()


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (404, {"chart": {"result": None, "error": {"code": "Not Found"}}}, False),
        (200, {"chart": {"result": [{"meta": {"symbol": "GOOGL", "longName": "Alphabet Inc."}}]}}, True),
        (200, {"chart": {"result": []}}, False),
        (429, {}, None),
        (500, {}, None),
    ],
)
def test_consulta_al_proveedor(monkeypatch, status, body, expected):
    def fake_get(url, **kwargs):
        assert kwargs["timeout"] <= 3.0
        return httpx.Response(status, json=body, request=httpx.Request("GET", url))

    monkeypatch.setattr("app.services.connectors.yahoo.httpx.get", fake_get)
    result = wtv.probe_yahoo("GOOGL")
    assert result.exists is expected
    if expected:
        assert result.name == "Alphabet Inc."


def test_consulta_al_proveedor_sin_red(monkeypatch):
    def timeout(url, **_):
        raise httpx.ConnectTimeout("lento", request=httpx.Request("GET", url))

    monkeypatch.setattr("app.services.connectors.yahoo.httpx.get", timeout)
    assert wtv.probe_yahoo("GOOGL").exists is None
