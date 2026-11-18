"""CNMV PS v3: arreglos de la auditoria del 18-nov (NO FAV funcional) y
cobertura del connector a 100% de lo nuevo.

(1) Deriva silenciosa: tabla de accionistas sin filas tbody lanza ParseError
    salvo declaracion explicita «No hay datos para mostrar».
(2) Retry-After se obedece INTEGRO: un Retry-After: 3600 marca un cooldown
    de 3600 s (antes se recortaba a 300 s).
(3) El pacer «cnmv» es una unica instancia compartida con NOD
    (app/services/connectors/cnmv_pacer.py).
"""

import time
from datetime import date
from email.utils import formatdate
from pathlib import Path

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models.entities import Base, Company, Tenant
from app.services import cnmv_ps_ingestion
from app.services.connectors import cnmv_nod, cnmv_ps

FIXTURE = (
    Path(__file__).parent / "fixtures" / "cnmv" / "ps_notificaciones_acerinox_2026-11.html"
).read_text(encoding="utf-8")

_SEARCH_HTML = '<html><body><input name="__VIEWSTATE" value="v1"/></body></html>'
_RESULTS_TWO = (
    '<html><body><input name="__VIEWSTATE" value="v2"/>'
    '<select name="ctl00$ContentPrincipal$wbusqueda$lstSeleccion">'
    '<option value="A28001895">ACS, S.A.</option>'
    '<option value="A87494772">ACS, S.A.</option>'
    "</select></body></html>"
)
_LANDING = (
    '<html><body><a href="/Portal/consultas/DerechosVoto/Notificaciones-Participaciones'
    '.aspx?qS={11111111-2222-3333-4444-555555555555}">ver</a></body></html>'
)
_LANDING_NO_QS = "<html><body><p>sin enlace de sesion</p></body></html>"
_PAGE_NO_DATA = (
    '<html><body><span id="ctl00_lblSubtitulo">ACS, S.A.</span>'
    "No hay datos para mostrar</body></html>"
)


# ---- (3) pacer compartido ----


def test_throttle_uses_the_shared_pacer(monkeypatch):
    calls = []
    monkeypatch.setattr(cnmv_ps._pacer, "wait_sync", lambda: calls.append(1))
    cnmv_ps._throttle()
    assert calls == [1]
    assert cnmv_ps._pacer is cnmv_nod._pacer  # una sola instancia para cnmv.es


# ---- (2) Retry-After integro ----


def test_retry_after_not_shortened(monkeypatch):
    cooldowns: list[float] = []
    monkeypatch.setattr(cnmv_ps._pacer, "cool_down", lambda s: cooldowns.append(s))
    cnmv_ps._respect_retry_after(httpx.Response(429, headers={"Retry-After": "3600"}))
    assert cooldowns == [3600.0]  # antes: [300.0] (recortado)


def test_retry_after_absent_or_http_date_or_garbage(monkeypatch):
    cooldowns: list[float] = []
    monkeypatch.setattr(cnmv_ps._pacer, "cool_down", lambda s: cooldowns.append(s))
    cnmv_ps._respect_retry_after(httpx.Response(200))  # sin cabecera: nada
    assert cooldowns == []
    future = formatdate(time.time() + 120, usegmt=True)
    cnmv_ps._respect_retry_after(httpx.Response(503, headers={"Retry-After": future}))
    assert 100.0 < cooldowns[0] <= 120.0
    cnmv_ps._respect_retry_after(httpx.Response(429, headers={"Retry-After": "soon"}))
    assert cooldowns[1] == 60.0  # formato irreconocible: prudencia fija


# ---- _viewstate / _result_issuers ----


def test_viewstate_missing_raises():
    with pytest.raises(cnmv_ps.CNMVPSParseError, match="__VIEWSTATE"):
        cnmv_ps._viewstate("<html><body>portal nuevo sin formulario</body></html>")


def test_result_issuers_without_select_and_without_zero_declared_raises():
    with pytest.raises(cnmv_ps.CNMVPSParseError, match="sin lista de emisores"):
        cnmv_ps._result_issuers("<html><body>layout desconocido</body></html>")


def test_result_issuers_empty_declared_is_empty():
    html = "<html><body>encontrados: 0 resultados</body></html>"
    assert cnmv_ps._result_issuers(html) == []


# ---- fetch_reports ----


def _flow_client(page_html: str, landing_html: str = _LANDING) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and "busqueda" in str(request.url):
            return httpx.Response(200, text=_SEARCH_HTML)
        if request.method == "POST":
            if "lstSeleccion" in request.content.decode():
                return httpx.Response(200, text=landing_html)
            return httpx.Response(200, text=_RESULTS_TWO)
        return httpx.Response(200, text=page_html)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_fetch_reports_without_qs_raises(monkeypatch):
    monkeypatch.setattr(cnmv_ps, "_throttle", lambda: None)
    client = _flow_client(_PAGE_NO_DATA, landing_html=_LANDING_NO_QS)
    with pytest.raises(cnmv_ps.CNMVPSParseError, match="sin qS"):
        cnmv_ps.fetch_reports(date(2026, 11, 16), date(2026, 11, 18), client=client)


