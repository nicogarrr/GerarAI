"""Companies House: cliente, grupo britanico verificado por PSC, cifras iXBRL y su uso
en el desglose por partes y en el respaldo de informes de emisores britanicos.

Todo con respuestas grabadas de la API real el 8-nov-2026 (sin red en los tests):
``replay_ffh_cgeo.json.gz`` (busquedas, PSC, administradores, historial y metadatos
de documentos de Fairfax y Georgia Capital) y dos cuentas iXBRL reales.
"""

from __future__ import annotations

import asyncio
import base64
import gzip
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app.services import companies_house_evidence as ev
from app.services.connectors import companies_house as ch
from app.services.connectors.esef_ixbrl import _transform_numeric

FIXTURES = Path(__file__).parent / "fixtures" / "companies_house"
FAKE_KEY = "00000000-test-key-not-real-000000000"


def _replay() -> dict:
    return json.loads(gzip.decompress((FIXTURES / "replay_ffh_cgeo.json.gz").read_bytes()))


def _ixbrl(number: str) -> bytes:
    return gzip.decompress((FIXTURES / f"accounts_{number}.xhtml.gz").read_bytes())


class Replay(httpx.AsyncBaseTransport):
    """Sirve las respuestas grabadas; una peticion no grabada es un fallo del test (sin red)."""

    def __init__(self, log: dict, documents: dict[str, bytes] | None = None) -> None:
        self.log, self.documents, self.seen = log, documents or {}, []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        url = request.url
        self.seen.append(request)
        if url.host == "s3.example":
            return httpx.Response(200, content=self.documents[url.path.strip("/")],
                                  headers={"content-type": "application/xhtml+xml"})
        query = "&".join(sorted(url.query.decode().split("&"))) if url.query else ""
        key = f"{url.host}{url.path}?{query} {request.headers.get('accept', '')}"
        entry = self.log.get(key)
        assert entry is not None, f"peticion no grabada: {key}"
        if "location" in entry:
            return httpx.Response(entry["status"], headers={"location": entry["location"]})
        return httpx.Response(entry["status"], json=entry.get("json"))


# Quién dirige Fairfax según Wikidata (P169/P488/P112): el PSC de FAIRFAX UK HOLDINGS es esa persona.
FFH_PEOPLE = ["Prem Watsa"]


def _client(log: dict | None = None, documents: dict[str, bytes] | None = None, **kw) -> tuple[ch.CompaniesHouseClient, Replay]:
    transport = Replay(_replay() if log is None else log, documents)
    return ch.CompaniesHouseClient(FAKE_KEY, client=httpx.AsyncClient(transport=transport), **kw), transport


# -- cliente -------------------------------------------------------------------------
def test_numero_de_registro_normalizado():
    assert ch.normalize_company_number("7811410") == "07811410"
    assert ch.normalize_company_number(" 08821629 ") == "08821629"
    assert ch.normalize_company_number("SC123") == "SC000123"
    assert ch.normalize_company_number("not a number") is None
    assert ch.normalize_company_number("") is None


