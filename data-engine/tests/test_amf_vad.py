"""AMF VAD: API data.gouv fail-closed, parser fail-closed del CSV, posición
vigente por titular (actualizaciones y cierres), agregado DERIVADO, cache,
pacer, Retry-After íntegro y rama XPAR del servicio de cortos.

Condiciones de la luz verde (Main, 18-nov): atribución «AMF», cabecera
literal, fallo de API/esquema = error (no «sin cortos»), ISIN/fecha/ratio
validados, T+2 y 0,5% declarados, N/D nunca 0, agregado etiquetado
DERIVADO, vigente = última fila del titular sin fecha fin."""

import asyncio
from datetime import date, datetime
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models.entities import Base, Company, Tenant
from app.services import short_positions_service
from app.services.connectors import amf_vad

FIXTURE = (Path(__file__).parent / "fixtures" / "amf" / "vad_2026-11.csv").read_text(
    encoding="utf-8"
)
# 11 filas reales: CFM x WORLDLINE (3 abiertas, actualizaciones), Helikon x
# WORLDLINE (abierta), AHL x WORLDLINE (2 cerradas), ARGONAUT x UBISOFT
# (3 abiertas, actualizaciones), 12 WEST x UBISOFT (2 cerradas de 2015).

_API_JSON = (
    '{"resources": [{"title": "ventes-a-decouvert", "format": "csv",'
    ' "url": "https://amf.s3.example/VAD/export_test.csv"}]}'
)


@pytest.fixture(autouse=True)
def _clean_cache():
    amf_vad.reset_cache()
    yield
    amf_vad.reset_cache()


# ---- resolución del recurso vía API data.gouv (fail-closed) ----


def test_resolve_resource_url_ok(monkeypatch):
    monkeypatch.setattr(amf_vad, "_throttle", lambda: None)
    client = httpx.Client(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, text=_API_JSON))
    )
    assert amf_vad.resolve_resource_url(client) == "https://amf.s3.example/VAD/export_test.csv"


def test_resolve_api_schema_drift_raises(monkeypatch):
    monkeypatch.setattr(amf_vad, "_throttle", lambda: None)
    client = httpx.Client(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, text="<html>portal</html>"))
    )
    with pytest.raises(amf_vad.AMFVADParseError, match="JSON de dataset"):
        amf_vad.resolve_resource_url(client)


def test_resolve_two_csv_resources_raises(monkeypatch):
    monkeypatch.setattr(amf_vad, "_throttle", lambda: None)
    payload = (
        '{"resources": [{"format": "csv", "url": "https://a.example/1.csv"},'
        ' {"format": "csv", "url": "https://a.example/2.csv"}]}'
    )
    client = httpx.Client(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, text=payload))
    )
    with pytest.raises(amf_vad.AMFVADParseError, match="recursos CSV"):
        amf_vad.resolve_resource_url(client)


def test_resolve_resource_without_url_raises(monkeypatch):
    monkeypatch.setattr(amf_vad, "_throttle", lambda: None)
    payload = '{"resources": [{"format": "csv"}]}'
    client = httpx.Client(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, text=payload))
    )
    with pytest.raises(amf_vad.AMFVADParseError, match="recursos CSV"):
        amf_vad.resolve_resource_url(client)


def test_resolve_http_error_raises(monkeypatch):
    monkeypatch.setattr(amf_vad, "_throttle", lambda: None)
    monkeypatch.setattr(amf_vad._pacer, "cool_down", lambda s: None)
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda req: httpx.Response(429, headers={"Retry-After": "30"})
        )
    )
    with pytest.raises(httpx.HTTPStatusError):
        amf_vad.resolve_resource_url(client)


# ---- parser fail-closed ----


def test_parse_real_fixture():
    rows = amf_vad.parse_csv(FIXTURE)
    assert len(rows) == 11
    first = rows[0]
    assert first.holder_name == "CAPITAL FUND MANAGEMENT"
    assert first.holder_lei == "549300KKLDTNOIW0NU52"
    assert first.isin == "FR0011981968"
    assert first.ratio_pct == 0.71
    assert first.position_start == date(2026, 6, 9)
    assert first.publication_end is None  # publicación vigente


