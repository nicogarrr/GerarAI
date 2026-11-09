"""Mapeo general de extensiones XBRL/ESEF (FRE/DE de gestoras, capex propio, deuda ESEF).

Fixtures: recortes de los filings REALES (descargados gratis de EDGAR y de
filings.xbrl.org el 9-nov-2026), con sus hechos, etiquetas, cálculo y
anclajes tal como los publicó el emisor:
* KKR 10-K 2025 (0001404912-26-000007): ``kkr:FeeRelatedIncomeLoss`` solo en el segmento de gestión de activos;
* Brookfield 40-F 2025 (0001001085-26-000006): ``bn:DistributableEarnings`` solo por segmentos;
* CNQ 40-F 2025 (0001017413-26-000018): capex en ``cnq:CashFlowsFromUsedInPropertyPlantandEquipment…``;
* Airbus ESEF 2025 (LEI MINO79WLOO247M1IL051): deuda y capex en conceptos ``airbus:`` anclados.
"""

import asyncio
import copy
import gzip
import io
import json
import zipfile
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.entities import Base, Company, Document, FinancialFact
from app.services import esef_live, sec_extension_facts
from app.services import financial_ingestion_service as ingestion
from app.services import xbrl_extension_map as xm
from app.services.connectors.esef import normalize_xbrl_json
from app.services.financial_ingestion_service import FinancialIngestionService

FIX = Path(__file__).parent / "fixtures" / "xbrl_extensions"


def _read(name: str) -> bytes:
    return gzip.decompress((FIX / f"{name}.gz").read_bytes())


def _sec(stem: str, metrics=None):
    tax = xm.build_taxonomy(lab=_read(f"{stem}_lab.xml"), cal=_read(f"{stem}_cal.xml"))
    return xm.resolve_extensions(tax, xm.parse_instance_facts(_read(f"{stem}_htm.xml")), metrics=metrics)


def _values(mapping: xm.ExtensionMapping) -> dict[str, Decimal]:
    return {end: val for (_start, end), val in mapping.values.items()}


def _airbus():
    facts = normalize_xbrl_json(json.loads(_read("airbus-2025_xbrl.json")))
    tax = xm.build_taxonomy(lab=_read("airbus-2025_lab-en.xml"), cal=_read("airbus-2025_cal.xml"),
                            defn=_read("airbus-2025_def.xml"))
    return facts, tax


# ---------------------------------------------------------------- reglas puras


def test_kkr_fre_por_etiqueta_en_su_unico_segmento():
    res = _sec("kkr-20251231")["fee_related_earnings"]
    assert isinstance(res, xm.ExtensionMapping)
    assert res.concept == "kkr:FeeRelatedIncomeLoss"
    assert res.rule == xm.RULE_LABEL
    assert res.segment == "kkr:AssetManagementSegmentMember"
    assert _values(res) == {"2025-12-31": Decimal("3714313000"), "2024-12-31": Decimal("3267796000"),
                            "2023-12-31": Decimal("2383786000")}
    assert "Fee Related Income (Loss)" in res.evidence and "AssetManagementSegmentMember" in res.evidence


def test_kkr_sin_de_etiquetado_queda_nd_con_motivo():
    res = _sec("kkr-20251231")["distributable_earnings"]
    assert isinstance(res, xm.NotAvailable)
    assert "ningún concepto de extensión" in res.motivo


def test_bn_de_solo_por_segmentos_no_se_suma_nd():
    res = _sec("bn-20251231")["distributable_earnings"]
    assert isinstance(res, xm.NotAvailable)
    assert "solo por segmento (2:" in res.motivo
    assert "AssetManagementSegmentMember" in res.motivo and "ReinsuranceMember" in res.motivo
    assert "sin total consolidado" in res.motivo