def test_fetch_reports_skips_unknown_issuers(monkeypatch):
    monkeypatch.setattr(cnmv_ps, "_throttle", lambda: None)
    client = _flow_client(_PAGE_NO_DATA)
    reports, seen, truncated = cnmv_ps.fetch_reports(
        date(2026, 11, 16),
        date(2026, 11, 18),
        client=client,
        is_known=lambda nif: nif == "A28001895",  # solo ACS es nuestra
    )
    assert seen == 2 and len(reports) == 1 and truncated is False
    assert reports[0].nif == "A28001895"


def test_fetch_reports_default_uses_public_session_and_closes_it(monkeypatch):
    monkeypatch.setattr(cnmv_ps, "_throttle", lambda: None)
    state = {"exited": 0, "kwargs": None}
    real_client = _flow_client(_PAGE_NO_DATA)

    class FakeSession:
        def __init__(self, **kwargs):
            state["kwargs"] = kwargs

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            state["exited"] += 1

        def get(self, url):
            return real_client.get(url)

        def post(self, url, data):
            return real_client.post(url, data=data)

    monkeypatch.setattr(cnmv_ps, "PublicSession", FakeSession)
    reports, seen, truncated = cnmv_ps.fetch_reports(
        date(2026, 11, 16), date(2026, 11, 18), is_known=lambda nif: True
    )
    assert seen == 2 and state["exited"] == 1
    assert state["kwargs"]["allowed_url"] is cnmv_ps.is_cnmv_url
    assert state["kwargs"]["extra_headers"] == {"Accept-Language": "es"}


# ---- (1) tabla sin filas tbody: deriva silenciosa ----

_TABLE_EMPTY = '<table id="ctl00_gridAccionistasSignificativos"></table>'


def test_table_without_tbody_rows_raises():
    html = f"<html><body>{_TABLE_EMPTY}</body></html>"
    with pytest.raises(cnmv_ps.CNMVPSParseError, match="sin filas tbody"):
        cnmv_ps.parse_issuer_page(html, "A28001895", "ACS, S.A.")


def test_table_without_rows_but_explicit_no_data_returns_empty():
    html = f"<html><body>{_TABLE_EMPTY} No hay datos para mostrar</body></html>"
    report = cnmv_ps.parse_issuer_page(html, "A28001895", "ACS, S.A.")
    assert report.holders == []


def test_row_without_denominacion_raises():
    html = (
        '<html><body><table id="ctl00_gridAccionistasSignificativos"><tbody>'
        '<tr><td data-th="% Total (A)">5,000</td></tr>'
        "</tbody></table></body></html>"
    )
    with pytest.raises(cnmv_ps.CNMVPSParseError, match="sin denominacion"):
        cnmv_ps.parse_issuer_page(html, "A28001895", "ACS, S.A.")


_ROW_FULL = (
    "<tbody><tr>"
    '<td data-th="Denominación">TITULAR PRUEBA, S.A.</td>'
    '<td data-th="% Total (A)">5,000</td>'
    '<td data-th="% Directo">5,000</td>'
    '<td data-th="% Indirecto">0,000</td>'
    '<td data-th="%  (B)">0,000</td>'
    '<td data-th="(A+B)">5,000</td>'
    '<td data-th="F.Registro Entrada CNMV">'
    '<a href="/webservices/verdocumento/ver?e=XYZ">07/03/2017</a></td>'
    "</tr></tbody>"
)


def test_row_with_relative_registry_anchor():
    html = (
        '<html><body><table id="ctl00_gridAccionistasSignificativos">'
        f"{_ROW_FULL}</table></body></html>"
    )
    report = cnmv_ps.parse_issuer_page(html, "A28001895", "ACS, S.A.")
    holder = report.holders[0]
    assert holder.holder_name == "TITULAR PRUEBA, S.A."
    assert holder.pct_total == 5.0
    assert holder.registry_date == date(2017, 3, 7)
    assert holder.document_url == "https://www.cnmv.es/webservices/verdocumento/ver?e=XYZ"


def test_row_without_registry_cell():
    row = (
        "<tbody><tr>"
        '<td data-th="Denominación">TITULAR SIN FECHA, S.A.</td>'
        '<td data-th="% Total (A)">3,000</td>'
        '<td data-th="% Directo">3,000</td>'
        '<td data-th="% Indirecto">0,000</td>'
        '<td data-th="%  (B)">0,000</td>'
        '<td data-th="(A+B)">3,000</td>'
        "</tr></tbody>"
    )
    html = (
        '<html><body><table id="ctl00_gridAccionistasSignificativos">'
        f"{row}</table></body></html>"
    )
    report = cnmv_ps.parse_issuer_page(html, "A28001895", "ACS, S.A.")
    holder = report.holders[0]
    assert holder.registry_date is None  # celda ausente: N/D
    assert holder.document_url is None


