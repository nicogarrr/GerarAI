"""Contratos del conector ESEF: parseo JSON:API, fechas inclusivas xBRL-JSON,
normalizacion a layout companyfacts, cliente con registry y snapshots locales.

Los instantes xBRL-JSON son EXCLUSIVOS a medianoche (2026-01-01T00:00:00 =
31/12/2025 inclusivo): ese es el contrato de fechas que se fija aqui, junto
con el fail-closed ante schema drift y las llamadas HTTP (fakes que solo
graban).
"""

import asyncio
import json

import httpx
import pytest

from app.services.connectors import esef
from app.services.connectors.esef import (
    EsefClient,
    EsefError,
    EsefFiling,
    _inclusive_date,
    _lei_from_filing,
    normalize_xbrl_json,
    parse_entity,
    parse_filings_page,
    parse_period,
    read_esef_snapshot,
)
from app.services.data_source_health import get_data_source_registry


def run_async(coroutine):
    return asyncio.run(coroutine)


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=esef.ESEF_BASE_URL)


@pytest.fixture(autouse=True)
def _no_throttle(monkeypatch):
    monkeypatch.setattr(esef, "_MIN_INTERVAL_S", 0)


def _esef_failures() -> int:
    return get_data_source_registry().get_status("esef").consecutive_failures


LEI = "959800ABCDEFGH123456"  # 20 chars alfanumericos


# -- _lei_from_filing -------------------------------------------------------


def test_lei_prioriza_json_url_sobre_package_y_fxo():
    assert _lei_from_filing("fxo", f"/{LEI}/pkg.zip", f"/{LEI}/doc.json") == LEI
    assert _lei_from_filing("fxo", f"/{LEI}/pkg.zip", None) == LEI


def test_lei_del_fxo_id_cuando_no_hay_urls():
    assert _lei_from_filing(LEI + "resto", None, None) == LEI


def test_lei_irresoluble_es_none():
    assert _lei_from_filing("corto", "/no-lei/x.zip", None) is None
    assert _lei_from_filing("!!!", None, None) is None


# -- parse_filings_page -----------------------------------------------------


def _page(rows, total=1):
    return {"data": rows, "meta": {"count": total}}


def test_parse_filings_page_happy_path():
    rows = [{
        "attributes": {
            "fxo_id": "fx1", "country": "ES", "period_end": "2025-12-31",
            "json_url": f"/{LEI}/doc.json", "package_url": f"/{LEI}/pkg.zip",
            "sha256": "abc", "error_count": 0, "warning_count": 2,
        }
    }]
    filings, total = parse_filings_page(_page(rows, total=42))
    assert total == 42
    f = filings[0]
    assert f.fxo_id == "fx1" and f.lei == LEI and f.country == "ES"
    assert f.period_end == "2025-12-31" and f.warning_count == 2


def test_parse_filings_page_schema_drift_falla_cerrado():
    with pytest.raises(EsefError, match="schema drift"):
        parse_filings_page({"meta": {"count": 1}})  # sin data
    with pytest.raises(EsefError, match="data is not a list"):
        parse_filings_page({"data": {}, "meta": {"count": 1}})
    with pytest.raises(EsefError, match="schema drift"):
        parse_filings_page(_page([{"attributes": {"country": "ES"}}]))  # sin fxo_id


def test_parse_filings_page_sin_lei_falla_cerrado():
    rows = [{"attributes": {"fxo_id": "x", "country": "ES"}}]
    with pytest.raises(EsefError, match="cannot resolve LEI"):
        parse_filings_page(_page(rows))


# -- parse_entity -----------------------------------------------------------


def test_parse_entity_happy_y_drift():
    payload = {"data": {"attributes": {"identifier": LEI, "name": "Aena SME SA"}}}
    assert parse_entity(payload) == (LEI, "Aena SME SA")
    with pytest.raises(EsefError, match="entity schema drift"):
        parse_entity({"data": {"attributes": {"identifier": LEI}}})