def test_cnq_capex_por_calculo_y_etiqueta_con_signo_estandar():
    res = _sec("cnq-20251231")["capital_expenditure"]
    assert isinstance(res, xm.ExtensionMapping)
    assert res.concept == "cnq:CashFlowsFromUsedInPropertyPlantandEquipmentClassifiedAsInvestingActivities"
    assert res.rule == xm.RULE_CALC
    assert res.unit == "CAD"
    # Declarado NEGATIVO con peso +1 en los flujos de inversión: la salida de caja
    # es la del «Purchase of PP&E» estándar (positiva, peso −1).
    assert res.sign == -1
    assert _values(res) == {"2025-12-31": Decimal("6676000000"), "2024-12-31": Decimal("5291000000"),
                            "2023-12-31": Decimal("4865000000")}
    assert "ifrs-full:CashFlowsFromUsedInInvestingActivities" in res.evidence


def test_cnq_no_confunde_partidas_del_inmovilizado_que_no_son_capex():
    # Las extensiones de la nota de PP&E (adiciones, costes capitalizados,
    # exploración) no suman en los flujos de inversión: no son candidatas.
    res = _sec("cnq-20251231", metrics=["capital_expenditure"])["capital_expenditure"]
    assert isinstance(res, xm.ExtensionMapping)
    assert "Exploration" not in res.concept and "Capitalised" not in res.concept


def test_airbus_deuda_y_capex_por_anclaje_esef():
    facts, tax = _airbus()
    res = xm.resolve_extensions(tax, xm.facts_from_xbrl_json(facts))
    nc, cur, capex = res["financial_liabilities_noncurrent"], res["financial_liabilities_current"], res[
        "capital_expenditure"]
    assert isinstance(nc, xm.ExtensionMapping) and isinstance(cur, xm.ExtensionMapping)
    assert isinstance(capex, xm.ExtensionMapping)
    assert (nc.concept, nc.rule) == ("airbus:LongtermFinancingLiabilities", xm.RULE_ANCHOR)
    assert (cur.concept, cur.rule) == ("airbus:ShorttermFinancingLiabilities", xm.RULE_ANCHOR)
    assert _values(nc) == {"2025-12-31": Decimal("9063000000.0"), "2024-12-31": Decimal("10355000000.0")}
    assert _values(cur) == {"2025-12-31": Decimal("5186000000.0"), "2024-12-31": Decimal("3924000000.0")}
    assert "ifrs-full:LongtermBorrowings" in nc.evidence and "ifrs-full:NoncurrentLeaseLiabilities" in nc.evidence
    assert capex.concept == "airbus:PurchasesOfIntangibleAssetsPropertyPlantAndEquipmentInvestmentProperty"
    assert capex.sign == 1  # peso −1 en inversión, como el estándar
    assert _values(capex)["2025-12-31"] == Decimal("3964000000.0")
    # Las extensiones de ACTIVOS financieros anclados a NoncurrentFinancialAssets no son deuda.
    assert "Assets" not in nc.concept and "Securities" not in nc.concept


def test_taxonomia_desde_el_paquete_esef_zip():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        base = "MINO79WLOO247M1IL051-2025-12-31-1-en/www.airbus.com/MINO79WLOO247M1IL051-2025-12-31"
        zf.writestr(f"{base}_lab-en.xml", _read("airbus-2025_lab-en.xml"))
        zf.writestr(f"{base}_cal.xml", _read("airbus-2025_cal.xml"))
        zf.writestr(f"{base}_def.xml", _read("airbus-2025_def.xml"))
        zf.writestr("MINO79WLOO247M1IL051-2025-12-31-1-en/META-INF/catalog.xml", b"<catalog/>")
    tax = xm.taxonomy_from_package(buf.getvalue())
    assert tax.labels["airbus:LongtermFinancingLiabilities"] == "Longterm Financing Liabilities"
    assert tax.narrower["airbus:LongtermFinancingLiabilities"] == {
        "ifrs-full:LongtermBorrowings", "ifrs-full:NoncurrentLeaseLiabilities"}


def _fact(concept, val, end="2025-12-31", start="2025-01-01", unit="USD", members=()):
    return xm.ExtFact(concept=concept, value=Decimal(val), end=end, start=start, unit=unit, members=members)