def test_basic_con_la_clave_como_usuario_y_la_descarga_firmada_va_sin_clave():
    log = {
        "api.company-information.service.gov.uk/company/07253542/filing-history?category=accounts&items_per_page=10 application/json":
            {"status": 200, "json": {"items": [{
                "date": "2026-08-27", "description": "accounts-with-accounts-type-total-exemption-full",
                "description_values": {"made_up_date": "2025-12-31"}, "transaction_id": "TX1", "type": "AA",
                "links": {"document_metadata": "https://document-api.company-information.service.gov.uk/document/D1"}}]}},
        "document-api.company-information.service.gov.uk/document/D1? application/json":
            {"status": 200, "json": {"resources": {"application/pdf": {}, "application/xhtml+xml": {}}, "pages": 7,
                                     "links": {"document": "https://document-api.company-information.service.gov.uk/document/D1/content"}}},
        "document-api.company-information.service.gov.uk/document/D1/content? application/xhtml+xml":
            {"status": 302, "location": "https://s3.example/trust"},
    }
    client, transport = _client(log, {"trust": _ixbrl("07253542")})
    member = ev.GroupMember("07253542", "TRUST INVESTMENTS LIMITED", 1, "prueba", parent="08821629")
    out = asyncio.run(ev.latest_accounts(client, member))
    assert out is not None
    expected = "Basic " + base64.b64encode(f"{FAKE_KEY}:".encode()).decode()
    gov = [r for r in transport.seen if r.url.host.endswith("service.gov.uk")]
    assert gov and all(r.headers.get("authorization") == expected for r in gov)
    s3 = [r for r in transport.seen if r.url.host == "s3.example"]
    assert s3 and all("authorization" not in r.headers for r in s3)
    assert out["document_url"] == ("https://find-and-update.company-information.service.gov.uk/company/07253542/"
                                   "filing-history/TX1/document?format=pdf&download=0")
    assert out["ixbrl_url"].endswith("/TX1/document?format=xhtml&download=0")
    assert out["made_up_to"] == "2025-12-31" and out["accounts_type"] == "total-exemption-full"
    figures = {f["metric"]: f for f in out["figures"]}
    # Patrimonio neto consolidado (sin ejes) del cierre mas reciente; las 130 £ son el capital (con eje).
    assert figures["net_assets"]["value"] == -652740.0 and figures["net_assets"]["currency"] == "GBP"
    assert figures["net_assets"]["period_end"] == "2025-12-31"


def test_presupuesto_y_ventana_de_600_en_5_minutos():
    client, _ = _client({}, max_requests=1)
    client.requests_used = 1
    with pytest.raises(ch.CompaniesHouseBudgetExceeded):
        asyncio.run(client.search_companies("x"))
    window = ch._RateWindow(limit=2, seconds=300)
    window.record(0.0)
    window.record(10.0)
    assert window.wait_seconds(20.0) == pytest.approx(280.0)
    assert window.wait_seconds(301.0) == 0.0


def test_un_error_no_lleva_la_clave():
    log = {"api.company-information.service.gov.uk/company/00000001? application/json": {"status": 500, "json": {}}}
    client, _ = _client(log)
    with pytest.raises(ch.CompaniesHouseError) as err:
        asyncio.run(client.company_profile("00000001"))
    assert FAKE_KEY not in str(err.value)


def test_sin_clave_la_funcion_esta_apagada(monkeypatch):
    from app.core.config import get_settings

    assert get_settings().companies_house_api_key in (None, "")
    assert ch.client_from_settings() is None
    assert ev.collect_group_accounts("Georgia Capital PLC", []) is None


# -- iXBRL ---------------------------------------------------------------------------
def test_formatos_ixt_de_la_primera_recomendacion_que_usa_companies_house():
    # ixt 2010-04-20 (TR1): numcommadot = 1,234.56 ; numdotcomma = 1.234,56 ; zerodash = 0.
    assert _transform_numeric("1,234,567", "ixt:numcommadot") == 1234567
    assert _transform_numeric("1.234,5", "ixt:numdotcomma") == pytest.approx(1234.5)
    assert _transform_numeric("-", "ixt:zerodash") == 0
    assert _transform_numeric("(12,000)", "ixt:numcommadot") == -12000


def test_cifras_de_unas_cuentas_completas_en_ixbrl():
    figures = {f["metric"]: f for f in ev.figures_from_ixbrl(_ixbrl("04162544"))}
    assert {"revenue", "net_assets", "profit"} <= set(figures)
    for f in figures.values():
        assert f["currency"] == "GBP" and f["period_end"] and f["concept"].split(":")[-1]
        assert f["value_millions"] == pytest.approx(f["value"] / 1e6)
    assert figures["revenue"]["value"] == 605530.0 and figures["revenue"]["period_start"] == "2025-03-01"
    assert figures["revenue"]["concept"].endswith(":TurnoverRevenue")
    assert figures["profit"]["value"] == -46682.0 and figures["net_assets"]["value"] == 237555.0


