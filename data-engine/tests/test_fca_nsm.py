"""NSM de la FCA como segunda fuente ESEF/UKSEF (fuentes-1, 8-nov-2026).

Medido ese dia: filings.xbrl.org va un ano por detras con el Reino Unido
(Associated British Foods: lo ultimo del indice es FY2025, cierre
2025-09-13; su ESEF FY2026, cierre 2026-09-12, esta en el NSM desde el
2026-11-05) y no tiene a Georgia Capital PLC (0 entidades; sus informes
anuales 2021-2025 estan en el NSM sin etiquetar). Sin red: MockTransport con
la forma real de la API del NSM y de los paquetes.
"""

from __future__ import annotations

import asyncio
import io
import json
import zipfile
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.entities import Base, Company, Document, FinancialFact
from app.services import esef_live
from app.services import financial_ingestion_service as ingestion
from app.services.connectors import esef as esef_connector
from app.services.connectors import fca_nsm
from app.services.financial_ingestion_service import FinancialIngestionService

LEI = "GBQKSY6W7G0OHCQ8OQ72"  # Associated British Foods plc
GC_LEI = "213800Q65T5GNBOW7H65"  # Georgia Capital PLC
OTHER_LEI = "549300OTHEROTHER0001"


def _ixbrl(lei: str, end: str, start: str, revenue: str, cash: str, op: str) -> bytes:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
 xmlns:xbrli="http://www.xbrl.org/2003/instance" xmlns:iso4217="http://www.xbrl.org/2003/iso4217"
 xmlns:ifrs-full="https://xbrl.ifrs.org/taxonomy/2024-03-27/ifrs-full"
 xmlns:ixt4="http://www.xbrl.org/inlineXBRL/transformation/2020-02-12"><head/><body>