def test_dos_candidatas_que_discrepan_es_ambigua_nd():
    tax = xm.ExtensionTaxonomy(labels={"x:FeeRelatedEarnings": "Fee-related earnings",
                                       "x:FeeRelatedEarningsAdjusted": "Fee Related Earnings, adjusted"})
    res = xm.resolve_extensions(tax, [_fact("x:FeeRelatedEarnings", "100"), _fact("x:FeeRelatedEarningsAdjusted", "90")],
                                metrics=["fee_related_earnings"])["fee_related_earnings"]
    assert isinstance(res, xm.NotAvailable) and res.motivo.startswith("ambigua:")


def test_consolidado_gana_al_segmento_y_se_ignoran_por_accion_y_no_monetarios():
    tax = xm.ExtensionTaxonomy(labels={"x:De": "Distributable earnings", "x:DePerShare": "Distributable earnings per share"})
    seg = (("us-gaap:StatementBusinessSegmentsAxis", "x:AMember"),)
    res = xm.resolve_extensions(tax, [
        _fact("x:De", "500"), _fact("x:De", "300", members=seg),
        _fact("x:DePerShare", "2.1", unit="USD/shares"),
    ], metrics=["distributable_earnings"])["distributable_earnings"]
    assert isinstance(res, xm.ExtensionMapping)
    assert (res.concept, res.segment, _values(res)) == ("x:De", None, {"2025-12-31": Decimal("500")})


def test_trimestres_y_conceptos_estandar_no_entran():
    tax = xm.ExtensionTaxonomy(labels={"x:Fre": "Fee related earnings",
                                       "us-gaap:FeeRelatedEarnings": "Fee related earnings"})
    res = xm.resolve_extensions(tax, [_fact("x:Fre", "10", start="2025-10-01"),
                                      _fact("us-gaap:FeeRelatedEarnings", "40")],
                                metrics=["fee_related_earnings"])["fee_related_earnings"]
    assert isinstance(res, xm.NotAvailable)


def test_capex_por_etiqueta_sin_calculo_no_basta():
    # Sin relación de cálculo con los flujos de inversión, una etiqueta de
    # «property, plant» no prueba que sea capex (podría ser una nota).
    tax = xm.ExtensionTaxonomy(labels={"x:PurchasesOfPropertyPlant": "Purchases of property, plant and equipment"})
    res = xm.resolve_extensions(tax, [_fact("x:PurchasesOfPropertyPlant", "7")],
                                metrics=["capital_expenditure"])["capital_expenditure"]
    assert isinstance(res, xm.NotAvailable)


def test_concepto_desde_href():
    assert xm.concept_from_href("kkr-20251231.xsd#kkr_FeeRelatedIncomeLoss") == "kkr:FeeRelatedIncomeLoss"
    assert xm.concept_from_href("https://xbrl.ifrs.org/x.xsd#ifrs-full_Assets") == "ifrs-full:Assets"
    assert xm.concept_from_href("sin-fragmento.xsd") is None


# ---------------------------------------------------------------- ESEF (esef_live + ingesta)


class _FakeEsef:
    def __init__(self, package: bytes | None):
        self.package = package
        self.calls = 0

    async def fetch_package(self, filing):
        self.calls += 1
        if self.package is None:
            raise RuntimeError("404")
        return self.package


def _airbus_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name in ("lab-en", "cal", "def"):
            zf.writestr(f"p/www.airbus.com/x_{name}.xml", _read(f"airbus-2025_{name}.xml"))
    return buf.getvalue()


_FILING = SimpleNamespace(package_url="/MINO79WLOO247M1IL051/2025-12-31/ESEF/NL/0/x.zip")


def test_esef_live_mapa_de_extensiones_con_fuente():
    facts, _tax = _airbus()
    fake = _FakeEsef(_airbus_zip())
    out = asyncio.run(esef_live._extension_map(fake, [("2025-12-31", 0, _FILING)], facts))
    assert out["financial_liabilities_noncurrent"]["concept"] == "airbus:LongtermFinancingLiabilities"
    assert out["financial_liabilities_noncurrent"]["includes_leases"] is True
    assert out["capital_expenditure"]["rule"] == "ancla_esef"
    assert out["capital_expenditure"]["source"].endswith("/x.zip")
    assert "values" not in out["capital_expenditure"]  # los hechos ya están en el snapshot