def test_blank_lines_are_skipped():
    con_huecos = FIXTURE.replace("\n", "\n\n", 1)  # línea en blanco: tolerada
    assert len(amf_vad.parse_csv(con_huecos)) == 11


def test_header_drift_raises():
    broken = FIXTURE.replace("Detenteur de la position courte nette", "Holder")
    with pytest.raises(amf_vad.AMFVADParseError, match="cabecera"):
        amf_vad.parse_csv(broken)


def test_empty_csv_is_drift_not_empty_market():
    header_only = FIXTURE.split("\n")[0] + "\n"
    with pytest.raises(amf_vad.AMFVADParseError, match="sin filas"):
        amf_vad.parse_csv(header_only)


def test_wrong_column_count_raises():
    broken = FIXTURE.replace(
        '"CAPITAL FUND MANAGEMENT";"549300KKLDTNOIW0NU52";"WORLDLINE";"0.71";"FR0011981968";"2026-06-09";"2026-06-10";""',
        '"CAPITAL FUND MANAGEMENT";"549300KKLDTNOIW0NU52";"WORLDLINE"',
    )
    with pytest.raises(amf_vad.AMFVADParseError, match="columnas"):
        amf_vad.parse_csv(broken)


def test_missing_holder_raises():
    broken = FIXTURE.replace('"CAPITAL FUND MANAGEMENT";"549300KKLDTNOIW0NU52"', '"";"549300KKLDTNOIW0NU52"', 1)
    with pytest.raises(amf_vad.AMFVADParseError, match="sin titular"):
        amf_vad.parse_csv(broken)


def test_missing_issuer_raises():
    broken = FIXTURE.replace(';"WORLDLINE";"0.71"', ';"";"0.71"', 1)
    with pytest.raises(amf_vad.AMFVADParseError, match="sin emisor"):
        amf_vad.parse_csv(broken)


def test_bad_isin_raises():
    broken = FIXTURE.replace('"FR0011981968"', '"XX!INVALID"', 1)
    with pytest.raises(amf_vad.AMFVADParseError, match="ISIN invalido"):
        amf_vad.parse_csv(broken)


def test_non_numeric_ratio_raises():
    broken = FIXTURE.replace(';"0.71";', ';"N/D";', 1)
    with pytest.raises(amf_vad.AMFVADParseError, match="no numerico"):
        amf_vad.parse_csv(broken)


def test_out_of_range_ratio_raises():
    broken = FIXTURE.replace(';"0.71";', ';"101.5";', 1)
    with pytest.raises(amf_vad.AMFVADParseError, match="fuera de rango"):
        amf_vad.parse_csv(broken)


def test_future_position_date_raises():
    broken = FIXTURE.replace('"2026-06-09"', '"2999-06-09"', 1)
    with pytest.raises(amf_vad.AMFVADParseError, match="futura"):
        amf_vad.parse_csv(broken, now=datetime(2026, 11, 18))


def test_bad_position_date_raises():
    broken = FIXTURE.replace('"2026-06-09"', '"09/06/2026"', 1)
    with pytest.raises(amf_vad.AMFVADParseError, match="fecha de posicion"):
        amf_vad.parse_csv(broken)


def test_bad_publication_dates_raise():
    broken = FIXTURE.replace('"2026-06-10";""', '"10-06-2026";""', 1)
    with pytest.raises(amf_vad.AMFVADParseError, match="fecha de publicacion"):
        amf_vad.parse_csv(broken)
    broken2 = FIXTURE.replace('"2026-06-10";""', '"2026-06-10";"ayer"', 1)
    with pytest.raises(amf_vad.AMFVADParseError, match="fecha fin"):
        amf_vad.parse_csv(broken2)