# -- grupo verificado por PSC ----------------------------------------------------------
def test_fairfax_grupo_britanico_por_la_cadena_de_psc():
    client, _ = _client()
    result = asyncio.run(ev.group_accounts(client, holding_name="Fairfax Financial Holdings Limited",
                                           hints=["Brit", "Allied World"], people=FFH_PEOPLE))
    rows = {r["company_number"]: r for r in result["members"]}
    assert result["status"] == "ok"
    # La pista «Brit» (nombre anterior) lleva a FAIRFAX UK HOLDINGS, con el nombre del holding y su PSC
    # (Prem Watsa, que dirige Fairfax): el nombre solo ya no basta.
    assert rows["08821629"]["depth"] == 0 and "nombre del holding" in rows["08821629"]["via"]
    assert "Prem Watsa" in rows["08821629"]["via"]
    assert rows["15884169"]["parent"] == "08821629"  # BRIT GROUP HOLDINGS
    assert rows["03121594"]["parent"] == "15884169"  # BRIT INSURANCE HOLDINGS
    assert rows["00824611"]["parent"] == "03121594"  # BRIT SYNDICATES
    assert rows["15884169"]["accounts_type"] == "group" and rows["15884169"]["made_up_to"] == "2025-12-31"
    assert all(r["document_url"].startswith(ch.PUBLIC_BASE_URL) for r in rows.values())
    names = " ".join(r["company_name"].upper() for r in rows.values())
    assert "FAIRFAX LTD" not in names  # mismo nombre, otro grupo: no entra
    assert "ALLIED WORLD" not in names  # su cadena de PSC no llega a Fairfax por el Reino Unido
    assert result["requests_used"] <= 120


def test_georgia_capital_raiz_por_nombre_exacto_sin_filiales_britanicas():
    client, _ = _client()
    result = asyncio.run(ev.group_accounts(client, holding_name="Georgia Capital PLC", hints=[]))
    assert [(r["company_number"], r["via"]) for r in result["members"]] == [("10852406", "nombre exacto del holding")]
    row = result["members"][0]
    assert row["accounts_type"] == "full" and row["pages"] == 231 and row["figures"] == []
    assert ev.subsidiary_reports(result) == []  # la propia raiz es el emisor, no una filial


def test_lo_que_se_lee_entero_es_la_consolidada_del_grupo():
    client, _ = _client()
    result = asyncio.run(ev.group_accounts(client, holding_name="Fairfax Financial Holdings Limited",
                                           hints=["Brit", "Allied World"], people=FFH_PEOPLE))
    picked = ev.subsidiary_reports(result)
    assert [p["company_number"] for p in picked] == ["15884169"]


def test_nombres_y_nombre_propio():
    assert ev.normalize_name("Georgia Capital Public Limited Company") == ev.normalize_name("GEORGIA CAPITAL PLC")
    assert ev.distinctive_token("Fairfax Financial Holdings Ltd") == "FAIRFAX"
    assert ev.distinctive_token("The Capital Group Holdings") is None


# -- desglose por partes ----------------------------------------------------------------
def test_salidas_del_sotp_citan_companies_house():
    from app.services.expert_team.sotp_valuer import SOTP_VALUER_TOOLS, companies_house_outputs

    assert "companies_house" in SOTP_VALUER_TOOLS
    client, _ = _client()
    result = asyncio.run(ev.group_accounts(client, holding_name="Fairfax Financial Holdings Limited",
                                           hints=["Brit", "Allied World"], people=FFH_PEOPLE))
    outs = companies_house_outputs(result)
    assert len(outs) == len(result["members"])
    brit = next(o for o in outs if o.data["numero"] == "15884169")
    assert brit.source["url"].startswith("https://find-and-update.company-information.service.gov.uk/company/15884169/")
    assert "15884169" in brit.source["title"] and "Companies House" in brit.source["title"]
    assert brit.data["cifras"] is None and "PDF" in brit.data["nota"]

    fig = companies_house_outputs({"members": [{
        "company_number": "04162544", "company_name": "ENGINEERING SERVICES SKILLCARD LTD", "accounts_type": "full",
        "made_up_to": "2025-03-31", "document_url": "https://find-and-update.company-information.service.gov.uk/x",
        "ixbrl_url": "https://find-and-update.company-information.service.gov.uk/x?format=xhtml",
        "figures": ev.figures_from_ixbrl(_ixbrl("04162544"))}]})[0]
    assert fig.source["url"].endswith("format=xhtml")
    assert fig.data["cifras"]["revenue"]["moneda"] == "GBP" and fig.data["quote"]