def test_esef_live_arrendamientos_declarados_aparte_no_se_cuentan_dos_veces():
    facts, _tax = _airbus()
    facts = copy.deepcopy(facts)
    facts["ifrs-full:NoncurrentLeaseLiabilities"] = {"iso4217:EUR": [
        {"instant": "2025-12-31", "end": "2025-12-31", "val": "1000000000", "dims": []}]}
    out = asyncio.run(esef_live._extension_map(_FakeEsef(_airbus_zip()), [("2025-12-31", 0, _FILING)], facts))
    assert out["financial_liabilities_noncurrent"]["status"] == "N/D"
    assert "se contarían dos veces" in out["financial_liabilities_noncurrent"]["motivo"]
    assert out["financial_liabilities_current"]["concept"] == "airbus:ShorttermFinancingLiabilities"


def test_esef_live_sin_paquete_es_nd_y_con_estandar_no_hay_red():
    facts, _tax = _airbus()
    out = asyncio.run(esef_live._extension_map(_FakeEsef(None), [("2025-12-31", 0, _FILING)], facts))
    assert {row["status"] for row in out.values()} == {"N/D"}
    assert all("no legible" in row["motivo"] for row in out.values())
    full = {
        "ifrs-full:PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities": {"iso4217:EUR": [{"dims": []}]},
        "ifrs-full:NoncurrentFinancialLiabilities": {"iso4217:EUR": [{"dims": []}]},
        "ifrs-full:CurrentFinancialLiabilities": {"iso4217:EUR": [{"dims": []}]},
    }
    fake = _FakeEsef(_airbus_zip())
    assert asyncio.run(esef_live._extension_map(fake, [("2025-12-31", 0, _FILING)], full)) == {}
    assert fake.calls == 0


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _company(db, ticker, name, **kw):
    fields = {"exchange": "NYSE", "currency": "USD", "sector": "Industrials", "industry": "Unknown",
              "company_type": "research_candidate", "valuation_model": "unassigned",
              "special_sources": [], "special_risks": [], "factor_tags": [], **kw}
    company = Company(ticker=ticker, name=name, **fields)
    db.add(company)
    db.commit()
    return company


def _facts(db, company, metric):
    return {f.fiscal_year: f for f in db.scalars(select(FinancialFact).where(
        FinancialFact.company_id == company.id, FinancialFact.metric == metric)) if f.fiscal_quarter == "FY"}


def test_ingesta_esef_usa_la_deuda_y_el_capex_anclados(db, monkeypatch):
    facts, _tax = _airbus()
    extension_map = asyncio.run(esef_live._extension_map(_FakeEsef(_airbus_zip()), [("2025-12-31", 0, _FILING)], facts))
    snapshot = {"lei": "MINO79WLOO247M1IL051", "ticker": "AIR.PA", "entity_name": "Airbus SE",
                "period_end": "2025-12-31", "periods": ["2025-12-31"], "fxo_id": "x", "sha256": "y",
                "fetched_at": "2026-11-09T00:00:00+00:00", "facts": facts, "extension_map": extension_map}
    monkeypatch.setattr(ingestion.esef_connector, "read_esef_snapshot", lambda ticker: copy.deepcopy(snapshot))
    company = _company(db, "AIR.PA", "Airbus SE", exchange="EPA", currency="EUR")
    asyncio.run(FinancialIngestionService().refresh_from_esef(db, company))
    debt = _facts(db, company, "total_debt")
    assert float(debt[2025].value) == pytest.approx(9_063_000_000 + 5_186_000_000)
    assert float(debt[2024].value) == pytest.approx(10_355_000_000 + 3_924_000_000)
    capex = _facts(db, company, "capital_expenditure")
    assert float(capex[2025].value) == pytest.approx(-3_964_000_000)  # salida de caja, signo interno
    doc = db.scalars(select(Document).where(Document.company_id == company.id)).first()
    assert doc.metadata_["extension_map"]["financial_liabilities_noncurrent"]["rule"] == "ancla_esef"