def test_invalid_lei_is_nd_never_invented():
    broken = FIXTURE.replace('"549300KKLDTNOIW0NU52"', '"LEI-ILEGIBLE"', 1)
    rows = amf_vad.parse_csv(broken)
    assert rows[0].holder_lei is None


# ---- posición vigente por titular: actualizaciones y cierres ----


def test_current_positions_latest_update_wins():
    rows = amf_vad.parse_csv(FIXTURE)
    vigentes = amf_vad.current_positions(rows)
    by_key = {(r.holder_name, r.isin): r for r in vigentes}
    # 3 filas abiertas de CFM: la última publicación (10-jun) manda
    assert by_key[("CAPITAL FUND MANAGEMENT", "FR0011981968")].ratio_pct == 0.71
    assert by_key[("CAPITAL FUND MANAGEMENT", "FR0011981968")].position_start == date(2026, 6, 9)
    assert by_key[("ARGONAUT CAPITAL PARTNERS LLP", "FR0000054470")].ratio_pct == 1.58
    assert by_key[("Helikon Investments Limited", "FR0011981968")].ratio_pct == 1.51
    # Cerrados (con fecha fin): fuera aunque la fila sea reciente
    assert ("AHL PARTNERS LLP", "FR0011981968") not in by_key
    assert ("12 WEST CAPITAL MANAGEMENT LP", "FR0000054470") not in by_key


def test_position_closed_when_all_rows_have_end_date():
    rows = amf_vad.parse_csv(FIXTURE)
    abierto = [r for r in rows if r.holder_name == "AHL PARTNERS LLP"]
    assert len(abierto) == 2  # hay filas históricas...
    vigentes = amf_vad.rows_for_isin(rows, "FR0011981968")
    assert all(r.holder_name != "AHL PARTNERS LLP" for r in vigentes)  # ...pero ninguna vigente


def test_aggregate_is_derivative_sum():
    rows = amf_vad.parse_csv(FIXTURE)
    agregado = amf_vad.aggregate_by_isin(amf_vad.current_positions(rows))
    assert agregado == {"FR0011981968": 2.22, "FR0000054470": 1.58}


def test_rows_for_isin_filters_and_normalizes():
    rows = amf_vad.parse_csv(FIXTURE)
    wor = amf_vad.rows_for_isin(rows, "fr0011981968")
    assert {r.holder_name for r in wor} == {
        "CAPITAL FUND MANAGEMENT",
        "Helikon Investments Limited",
    }
    assert amf_vad.rows_for_isin(rows, "ES0132105018") == []  # sin cortos declarados: vacío
    assert amf_vad.rows_for_isin(rows, None) == []
    assert amf_vad.rows_for_isin(rows, "") == []


# ---- fetch: cache, pacer, Retry-After íntegro, registry ----


def _flow_client() -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if "data.gouv.fr" in str(request.url):
            return httpx.Response(200, text=_API_JSON)
        return httpx.Response(200, text=FIXTURE)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_fetch_current_full_flow_and_cache(monkeypatch):
    monkeypatch.setattr(amf_vad, "_throttle", lambda: None)
    calls = []
    client = _flow_client()
    original_get = client.get

    def counting_get(url, **kw):
        calls.append(str(url))
        return original_get(url, **kw)

    monkeypatch.setattr(client, "get", counting_get)
    first = amf_vad.fetch_current(client=client)
    second = amf_vad.fetch_current(client=client)
    assert len(calls) == 2  # API + CSV; la segunda lectura sale de cache
    assert first is second
    assert len(first) == 11


def test_fetch_current_own_client_closes(monkeypatch):
    monkeypatch.setattr(amf_vad, "_throttle", lambda: None)
    closed = {"n": 0}
    real_client = _flow_client()

    class FakeClient:
        def get(self, url, **kw):
            return real_client.get(url, **kw)

        def close(self):
            closed["n"] += 1

    monkeypatch.setattr(amf_vad.httpx, "Client", lambda **kwargs: FakeClient())
    rows = amf_vad.fetch_current()
    assert len(rows) == 11 and closed["n"] == 1