def test_la_herramienta_no_corre_para_empresas_con_cik(monkeypatch):
    from app.services.expert_team.models import RunContext
    from app.services.expert_team.sotp_valuer import companies_house_tool

    company = SimpleNamespace(id=1, ticker="AAPL", name="Apple Inc.", cik="0000320193")

    class _DB:
        def scalars(self, _q):
            return SimpleNamespace(first=lambda: company)

    called = []
    monkeypatch.setattr(ev, "collect_group_accounts", lambda *a, **k: called.append(a) or {"members": []})
    out = companies_house_tool(_DB()).fn(RunContext(ticker="AAPL", tenant_id=1))
    assert out == [] and called == []


# -- respaldo de informes del emisor britanico ------------------------------------------
def test_emisor_britanico_sin_informe_del_nsm_usa_las_cuentas_de_companies_house(monkeypatch):
    from app.services import esef_live, issuer_reports

    async def no_lei(company, **kwargs):
        return None, "sin LEI en GLEIF"

    monkeypatch.setattr(esef_live, "resolve_issuer", no_lei)
    client, _ = _client()
    monkeypatch.setattr(ch, "client_from_settings", lambda **kw: client)
    company = SimpleNamespace(ticker="CGEO.L", name="Georgia Capital PLC", ir_url=None)
    links, reason = asyncio.run(issuer_reports.discover_reports(company))
    assert reason.startswith("companies_house") and "sin_lei" in reason
    assert [link.kind for link in links] == ["annual"]
    link = links[0]
    assert link.source == "Companies House" and "2025-12-31" in link.title
    assert link.url == ("https://find-and-update.company-information.service.gov.uk/company/10852406/"
                        "filing-history/MzUyOTE5MTI0MmFkaXF6a2N4/document?format=pdf&download=0")


def test_la_tesis_encola_la_consolidada_de_la_filial_con_su_nombre(monkeypatch):
    from app.services.thesis_evidence_service import ThesisEvidenceService

    client, _ = _client()
    result = asyncio.run(ev.group_accounts(client, holding_name="Fairfax Financial Holdings Limited",
                                           hints=["Brit", "Allied World"], people=FFH_PEOPLE))
    sent = []
    monkeypatch.setattr(ThesisEvidenceService, "_fetch_uk_group", lambda self, company, hints, people=None: result)
    monkeypatch.setattr(ev, "subsidiary_hints", lambda db, company, tenant: ["Brit"])
    monkeypatch.setattr("app.services.thesis_evidence_service.annual_report_has_text", lambda db, cid, url: False)
    import app.workers.dramatiq_app as actors

    monkeypatch.setattr(actors.process_document, "send", lambda *a, **k: sent.append((a, k)))
    db = SimpleNamespace(info={"tenant_id": 1, "user_id": "u"})
    company = SimpleNamespace(id=7, ticker="FFH.TO", name="Fairfax Financial Holdings Limited")
    items = ThesisEvidenceService()._uk_subsidiary_reports(db, company)  # type: ignore[arg-type]
    assert [(i["kind"], i["company_number"], i["text"]) for i in items] == [("subsidiary_accounts", "15884169", "queued")]
    (args, kwargs), = sent
    assert "Brit Group Holdings Limited" in args[1] and "filial británica" in args[1]
    assert args[3] == "companies_house" and kwargs["filing_metadata"]["company_number"] == "15884169"


def test_pistas_de_filiales_desde_los_alias_verificados(monkeypatch):
    from app.services import company_alias_sources as cas

    record = cas.AliasRecord(ticker="FFH.TO", aliases=[
        cas.AliasTerm("Brit Insurance", "filial", "wikidata"),
        cas.AliasTerm("Odyssey Re", "filial", "wikidata"),
        cas.AliasTerm("Prem Watsa", "persona", "wikidata"),
        cas.AliasTerm("Recipe", "filial", "texto", etiqueta=cas.INFERRED),
    ])
    monkeypatch.setattr(cas, "load_cached", lambda db: {"FFH.TO": record})
    company = SimpleNamespace(id=1, ticker="FFH.TO", name="Fairfax Financial Holdings Limited")
    assert ev.subsidiary_hints(object(), company, None) == ["Brit Insurance", "Odyssey Re"]