# -- fechas inclusivas ------------------------------------------------------


def test_inclusive_date_medianoche_exclusiva_se_resta_un_dia():
    assert _inclusive_date("2026-01-01T00:00:00") == "2025-12-31"
    assert _inclusive_date("2026-01-01T00:00:00Z") == "2025-12-31"
    assert _inclusive_date("2026-01-01T00:00:00+01:00") == "2025-12-31"


def test_inclusive_date_fecha_simple_no_se_toca():
    assert _inclusive_date("2025-12-31") == "2025-12-31"
    # hora distinta de medianoche: no es la firma del instante exclusivo
    assert _inclusive_date("2026-01-01T09:30:00") == "2026-01-01"


def test_inclusive_date_invalida_degrada_a_prefijo():
    assert _inclusive_date("2026-13-99T00:00:00") == "2026-13-99"


def test_parse_period_duracion_e_instante():
    assert parse_period("2025-01-01/2026-01-01T00:00:00") == {"start": "2025-01-01", "end": "2025-12-31"}
    assert parse_period("2026-01-01T00:00:00") == {"instant": "2025-12-31"}


# -- normalize_xbrl_json ----------------------------------------------------


def test_normalize_xbrl_json_layout_y_filtros():
    doc = {
        "facts": {
            "f1": {
                "value": "100", "decimals": "0",
                "dimensions": {
                    "concept": "ifrs-full:Revenue", "period": "2025-01-01/2026-01-01T00:00:00",
                    "unit": "EUR", "entity": f"scheme:{LEI}",
                },
            },
            "f2": {  # hecho dimensional (miembro): dims lo declara, no se pierde
                "value": "30", "decimals": "0",
                "dimensions": {
                    "concept": "ifrs-full:Revenue", "period": "2026-01-01T00:00:00",
                    "unit": "EUR", "entity": f"scheme:{LEI}", "ifrs-full:SegmentsAxis": "x",
                },
            },
            "f3": {"value": "1"},          # sin dimensions: se descarta
            "f4": {"dimensions": {"concept": "", "period": "2025-12-31"}},  # sin concepto: descartado
        }
    }
    out = normalize_xbrl_json(doc)
    entries = out["ifrs-full:Revenue"]["EUR"]
    assert len(entries) == 2
    base = [e for e in entries if e["dims"] == []][0]
    assert base["val"] == "100" and base["decimals"] == "0"
    assert base["start"] == "2025-01-01" and base["end"] == "2025-12-31"
    assert base["lei"] == LEI
    member = [e for e in entries if e["dims"]][0]
    assert member["dims"] == ["ifrs-full:SegmentsAxis"]


def test_normalize_xbrl_json_unit_por_defecto_pure():
    doc = {"facts": {"f": {"dimensions": {"concept": "ifrs-full:X", "period": "2025-12-31"}}}}
    out = normalize_xbrl_json(doc)
    assert "pure" in out["ifrs-full:X"]


def test_normalize_xbrl_json_sin_facts_falla_cerrado():
    with pytest.raises(EsefError, match="schema drift"):
        normalize_xbrl_json({"no_facts": {}})


# -- EsefClient -------------------------------------------------------------


def test_client_404_es_dato_inexistente_no_fuente_caida():
    before = _esef_failures()

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={}, request=request)

    async def probe():
        client = EsefClient(client=_client(handler))
        await client.get_entity_name(LEI)

    with pytest.raises(EsefError):
        run_async(probe())
    assert _esef_failures() == before


def test_client_500_registra_fallo():
    before = _esef_failures()

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={}, request=request)

    async def probe():
        client = EsefClient(client=_client(handler))
        await client.get_entity_name(LEI)

    with pytest.raises(EsefError):
        run_async(probe())
    assert _esef_failures() == before + 1