def test_fetch_records_registry_failure_on_parse_error(monkeypatch):
    monkeypatch.setattr(amf_vad, "_throttle", lambda: None)
    registry = Mock()
    monkeypatch.setattr(amf_vad, "get_data_source_registry", lambda: registry)
    client = httpx.Client(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, text="html, no csv"))
    )
    with pytest.raises(amf_vad.AMFVADParseError):
        amf_vad.fetch_current(client=client)
    assert registry.record_failure.called
    assert not registry.record_success.called


def test_fetch_records_registry_failure_on_network_error(monkeypatch):
    monkeypatch.setattr(amf_vad, "_throttle", lambda: None)
    registry = Mock()
    monkeypatch.setattr(amf_vad, "get_data_source_registry", lambda: registry)

    def handler(req):
        raise httpx.ConnectError("sin red", request=req)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(httpx.ConnectError):
        amf_vad.fetch_current(client=client)
    assert registry.record_failure.called


def test_fetch_records_success(monkeypatch):
    monkeypatch.setattr(amf_vad, "_throttle", lambda: None)
    registry = Mock()
    monkeypatch.setattr(amf_vad, "get_data_source_registry", lambda: registry)
    amf_vad.fetch_current(client=_flow_client())
    assert registry.record_success.called


def test_retry_after_not_shortened(monkeypatch):
    cooldowns: list[float] = []
    monkeypatch.setattr(amf_vad._pacer, "cool_down", lambda s: cooldowns.append(s))
    amf_vad._respect_retry_after(httpx.Response(429, headers={"Retry-After": "3600"}))
    assert cooldowns == [3600.0]  # íntegro, nunca recortado


def test_retry_after_absent_http_date_and_garbage(monkeypatch):
    import time as _time
    from email.utils import formatdate

    cooldowns: list[float] = []
    monkeypatch.setattr(amf_vad._pacer, "cool_down", lambda s: cooldowns.append(s))
    amf_vad._respect_retry_after(httpx.Response(200))  # sin cabecera: nada
    assert cooldowns == []
    future = formatdate(_time.time() + 120, usegmt=True)
    amf_vad._respect_retry_after(httpx.Response(503, headers={"Retry-After": future}))
    assert 100.0 < cooldowns[0] <= 120.0
    amf_vad._respect_retry_after(httpx.Response(429, headers={"Retry-After": "soon"}))
    assert cooldowns[1] == 60.0


def test_redis_client_paths(monkeypatch):
    import sys

    monkeypatch.setattr("app.core.config.get_settings", lambda: Mock(redis_url=""))
    assert amf_vad._amf_redis_client() is None

    def boom():
        raise RuntimeError("settings rotos")

    monkeypatch.setattr("app.core.config.get_settings", boom)
    assert amf_vad._amf_redis_client() is None

    sentinel = object()
    fake_redis = Mock(from_url=Mock(return_value=sentinel))
    monkeypatch.setitem(sys.modules, "redis", fake_redis)
    monkeypatch.setattr(
        "app.core.config.get_settings", lambda: Mock(redis_url="redis://localhost:6379/0")
    )
    assert amf_vad._amf_redis_client() is sentinel


def test_throttle_uses_pacer(monkeypatch):
    calls = []
    monkeypatch.setattr(amf_vad._pacer, "wait_sync", lambda: calls.append(1))
    amf_vad._throttle()
    assert calls == [1]


# ---- rama XPAR del servicio de cortos ----


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
                ticker="WLN",
                name="WORLDLINE",
                exchange="XPAR",
                company_type="cyclical",
                valuation_model="dcf",
                isin="FR0011981968",
            )
        )
        session.commit()
        session.info.update(tenant_id=1, user_id="a")
        yield session
    engine.dispose()


