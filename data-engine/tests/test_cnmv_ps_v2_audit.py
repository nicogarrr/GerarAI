"""CNMV PS: los 5 arreglos de la auditoria NOD aplicados desde el inicio.

1. Deriva silenciosa: ya fail-closed en v1 (cubierto por
   test_missing_table_degrades_instead_of_inventing y test_result_issuers_list_and_empty).
2. _companies_by_isin_and_ticker consumia db.scalars dos veces.
3. Throttle de modulo -> pacer global "cnmv" (hilos + procesos), compartido
   con NOD; Retry-After marca cooldown global.
4. max_issuers=0 no hace NINGUNA peticion; tope alcanzado con emisores
   conocidos pendientes -> truncated=True.
5. Actor: queue INGESTA y coste por tenant declarados en docstrings.
"""

from datetime import date

import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, Tenant
from app.services import cnmv_ps_ingestion
from app.services.connectors import cnmv_ps
from app.services.connectors.global_pacing import GlobalPacer


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    db.add(Tenant(id=1, external_id="a"))
    db.commit()
    db.info["tenant_id"] = 1
    return db


# ---- 2. universo de companies consumido una vez ----


def test_ticker_fallback_actually_finds_company():
    db = _db()
    db.add(
        Company(
            ticker="ACS",
            name="ACS",
            exchange="BME",
            company_type="compounders",
            valuation_model="dcf",
            isin=None,
        )
    )
    db.commit()
    by_isin, by_ticker = cnmv_ps_ingestion._companies_by_isin_and_ticker(db)
    assert by_ticker["ACS"].ticker == "ACS"
    assert by_isin == {}


# ---- 3. throttle global + Retry-After global ----


def test_throttle_delegates_to_shared_global_pacer():
    assert isinstance(cnmv_ps._pacer, GlobalPacer)
    assert cnmv_ps._pacer.key == "cnmv"  # mismo presupuesto que NOD
    assert cnmv_ps._pacer.min_interval_seconds == 1.0
    assert not hasattr(cnmv_ps, "_last_request_at")
    assert not hasattr(cnmv_ps, "_retry_after_s")


def test_retry_after_marks_global_cooldown(monkeypatch):
    cooldowns: list[float] = []
    monkeypatch.setattr(cnmv_ps._pacer, "cool_down", lambda s: cooldowns.append(s))
    response = httpx.Response(429, headers={"Retry-After": "45"})
    cnmv_ps._respect_retry_after(response)
    assert cooldowns == [45.0]


# ---- 4. presupuesto de peticiones honesto ----


def test_max_issuers_zero_makes_no_request():
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("max_issuers=0 no debe hacer ninguna peticion")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    reports, seen, truncated = cnmv_ps.fetch_reports(
        date(2026, 11, 16), date(2026, 11, 18), client=client, max_issuers=0
    )
    assert reports == [] and seen == 0 and truncated is False


_SEARCH_HTML = (
    '<html><body><input name="__VIEWSTATE" value="v1"/></body></html>'
)
_RESULTS_HTML_TWO = (
    '<html><body><input name="__VIEWSTATE" value="v2"/>'
    '<select name="ctl00$ContentPrincipal$wbusqueda$lstSeleccion">'
    '<option value="A28001895">ACS, ACTIVIDADES DE CONSTRUCCION Y SERVICIOS, S.A.</option>'
    '<option value="A87494772">ACS, ACTIVIDADES DE CONSTRUCCION Y SERVICIOS, S.A.</option>'
    "</select></body></html>"
)
_LANDING_HTML = (
    '<html><body><a href="/Portal/consultas/DerechosVoto/Notificaciones-Participaciones'
    '.aspx?qS={11111111-2222-3333-4444-555555555555}">ver</a></body></html>'
)
_PAGE_HTML = (
    '<html><body><span id="ctl00_lblSubtitulo">ACS, ACTIVIDADES DE CONSTRUCCION Y SERVICIOS, S.A.'
    "</span>No hay datos para mostrar</body></html>"
)


def test_tope_con_emisores_conocidos_pendientes_se_senala(monkeypatch):
    monkeypatch.setattr(cnmv_ps, "_throttle", lambda: None)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and "busqueda" in str(request.url):
            return httpx.Response(200, text=_SEARCH_HTML)
        if request.method == "POST":
            data = request.content.decode()
            if "lstSeleccion" in data:
                return httpx.Response(200, text=_LANDING_HTML)
            return httpx.Response(200, text=_RESULTS_HTML_TWO)
        return httpx.Response(200, text=_PAGE_HTML)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    reports, seen, truncated = cnmv_ps.fetch_reports(
        date(2026, 11, 16),
        date(2026, 11, 18),
        client=client,
        is_known=lambda nif: True,  # los dos emisores son conocidos
        max_issuers=1,
    )
    assert seen == 2
    assert len(reports) == 1
    assert truncated is True  # el segundo emisor conocido quedo sin visitar: señalado


def test_sin_tope_no_hay_truncado(monkeypatch):
    monkeypatch.setattr(cnmv_ps, "_throttle", lambda: None)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and "busqueda" in str(request.url):
            return httpx.Response(200, text=_SEARCH_HTML)
        if request.method == "POST":
            data = request.content.decode()
            if "lstSeleccion" in data:
                return httpx.Response(200, text=_LANDING_HTML)
            return httpx.Response(200, text=_RESULTS_HTML_TWO)
        return httpx.Response(200, text=_PAGE_HTML)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    reports, seen, truncated = cnmv_ps.fetch_reports(
        date(2026, 11, 16), date(2026, 11, 18), client=client, is_known=lambda nif: True
    )
    assert seen == 2 and len(reports) == 2 and truncated is False


def test_ps_rows_never_reach_us_13dg_screen():
    """Las filas form="PS-ES" comparten tabla con las 13D/G de EE. UU. pero
    NUNCA la pantalla /schedule-13dg: el servicio filtra por FORMS_13DG."""
    from app.models.entities import Schedule13DGFiling
    from app.services import schedule13dg_service

    db = _db()
    registro_previo = "cnmvps-abc123"
    db.add(
        Schedule13DGFiling(
            tenant_id=1,
            accession_number=registro_previo,
            form="PS-ES",
            issuer_cik="A28001895",
            issuer_ticker="ACS",
            issuer_name="ACS",
            holder_name="TITULAR, S.A.",
            percent_of_class=5.0,
            holders=[],
            parser_version="2026-11-18.1",
            status="parsed",
        )
    )
    db.commit()
    out = schedule13dg_service.filings_for_ticker(db, "ACS")
    assert out["count"] == 0
    assert out["filings"] == []


def test_ingest_propaga_truncated(monkeypatch):
    db = _db()
    monkeypatch.setattr(
        cnmv_ps_ingestion, "fetch_reports", lambda *a, **k: ([], 30, True)
    )
    result = cnmv_ps_ingestion.ingest_cnmv_ps(db, 1, date(2026, 11, 16), date(2026, 11, 18))
    assert result["truncated"] == 1
    assert result["issuers_seen"] == 30