def test_list_all_filings_pagina_hasta_el_total():
    page1 = _page([{"attributes": {"fxo_id": LEI + "a", "country": "ES", "json_url": f"/{LEI}/a.json"}}], total=3)
    page2 = _page([{"attributes": {"fxo_id": LEI + "b", "country": "ES", "json_url": f"/{LEI}/b.json"}}], total=3)
    seen_pages = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen_pages.append(request.url.params["page[number]"])
        return httpx.Response(200, json=page1 if request.url.params["page[number]"] == "1" else page2, request=request)

    async def probe():
        client = EsefClient(client=_client(handler))
        return await client.list_all_filings(country="ES", page_size=2)

    filings = run_async(probe())
    assert seen_pages == ["1", "2"]
    assert [f.fxo_id for f in filings] == [LEI + "a", LEI + "b"]


def test_fetch_filing_json_sin_render_falla_cerrado():
    filing = EsefFiling(
        fxo_id="fx1", lei=LEI, country="ES", period_end=None,
        json_url=None, package_url=f"/{LEI}/pkg.zip", sha256=None,
        error_count=None, warning_count=None,
    )
    client = EsefClient(client=_client(lambda r: httpx.Response(200, json={}, request=r)))
    with pytest.raises(EsefError, match="no xBRL-JSON render"):
        run_async(client.fetch_filing_json(filing))


def test_fetch_filing_json_pide_json_plano():
    filing = EsefFiling(
        fxo_id="fx1", lei=LEI, country="ES", period_end=None,
        json_url=f"/{LEI}/doc.json", package_url=None, sha256=None,
        error_count=None, warning_count=None,
    )
    seen = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["accept"] = request.headers.get("accept")
        return httpx.Response(200, json={"facts": {}}, request=request)

    async def probe():
        client = EsefClient(client=_client(handler))
        return await client.fetch_filing_json(filing)

    assert run_async(probe()) == {"facts": {}}
    assert seen["accept"] == "application/json"


# -- read_esef_snapshot -----------------------------------------------------


def _settings_with_snapshot_dir(monkeypatch, base):
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "esef_snapshot_dir", str(base) if base else None)


def test_snapshot_sin_directorio_configurado_es_none(monkeypatch):
    _settings_with_snapshot_dir(monkeypatch, None)
    assert read_esef_snapshot("AENA.MC") is None


def test_snapshot_manifest_ausente_o_corrupto_es_none(monkeypatch, tmp_path):
    _settings_with_snapshot_dir(monkeypatch, tmp_path)
    assert read_esef_snapshot("AENA.MC") is None
    (tmp_path / "manifest.json").write_text("{no json")
    assert read_esef_snapshot("AENA.MC") is None


def test_snapshot_por_ticker_mc_y_as(monkeypatch, tmp_path):
    _settings_with_snapshot_dir(monkeypatch, tmp_path)
    manifest = {"issuers": {LEI: {"ticker": "AENA"}}}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    snap_dir = tmp_path / "snapshots"
    snap_dir.mkdir()
    (snap_dir / f"{LEI}.json").write_text(json.dumps({"ifrs-full:Revenue": {}}))
    assert read_esef_snapshot("AENA.MC") == {"ifrs-full:Revenue": {}}
    assert read_esef_snapshot("AENA.AS") == {"ifrs-full:Revenue": {}}  # tambien Euronext
    assert read_esef_snapshot("OTRA.MC") is None


def test_snapshot_fichero_corrupto_es_none(monkeypatch, tmp_path):
    _settings_with_snapshot_dir(monkeypatch, tmp_path)
    (tmp_path / "manifest.json").write_text(json.dumps({"issuers": {LEI: {"ticker": "AENA"}}}))
    snap_dir = tmp_path / "snapshots"
    snap_dir.mkdir()
    (snap_dir / f"{LEI}.json").write_text("no json")
    assert read_esef_snapshot("AENA.MC") is None