def test_refresh_shorts_fr_with_holders(db, monkeypatch):
    rows = amf_vad.parse_csv(FIXTURE)
    monkeypatch.setattr(short_positions_service, "fetch_amf_vad_current", lambda: rows)
    company = db.get(Company, 1)
    out = asyncio.run(short_positions_service.refresh_shorts(db, company))
    payload = out["data"]
    assert payload["source"] == "AMF-VAD"
    assert payload["licence"] == "AMF - Licence Ouverte v2.0"  # atribución visible
    assert "T+2" in payload["delay"]
    assert "0,5%" in payload["threshold"]
    assert payload["ratio_kind"] == "DERIVADO"  # el agregado se etiqueta
    assert payload["public_total_percent"] == 2.22
    by_holder = {p["holder"]: p for p in payload["positions"]}
    assert by_holder["CAPITAL FUND MANAGEMENT"]["percent"] == 0.71
    assert by_holder["Helikon Investments Limited"]["lei"] == "254900EGJIB7IR00B295"
    assert "AHL PARTNERS LLP" not in by_holder  # posición cerrada: fuera


def test_refresh_shorts_fr_without_positions_is_empty_not_zero(db, monkeypatch):
    monkeypatch.setattr(short_positions_service, "fetch_amf_vad_current", lambda: [])
    company = db.get(Company, 1)
    out = asyncio.run(short_positions_service.refresh_shorts(db, company))
    payload = out["data"]
    assert payload["positions"] == []
    assert payload["public_total_percent"] is None  # N/D, nunca 0


def test_refresh_shorts_fr_without_isin_degrades(db):
    from app.models import ConnectorState

    company = db.get(Company, 1)
    company.isin = None
    out = asyncio.run(short_positions_service.refresh_shorts(db, company))
    assert out["status"] == "degraded"
    state = db.query(ConnectorState).filter_by(company_id=company.id).one()
    assert state.last_error == "ValueError"


def _alertas(monkeypatch):
    emit = Mock()
    monkeypatch.setattr(
        "app.services.review_alert_service.ReviewAlertService.emit_alert", emit
    )
    return emit


def _payload_fr(pct_cfm, pct_helikon, day_cfm, day_helikon):
    return {
        "source": "AMF-VAD",
        "positions": [
            {"holder": "CAPITAL FUND MANAGEMENT", "percent": pct_cfm, "position_date": day_cfm},
            {"holder": "Helikon Investments Limited", "percent": pct_helikon, "position_date": day_helikon},
        ],
        "public_total_percent": round(pct_cfm + pct_helikon, 6),
        "source_url": amf_vad.DATASET_API_URL,
    }


def test_emit_amf_increase_alerts_with_attribution(db, monkeypatch):
    from app.models import Position

    emit = _alertas(monkeypatch)
    company = db.get(Company, 1)
    db.add(Position(company_id=company.id, quantity=1))
    db.commit()
    previo = _payload_fr(0.5, 1.51, "2026-06-09", "2026-03-10")
    actual = _payload_fr(0.71, 1.6, "2026-11-13", "2026-11-13")
    short_positions_service.emit_shorts_increase(db, company, previo, actual, datetime.now())
    assert emit.call_count == 1
    message = emit.call_args.kwargs["message"]
    assert "AMF-VAD" in message
    assert "0,5%" in message  # umbral declarado en el propio aviso
    assert "AMF-VAD" in emit.call_args.kwargs["fingerprint_parts"]


def test_emit_amf_same_totals_no_alert(db, monkeypatch):
    from app.models import Position

    emit = _alertas(monkeypatch)
    company = db.get(Company, 1)
    db.add(Position(company_id=company.id, quantity=1))
    db.commit()
    previo = _payload_fr(0.5, 1.51, "2026-06-09", "2026-03-10")
    actual = _payload_fr(0.5, 1.51, "2026-11-13", "2026-11-13")
    short_positions_service.emit_shorts_increase(db, company, previo, actual, datetime.now())
    emit.assert_not_called()