def test_row_with_unparseable_registry_date_and_no_anchor():
    row = _ROW_FULL.replace(
        '<a href="/webservices/verdocumento/ver?e=XYZ">07/03/2017</a>', "fecha ilegible"
    )
    html = (
        '<html><body><table id="ctl00_gridAccionistasSignificativos">'
        f"{row}</table></body></html>"
    )
    report = cnmv_ps.parse_issuer_page(html, "A28001895", "ACS, S.A.")
    holder = report.holders[0]
    assert holder.registry_date is None  # N/D, nunca inventada
    assert holder.document_url is None


def test_loyalty_voting_rights_parsed():
    html = (
        "<html><body>Número total de derechos de voto (incluidos los adicionales"
        " otorgados por acciones por lealtad): 249.335.371 derechos. "
        '<table id="ctl00_gridAccionistasSignificativos">'
        f"{_ROW_FULL}</table></body></html>"
    )
    report = cnmv_ps.parse_issuer_page(html, "A28001895", "ACS, S.A.")
    assert report.total_voting_rights == 249335371
    assert report.loyalty_voting_rights is None  # no declarado: N/D


def test_loyalty_line_parsed_when_present():
    html = (
        "<html><body>Número total de derechos de voto (incluidos los adicionales"
        " otorgados por acciones por lealtad): 249.335.371 "
        "adicionales otorgados por acciones por lealtad: 1.234 "
        '<table id="ctl00_gridAccionistasSignificativos">'
        f"{_ROW_FULL}</table></body></html>"
    )
    report = cnmv_ps.parse_issuer_page(html, "A28001895", "ACS, S.A.")
    assert report.loyalty_voting_rights == 1234


# ---- helpers numericos ----


def test_parse_helpers_degrade_to_none():
    assert cnmv_ps._parse_int("abc") is None
    assert cnmv_ps._parse_date("garbage") is None
    assert cnmv_ps._parse_date(None) is None  # AttributeError: N/D
    assert cnmv_ps._parse_pct("no-es-numero") is None


def test_recent_window():
    start, end = cnmv_ps.recent_window(days=7)
    assert (end - start).days == 7
    assert end == date.today()


# ---- ingesta: fetch por defecto, NIF desconocido, issuers_seen ----


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Tenant(id=1, external_id="a"))
        session.add(
            Company(
                id=1,
                ticker="ACX",
                name="ACERINOX",
                exchange="BME",
                company_type="cyclical",
                valuation_model="dcf",
                isin="ES0132105018",
            )
        )
        session.commit()
        session.info["tenant_id"] = 1
        yield session
    engine.dispose()


def test_known_nif_helper():
    assert cnmv_ps_ingestion._known_nif("A-28250777") is True  # ACERINOX, tabla revisada
    assert cnmv_ps_ingestion._known_nif("X9999999Z") is False


def test_ingest_fetches_by_default_and_skips_unknown_nif(db, monkeypatch):
    unknown = cnmv_ps.PSIssuerReport(nif="X9999999Z", issuer_name="DESCONOCIDA, S.A.")
    calls = []

    def fake_fetch(start, end, *, is_known=None):
        calls.append((start, end))
        return [unknown], 1, False

    monkeypatch.setattr(cnmv_ps_ingestion, "fetch_reports", fake_fetch)
    result = cnmv_ps_ingestion.ingest_cnmv_ps(db, 1, date(2026, 11, 16), date(2026, 11, 18))
    assert calls == [(date(2026, 11, 16), date(2026, 11, 18))]
    assert result["skipped_unknown_nif"] == 1
    assert result["saved"] == 0


def test_ingest_skips_known_nif_without_company_row(db):
    # ATRESMEDIA esta en la tabla revisada cnmv_mapping pero NO en la db:
    # no se inventa fila; se cuenta y se sigue.
    report = cnmv_ps.PSIssuerReport(
        nif="A-78839271", issuer_name="ATRESMEDIA CORPORACION DE MEDIOS DE COMUNICACION, S.A."
    )
    result = cnmv_ps_ingestion.ingest_cnmv_ps(
        db, 1, date(2026, 11, 16), date(2026, 11, 18), reports=[report]
    )
    assert result["skipped_unknown_company"] == 1
    assert result["saved"] == 0


def test_ingest_issuers_seen_defaults_to_reports_len(db):
    result = cnmv_ps_ingestion.ingest_cnmv_ps(
        db, 1, date(2026, 11, 16), date(2026, 11, 18), reports=[], issuers_seen=None
    )
    assert result["issuers_seen"] == 0