<ix:header><ix:resources>
<xbrli:context id="d"><xbrli:entity><xbrli:identifier scheme="http://standards.iso.org/iso/17442">{lei}</xbrli:identifier></xbrli:entity>
<xbrli:period><xbrli:startDate>{start}</xbrli:startDate><xbrli:endDate>{end}</xbrli:endDate></xbrli:period></xbrli:context>
<xbrli:context id="i"><xbrli:entity><xbrli:identifier scheme="http://standards.iso.org/iso/17442">{lei}</xbrli:identifier></xbrli:entity>
<xbrli:period><xbrli:instant>{end}</xbrli:instant></xbrli:period></xbrli:context>
<xbrli:unit id="gbp"><xbrli:measure>iso4217:GBP</xbrli:measure></xbrli:unit>
</ix:resources></ix:header>
<p><ix:nonFraction name="ifrs-full:Revenue" format="ixt4:num-dot-decimal" contextRef="d" unitRef="gbp" decimals="-6" scale="6">{revenue}</ix:nonFraction></p>
<p><ix:nonFraction name="ifrs-full:ProfitLossFromOperatingActivities" format="ixt4:num-dot-decimal" contextRef="d" unitRef="gbp" decimals="-6" scale="6">{op}</ix:nonFraction></p>
<p><ix:nonFraction name="ifrs-full:CashAndCashEquivalents" format="ixt4:num-dot-decimal" contextRef="i" unitRef="gbp" decimals="-6" scale="6">{cash}</ix:nonFraction></p>
</body></html>""".encode()


def _package(lei: str, end: str, report: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        # Forma real del paquete de ABF FY2026: informe .html en reports/.
        zf.writestr(f"{lei}-{end}/reports/{lei}-{end}-T01.html", report)
        zf.writestr(f"{lei}-{end}/META-INF/reportPackage.json", "{}")
    return buf.getvalue()


def _hit(lei, company, ftype, fmt, submitted, link, did):
    return {"_id": did, "_source": {
        "lei": lei, "company": company, "type": ftype, "document_format": fmt,
        "tag_esef": fmt if fmt in {"Tagged", "Untagged"} else "",
        "submitted_date": f"{submitted}T10:00:00Z", "download_link": link, "disclosure_id": did,
    }}


ABF_HITS = [
    _hit(LEI, "ASSOCIATED BRITISH FOODS PLC;", "Annual Financial Report", "PDF", "2026-11-05",
         "NSM/DirectUpload/NI-000154216/NI-000154216.pdf", "154216"),
    _hit(LEI, "ASSOCIATED BRITISH FOODS PLC;", "Annual Financial Report", "Tagged", "2026-11-05",
         f"NSM/DirectUpload/NI-000154213/NI-000154213_{LEI}-2026-09-12.xbri", "154213"),
    _hit(LEI, "ASSOCIATED BRITISH FOODS PLC;", "Annual Financial Report", "Tagged", "2025-11-06",
         f"NSM/DirectUpload/NI-000133011/NI-000133011_{LEI}-2025-09-13.zip", "133011"),
]

GC_HITS = [
    _hit(GC_LEI, "Georgia Capital PLC", "Annual Financial Report", "Untagged", "2026-04-24",
         f"NSM/DirectUpload/NI-000143657/NI-000143657_{GC_LEI}-2025-12-31.xhtml", "143657"),
    _hit(GC_LEI, "Georgia Capital PLC", "Annual Financial Report", "Plain text", "2026-04-23",
         "NSM/RNS/21b45652.html", "21b45652"),
]


def _index_doc(lei, start, end, revenue):
    return {"documentInfo": {}, "facts": {
        "f1": {"value": str(revenue), "decimals": -6, "dimensions": {
            "concept": "ifrs-full:Revenue", "entity": f"http://standards.iso.org/iso/17442:{lei}",
            # xBRL-JSON: fin exclusivo (el dia siguiente al cierre).
            "period": f"{start}T00:00:00/{end}T00:00:00", "unit": "iso4217:GBP"}},
    }}


def _handler(*, nsm_hits, index_rows=None, packages=None, calls=None, gleif=None):
    packages = packages or {}

    def handle(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if calls is not None:
            calls.append(url)
        if "api.gleif.org" in url:
            lei, legal = gleif or (LEI, "ASSOCIATED BRITISH FOODS PLC")
            return httpx.Response(200, json={"data": [{"type": "lei-records", "id": lei, "attributes": {
                "lei": lei, "entity": {"legalName": {"name": legal}, "jurisdiction": "GB"},
                "registration": {"status": "ISSUED"}}}]})
        if url.startswith(fca_nsm.NSM_SEARCH_URL):
            body = json.loads(request.content)
            lei = body["criteriaObj"]["criteria"][0]["value"][1]
            hits = [h for h in nsm_hits if h["_source"]["lei"] == lei]
            return httpx.Response(200, json={"hits": {"total": {"value": len(hits)}, "hits": hits}})
        if url.startswith(fca_nsm.NSM_ARTEFACTS_BASE):
            blob = packages.get(url[len(fca_nsm.NSM_ARTEFACTS_BASE):])
            return httpx.Response(200, content=blob) if blob is not None else httpx.Response(404)
        if "/api/entities/" in url and url.split("?")[0].endswith("/filings"):
            rows = index_rows or []
            if not rows:
                return httpx.Response(404, json={"errors": [{"status": "404"}]})
            return httpx.Response(200, json={"data": rows, "meta": {"count": len(rows)}})
        if "/api/entities/" in url:
            return httpx.Response(200, json={"data": {"attributes": {"identifier": LEI, "name": "ASSOCIATED BRITISH FOODS PLC"}}})
        if url.endswith(".json"):
            return httpx.Response(200, content=json.dumps(_index_doc(LEI, "2024-09-15", "2025-09-14", 19459000000)))
        return httpx.Response(404)
    return handle


def _index_row(lei, end):
    path = f"/{lei}/{end}/ESEF/GB/0/{lei}-{end}-T01.json"
    return {"type": "filing", "id": end, "attributes": {
        "fxo_id": f"{lei}-{end}-ESEF-GB-0", "country": "GB", "period_end": end,
        "json_url": path, "package_url": None, "sha256": f"sha{end}", "error_count": 0, "warning_count": 0}}


@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    monkeypatch.setattr(esef_connector, "_MIN_INTERVAL_S", 0.0)
    monkeypatch.setattr(fca_nsm, "_MIN_INTERVAL_S", 0.0)
    monkeypatch.setattr(ingestion.esef_connector, "read_esef_snapshot", lambda ticker: None)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _company(ticker="ABF.L", name="Associated British Foods plc", isin=None):
    return Company(
        ticker=ticker, name=name, exchange="LSE", currency="GBP", sector="S", industry="I",
        company_type="research_candidate", valuation_model="unassigned",
        special_sources=[], special_risks=[], factor_tags=[], isin=isin,
    )


def _snapshot(company, handler):
    transport = httpx.MockTransport(handler)

    async def go():
        http = httpx.AsyncClient(transport=transport)
        esef = esef_connector.EsefClient(client=httpx.AsyncClient(
            transport=transport, base_url=esef_connector.ESEF_BASE_URL))
        return await esef_live.fetch_live_snapshot(company, esef=esef, http=http)

    return asyncio.run(go())


ABF_PACKAGES = {
    f"NSM/DirectUpload/NI-000154213/NI-000154213_{LEI}-2026-09-12.xbri": _package(
        LEI, "2026-09-12", _ixbrl(LEI, "2026-09-12", "2025-09-14", "19,582", "1,010", "1,327")),
    f"NSM/DirectUpload/NI-000133011/NI-000133011_{LEI}-2025-09-13.zip": _package(
        LEI, "2025-09-13", _ixbrl(LEI, "2025-09-13", "2024-09-15", "19,459", "1,057", "1,483")),
}


# -- parser de la API -------------------------------------------------------


def test_hits_cierre_del_ejercicio_sale_del_nombre_del_paquete():
    rows = fca_nsm.parse_search_hits({"hits": {"hits": ABF_HITS + GC_HITS}}, lei=LEI)
    assert [r.disclosure_id for r in rows] == ["154216", "154213", "133011"]  # GC_HITS es otro LEI
    tagged = fca_nsm.tagged_annual_reports(rows)
    assert [(f.period_end, f.tagged) for f in tagged] == [("2026-09-12", True), ("2025-09-13", True)]
    assert tagged[0].url == f"https://data.fca.org.uk/artefacts/NSM/DirectUpload/NI-000154213/NI-000154213_{LEI}-2026-09-12.xbri"


def test_redeposito_del_mismo_ejercicio_gana_el_ultimo():
    again = _hit(LEI, "ABF", "Annual Financial Report", "Tagged", "2026-11-20",
                 f"NSM/DirectUpload/NI-1/NI-1_{LEI}-2026-09-12.zip", "1")
    rows = fca_nsm.parse_search_hits({"hits": {"hits": [*ABF_HITS, again]}}, lei=LEI)
    assert fca_nsm.tagged_annual_reports(rows)[0].disclosure_id == "1"


def test_paquete_con_informe_html_en_reports():
    report, path = fca_nsm.report_from_package(ABF_PACKAGES[ABF_HITS[1]["_source"]["download_link"]])
    assert path.endswith("/reports/GBQKSY6W7G0OHCQ8OQ72-2026-09-12-T01.html")
    assert b"ifrs-full:Revenue" in report


# -- snapshot en vivo -------------------------------------------------------


def test_abf_completa_el_ejercicio_que_el_indice_aun_no_tiene():
    """Antes: lo ultimo era FY2025 (indice). Ahora: FY2026 desde el NSM."""
    snap, reason = _snapshot(
        _company(),
        _handler(nsm_hits=ABF_HITS, index_rows=[_index_row(LEI, "2025-09-13")], packages=ABF_PACKAGES),
    )
    assert reason == "ok", reason
    assert snap["periods"] == ["2026-09-12", "2025-09-13"]
    assert snap["period_end"] == "2026-09-12"
    origins = [(s["period_end"], s["origin"]) for s in snap["filing_sources"]]
    # En empate (FY2025 en ambos) gana el indice, ya validado.
    assert origins == [("2026-09-12", "fca_nsm"), ("2025-09-13", "filings.xbrl.org")]
    nsm_src = snap["filing_sources"][0]
    assert nsm_src["url"].startswith("https://data.fca.org.uk/artefacts/NSM/DirectUpload/NI-000154213/")
    assert nsm_src["submitted_date"] == "2026-11-05" and len(nsm_src["sha256"]) == 64
    revenue = {e["end"]: e["val"] for e in snap["facts"]["ifrs-full:Revenue"]["iso4217:GBP"] if not e["dims"]}
    assert Decimal(revenue["2026-09-12"]) == Decimal("19582000000")
    assert Decimal(revenue["2025-09-13"]) == Decimal("19459000000")


def test_emisor_britanico_que_el_indice_no_tiene_entra_por_el_nsm(db, monkeypatch):
    calls: list[str] = []
    handler = _handler(nsm_hits=ABF_HITS, index_rows=[], packages=ABF_PACKAGES, calls=calls)
    transport = httpx.MockTransport(handler)
    real = esef_live.fetch_live_snapshot

    async def fake(company, **_):
        http = httpx.AsyncClient(transport=transport)
        esef = esef_connector.EsefClient(client=httpx.AsyncClient(transport=transport, base_url=esef_connector.ESEF_BASE_URL))
        return await real(company, esef=esef, http=http)

    monkeypatch.setattr(esef_live, "fetch_live_snapshot", fake)
    monkeypatch.setattr(esef_live, "live_lookup_enabled", lambda: True)
    company = _company()
    db.add(company)
    db.commit()
    result = asyncio.run(FinancialIngestionService().refresh_from_esef(db=db, company=company))
    assert result["provider"] == "ESEF" and result["period_end"] == "2026-09-12"
    facts = {(f.metric, f.fiscal_year): f for f in db.scalars(
        select(FinancialFact).where(FinancialFact.company_id == company.id))}
    assert facts[("revenue", 2026)].value == Decimal("19582000000")
    assert facts[("revenue", 2026)].unit == "GBP" and facts[("revenue", 2026)].is_reported
    assert facts[("revenue", 2025)].value == Decimal("19459000000")
    doc = db.get(Document, result["source_document_id"])
    assert [s["origin"] for s in doc.metadata_["filing_sources"]] == ["fca_nsm", "fca_nsm"]
    assert "National Storage Mechanism" in doc.metadata_["source"]
    assert any(c.startswith(fca_nsm.NSM_SEARCH_URL) for c in calls)


def test_paquete_de_otra_entidad_se_descarta():
    wrong = {k: _package(LEI, "2026-09-12", _ixbrl(OTHER_LEI, "2026-09-12", "2025-09-14", "1", "1", "1"))
             for k in ABF_PACKAGES}
    snap, reason = _snapshot(_company(), _handler(nsm_hits=ABF_HITS, index_rows=[], packages=wrong))
    assert snap is None and reason == "filings_ilegibles"


@pytest.mark.parametrize("identifier", ["", "   ", None])
def test_paquete_sin_identificador_de_entidad_se_descarta(identifier):
    report = _ixbrl(LEI, "2026-09-12", "2025-09-14", "1", "1", "1")
    original = (
        '<xbrli:identifier scheme="http://standards.iso.org/iso/17442">'
        f"{LEI}</xbrli:identifier>"
    ).encode()
    replacement = b"" if identifier is None else original.replace(LEI.encode(), identifier.encode())
    report = report.replace(original, replacement)
    packages = {key: _package(LEI, "2026-09-12", report) for key in ABF_PACKAGES}
    snap, reason = _snapshot(_company(), _handler(nsm_hits=ABF_HITS, index_rows=[], packages=packages))
    assert snap is None and reason == "filings_ilegibles"


def test_georgia_capital_solo_sin_etiquetar_da_motivo_con_la_url():
    snap, reason = _snapshot(
        _company("CGEO.L", "Georgia Capital PLC"),
        _handler(nsm_hits=GC_HITS, gleif=(GC_LEI, "GEORGIA CAPITAL PLC")),
    )
    assert snap is None
    assert reason.startswith("nsm_sin_etiquetar: 2 informes anuales en el NSM de la FCA, ninguno con iXBRL")
    assert f"https://data.fca.org.uk/artefacts/NSM/DirectUpload/NI-000143657/NI-000143657_{GC_LEI}-2025-12-31.xhtml" in reason


def test_emisor_de_la_ue_con_indice_no_consulta_el_nsm():
    calls: list[str] = []
    rows = [_index_row(LEI, "2025-09-13")]
    rows[0]["attributes"]["country"] = "NL"
    snap, reason = _snapshot(
        _company("BFIT.AS", "Associated British Foods plc"),
        _handler(nsm_hits=ABF_HITS, index_rows=rows, calls=calls),
    )
    assert reason == "ok"
    assert not any(c.startswith(fca_nsm.NSM_SEARCH_URL) for c in calls)
    assert [s["origin"] for s in snap["filing_sources"]] == ["filings.xbrl.org"]