def test_emit_amf_holder_set_changed_no_alert(db, monkeypatch):
    from app.models import Position

    emit = _alertas(monkeypatch)
    company = db.get(Company, 1)
    db.add(Position(company_id=company.id, quantity=1))
    db.commit()
    previo = _payload_fr(0.5, 1.51, "2026-06-09", "2026-03-10")
    actual = _payload_fr(0.71, 1.6, "2026-11-13", "2026-11-13")
    actual["positions"][1]["holder"] = "OTRO TITULAR LLP"  # cambió el set: no comparable
    short_positions_service.emit_shorts_increase(db, company, previo, actual, datetime.now())
    emit.assert_not_called()


def test_emit_mixed_sources_no_alert(db, monkeypatch):
    """Previo CNMV + actual AMF-VAD (y al reves): no comparables, sin alerta.
    Mata el mutante que quita la igualdad previous.source == current.source."""
    from app.models import Position

    emit = _alertas(monkeypatch)
    company = db.get(Company, 1)
    db.add(Position(company_id=company.id, quantity=1))
    db.commit()
    previo = _payload_fr(0.5, 1.51, "2026-06-09", "2026-03-10")
    previo["source"] = "CNMV"
    actual = _payload_fr(0.71, 1.6, "2026-11-13", "2026-11-13")
    short_positions_service.emit_shorts_increase(db, company, previo, actual, datetime.now())
    emit.assert_not_called()
    previo["source"], actual["source"] = "AMF-VAD", "CNMV"
    short_positions_service.emit_shorts_increase(db, company, previo, actual, datetime.now())
    emit.assert_not_called()


def test_malformed_quotes_rejected_strict():
    broken = FIXTURE.replace('"CAPITAL FUND MANAGEMENT"', '"CAPITAL FUND MANAGEMENT"basura', 1)
    with pytest.raises(amf_vad.AMFVADParseError, match="malformado"):
        amf_vad.parse_csv(broken)


def test_future_publication_date_raises():
    broken = FIXTURE.replace('"2026-06-10";""', '"2999-06-10";""', 1)
    with pytest.raises(amf_vad.AMFVADParseError, match="publicacion futura"):
        amf_vad.parse_csv(broken, now=datetime(2026, 11, 18))


def test_concurrent_cache_miss_single_download(monkeypatch):
    import threading

    monkeypatch.setattr(amf_vad, "_throttle", lambda: None)
    gets = []
    gate = threading.Event()

    def handler(request: httpx.Request) -> httpx.Response:
        gets.append(str(request.url))
        gate.wait(timeout=0.3)  # mantiene abierta la ventana de carrera
        if "data.gouv.fr" in str(request.url):
            return httpx.Response(200, text=_API_JSON)
        return httpx.Response(200, text=FIXTURE)

    cache: dict = {}
    results = []
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        threads = [
            threading.Thread(target=lambda: results.append(amf_vad.fetch_current(client=client, cache=cache)))
            for _ in range(3)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(5)
    assert len(gets) == 2  # API + CSV UNA vez, no una por hilo
    assert len(results) == 3 and all(r is results[0] for r in results)


@pytest.mark.parametrize("dia_actual", ["2026-11-01", "2026-11-13", "2999-01-01"])
def test_emit_amf_no_alert_without_advanced_dates(db, monkeypatch, dia_actual):
    from app.models import Position

    emit = _alertas(monkeypatch)
    company = db.get(Company, 1)
    db.add(Position(company_id=company.id, quantity=1))
    db.commit()
    previo = _payload_fr(0.5, 1.51, "2026-11-13", "2026-11-13")
    actual = _payload_fr(0.71, 1.6, dia_actual, dia_actual)
    short_positions_service.emit_shorts_increase(db, company, previo, actual, datetime(2026, 11, 18))
    if dia_actual == "2026-11-13":
        emit.assert_not_called()  # fecha igual: no avanza
    elif dia_actual == "2026-11-01":
        emit.assert_not_called()  # retrocede
    else:
        emit.assert_not_called()  # futura