def test_esef_signo_contrario_se_orienta_sin_tocar_el_crudo():
    facts = {"x:Capex": {"iso4217:EUR": [{"start": "2025-01-01", "end": "2025-12-31", "val": "-5", "dims": []}]}}
    snap = {"extension_map": {"capital_expenditure": {"concept": "x:Capex", "sign": -1}}, "facts": facts}
    view = copy.deepcopy(facts)
    assert ingestion.esef_extension_concepts(snap, view) == {"capital_expenditure": "x:Capex"}
    assert view["x:Capex"]["iso4217:EUR"][0]["val"] == "5"
    assert facts["x:Capex"]["iso4217:EUR"][0]["val"] == "-5"


# ---------------------------------------------------------------- SEC (plan C + ingesta)

CNQ_ACCN, KKR_ACCN = "0001017413-26-000018", "0001404912-26-000007"


def _flow(val, year, accn, filed, form):
    return {"fy": 2025, "fp": "FY", "form": form, "start": f"{year}-01-01", "end": f"{year}-12-31",
            "val": val, "filed": filed, "accn": accn}


def _fake_sec(stem, accn, form, cik, taxonomy, base_facts):
    class _Fake:
        fetched: list[str] = []

        async def cik_for_ticker(self, ticker):
            return cik

        async def annual_report_anchors(self, cik_):
            return {accn: "2025-12-31"}

        async def index_accessions(self, cik_):
            return {accn}

        async def submissions(self, cik_):
            return {"filings": {"recent": {"form": [form], "accessionNumber": [accn], "filingDate": ["2026-03-01"],
                                           "reportDate": ["2025-12-31"], "primaryDocument": [f"{stem}.htm"],
                                           "isXBRL": [1]}}}

        async def company_facts(self, cik_):
            return {"cik": int(cik), "entityName": stem, "facts": {taxonomy: copy.deepcopy(base_facts)}}

        async def filing_document(self, url):
            _Fake.fetched.append(url)
            name = url.rsplit("/", 1)[-1]
            return _read(name), "application/xml"

    return _Fake


def test_ingesta_sec_cnq_capex_propio_entra_con_su_concepto(db, monkeypatch):
    base = {"CashFlowsFromUsedInOperatingActivities": {"units": {"CAD": [
        _flow(15_000_000_000, 2025, CNQ_ACCN, "2026-03-26", "40-F")]}},
        "CashFlowsFromUsedInInvestingActivities": {"units": {"CAD": [
            _flow(-6_500_000_000, 2025, CNQ_ACCN, "2026-03-26", "40-F")]}},
        "Assets": {"units": {"CAD": [{**_flow(80_000_000_000, 2025, CNQ_ACCN, "2026-03-26", "40-F"), "start": None}]}}}
    fake = _fake_sec("cnq-20251231", CNQ_ACCN, "40-F", "0001017413", "ifrs-full", base)
    monkeypatch.setattr(ingestion, "SECClient", fake)
    company = _company(db, "CNQ", "Canadian Natural Resources Ltd", currency="CAD", sector="Energy",
                       industry="Oil & Gas E&P")
    asyncio.run(FinancialIngestionService().refresh_from_sec(db=db, company=company))
    capex = _facts(db, company, "capital_expenditure")
    assert float(capex[2025].value) == pytest.approx(-6_676_000_000)
    assert float(capex[2024].value) == pytest.approx(-5_291_000_000)
    assert _facts(db, company, "fee_related_earnings") == {}  # no es gestora: ni se busca
    doc = db.scalars(select(Document).where(Document.company_id == company.id)).first()
    meta = doc.metadata_["sec_extension_map"]
    assert meta["filing"]["accn"] == CNQ_ACCN
    assert meta["metrics"]["capital_expenditure"]["rule"] == "calculo+etiqueta"
    used = doc.metadata_["xbrl_concept_by_metric_period"]
    assert any("cnq:CashFlowsFromUsedInPropertyPlantandEquipment" in json.dumps(v) for k, v in used.items()
               if k.startswith("capital_expenditure"))

    # Segundo refresh del mismo accession: la resolución se reutiliza sin red.
    fake.fetched.clear()
    monkeypatch.setattr(ingestion, "SEC_INGESTION_RULES_VERSION", 999)
    asyncio.run(FinancialIngestionService().refresh_from_sec(db=db, company=company))
    assert not any(u.endswith(("_lab.xml", "_cal.xml")) for u in fake.fetched)
    assert float(_facts(db, company, "capital_expenditure")[2025].value) == pytest.approx(-6_676_000_000)


def test_ingesta_sec_kkr_fre_de_la_gestora(db, monkeypatch):
    base = {"Revenues": {"units": {"USD": [_flow(19_000_000_000, 2025, KKR_ACCN, "2026-02-27", "10-K")]}},
            "Assets": {"units": {"USD": [{**_flow(400_000_000_000, 2025, KKR_ACCN, "2026-02-27", "10-K"), "start": None}]}},
            "PaymentsToAcquirePropertyPlantAndEquipment": {"units": {"USD": [
                _flow(100_000_000, 2025, KKR_ACCN, "2026-02-27", "10-K")]}}}
    fake = _fake_sec("kkr-20251231", KKR_ACCN, "10-K", "0001404912", "us-gaap", base)
    monkeypatch.setattr(ingestion, "SECClient", fake)
    company = _company(db, "KKR", "KKR & Co. Inc.", sector="Financial Services", industry="Asset Management")
    asyncio.run(FinancialIngestionService().refresh_from_sec(db=db, company=company))
    fre = _facts(db, company, "fee_related_earnings")
    assert float(fre[2025].value) == pytest.approx(3_714_313_000)
    assert float(fre[2024].value) == pytest.approx(3_267_796_000)
    doc = db.scalars(select(Document).where(Document.company_id == company.id)).first()
    metrics = doc.metadata_["sec_extension_map"]["metrics"]
    assert metrics["fee_related_earnings"]["segment"] == "kkr:AssetManagementSegmentMember"
    assert metrics["distributable_earnings"]["status"] == "N/D"
    assert "capital_expenditure" not in metrics  # el capex estándar existe: no se busca


def test_sec_sin_metricas_objetivo_no_descarga_nada():
    company = SimpleNamespace(industry="Software", sector="Technology", company_type="research_candidate",
                              valuation_model="", factor_tags=[])
    fy = {"units": {"USD": [{"fp": "FY", "end": "2025-12-31"}]}}
    with_capex = {"PaymentsToAcquirePropertyPlantAndEquipment": fy, "NetCashProvidedByUsedInInvestingActivities": fy}
    assert sec_extension_facts.wanted_metrics(company, with_capex, ingestion.SEC_METRIC_MAP, "2025-12-31") == []
    # Sin estado de flujos etiquetado no hay capex propio que buscar (ni red).
    assert sec_extension_facts.wanted_metrics(company, {}, ingestion.SEC_METRIC_MAP, "2025-12-31") == []
    only_total = {"NetCashProvidedByUsedInInvestingActivities": fy}
    assert sec_extension_facts.wanted_metrics(company, only_total, ingestion.SEC_METRIC_MAP, "2025-12-31") == [
        "capital_expenditure"]


def test_apply_resolution_deja_el_estandar_delante():
    prov = {"filing": {"accn": "a", "form": "10-K", "filed": "2026-01-01", "report": "2025-12-31"},
            "metrics": {"capital_expenditure": {"concept": "x:Capex", "unit": "USD",
                                                "values": [{"start": "2025-01-01", "end": "2025-12-31", "val": "7"}]},
                        "distributable_earnings": {"metric": "distributable_earnings", "status": "N/D", "motivo": "m"}}}
    data = {"facts": {"us-gaap": {}}}
    out = sec_extension_facts.apply_resolution(data, "us-gaap", [("capital_expenditure", ["Std"], "USD")], prov)
    assert out == [("capital_expenditure", ["Std", "x:Capex"], "USD")]
    assert data["facts"]["us-gaap"]["x:Capex"]["units"]["USD"][0]["val"] == 7
