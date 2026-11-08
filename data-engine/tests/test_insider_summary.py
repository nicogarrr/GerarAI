"""insiders-1: Form 4/5 con acciones tras la operacion, retraso de presentacion
y agregados deterministas (compra neta 3/6/12 meses, compras en grupo, % de lo
que tenia, primera compra en N anos). Fixture real grabado de EDGAR (META,
0000950103-26-016314) mas Form 4 sinteticos con la misma estructura."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.database import SessionLocal, init_db
from app.models.entities import InsiderFiling, InsiderTransaction
from app.services import insider_persistence, insider_summary
from app.services.connectors import form4 as form4_connector

FIXTURES = Path(__file__).parent / "fixtures" / "form4"
META_XML = (FIXTURES / "meta_0000950103-26-016314.xml").read_text()


def _xml(*, owner_cik: str, name: str, code: str, ad: str, shares: float, price: float,
         day: str, after: float | None, form: str = "4", derivative: bool = False) -> str:
    post = (
        f"<postTransactionAmounts><sharesOwnedFollowingTransaction><value>{after}</value>"
        "</sharesOwnedFollowingTransaction></postTransactionAmounts>"
        if after is not None else ""
    )
    tx = (
        f"<securityTitle><value>Common Stock</value></securityTitle>"
        f"<transactionDate><value>{day}</value></transactionDate>"
        f"<transactionCoding><transactionCode>{code}</transactionCode></transactionCoding>"
        f"<transactionAmounts><transactionShares><value>{shares}</value></transactionShares>"
        f"<transactionPricePerShare><value>{price}</value></transactionPricePerShare>"
        f"<transactionAcquiredDisposedCode><value>{ad}</value></transactionAcquiredDisposedCode>"
        f"</transactionAmounts>{post}"
        "<ownershipNature><directOrIndirectOwnership><value>D</value></directOrIndirectOwnership></ownershipNature>"
    )
    table = (
        f"<derivativeTable><derivativeTransaction>{tx}</derivativeTransaction></derivativeTable>"
        if derivative else
        f"<nonDerivativeTable><nonDerivativeTransaction>{tx}</nonDerivativeTransaction></nonDerivativeTable>"
    )
    return (
        f"<ownershipDocument><documentType>{form}</documentType>"
        f"<periodOfReport><value>{day}</value></periodOfReport>"
        "<issuer><issuerCik>0009999999</issuerCik><issuerName>Test Corp</issuerName>"
        "<issuerTradingSymbol>TSTX</issuerTradingSymbol></issuer>"
        f"<reportingOwner><reportingOwnerId><rptOwnerCik>{owner_cik}</rptOwnerCik>"
        f"<rptOwnerName>{name}</rptOwnerName></reportingOwnerId>"
        "<reportingOwnerRelationship><isDirector>1</isDirector></reportingOwnerRelationship>"
        f"</reportingOwner>{table}</ownershipDocument>"
    )


def _filing(acc: str, filed: str, form: str = "4") -> dict:
    return {
        "form": form,
        "accession_number": acc,
        "filing_date": filed,
        "document_url": f"https://www.sec.gov/Archives/edgar/data/9999999/{acc.replace('-', '')}/f.xml",
        "index_url": f"https://www.sec.gov/Archives/edgar/data/9999999/{acc.replace('-', '')}/",
    }


def _db():
    init_db()
    db = SessionLocal()
    db.query(InsiderTransaction).delete()
    db.query(InsiderFiling).delete()
    db.commit()
    return db


def _store(db, acc: str, filed: str, xml: str, form: str = "4") -> dict:
    return insider_persistence.persist_filing(db, _filing(acc, filed, form), form4_connector.parse_form4_xml(xml), xml_text=xml)


# --- conector -------------------------------------------------------------

def test_parse_reads_holdings_after_and_ownership_from_recorded_filing():
    parsed = form4_connector.parse_form4_xml(META_XML)
    (tx,) = parsed["transactions"]
    assert tx["type"] == "S" and tx["shares"] == 390.0 and tx["price"] == 640.0
    assert tx["rule_10b5_1"] is True
    assert tx["shares_owned_after"] == 2450.0
    assert tx["direct_indirect"] == "I"


def test_form5_is_part_of_the_listed_family():
    assert {"4", "4/A", "5", "5/A"} <= form4_connector.FORM4_FAMILY


def test_persistence_keeps_holdings_after_and_enriches_old_rows():
    db = _db()
    try:
        parsed = form4_connector.parse_form4_xml(META_XML)
        filing = {**_filing("0000950103-26-016314", "2026-10-28"), "form": "4"}
        # Fila guardada por un parser anterior: sin acciones tras la operacion.
        old = {**parsed, "transactions": [{k: v for k, v in t.items() if k not in ("shares_owned_after", "direct_indirect")} for t in parsed["transactions"]]}
        insider_persistence.persist_filing(db, filing, old, xml_text=META_XML)
        row = db.query(InsiderTransaction).one()
        assert "holdings_after" not in (row.data_quality or {})
        stats = insider_persistence.persist_filing(db, filing, parsed, xml_text=META_XML)
        assert stats["transactions_created"] == 0 and stats["transactions_enriched"] == 1
        db.refresh(row)
        assert row.data_quality["holdings_after"] == 2450.0
        assert row.data_quality["ownership"] == "I"
    finally:
        db.close()


# --- calendario -----------------------------------------------------------

def test_business_days_skip_weekends_and_us_holidays():
    # Jueves 26-nov-2026 es Thanksgiving: del miercoles 25 al lunes 30 hay 2 habiles (27 y 30).
    assert insider_summary.business_days_between(date(2026, 11, 25), date(2026, 11, 30)) == 2
    assert date(2026, 11, 26) in insider_summary.us_federal_holidays(2026)
    assert date(2026, 6, 19) in insider_summary.us_federal_holidays(2026)  # Juneteenth (viernes)
    assert insider_summary.business_days_between(date(2026, 10, 26), date(2026, 10, 28)) == 2


# --- resumen --------------------------------------------------------------

def test_summary_net_buying_excludes_exercises_awards_tax_and_gifts():
    db = _db()
    try:
        _store(db, "0000000001-26-000001", "2026-09-03", _xml(owner_cik="1", name="ANA", code="P", ad="A", shares=1000, price=10, day="2026-09-01", after=5000))
        _store(db, "0000000001-26-000002", "2026-09-03", _xml(owner_cik="2", name="BEA", code="S", ad="D", shares=200, price=10, day="2026-09-01", after=800))
        _store(db, "0000000001-26-000003", "2026-09-03", _xml(owner_cik="3", name="CAR", code="M", ad="A", shares=9000, price=1, day="2026-09-01", after=9000, derivative=True))
        _store(db, "0000000001-26-000004", "2026-09-03", _xml(owner_cik="3", name="CAR", code="F", ad="D", shares=3000, price=10, day="2026-09-01", after=6000))
        _store(db, "0000000001-26-000005", "2026-09-03", _xml(owner_cik="4", name="DAN", code="A", ad="A", shares=500, price=0, day="2026-09-01", after=500))
        _store(db, "0000000001-26-000006", "2026-09-03", _xml(owner_cik="4", name="DAN", code="G", ad="D", shares=100, price=0, day="2026-09-01", after=400))
        out = insider_summary.insider_summary(db, "tstx", as_of=date(2026, 11, 8))
        assert out["status"] == "ok"
        w90 = next(w for w in out["windows"] if w["days"] == 90)
        assert w90["buys"]["value"] == 10000.0 and w90["sells"]["value"] == 2000.0
        assert w90["net_value"] == 8000.0
        assert w90["excluded"] == {"ejercicio": 1, "retencion_fiscal": 1, "concesion": 1, "regalo": 1}
        buy = next(t for t in out["transactions"] if t["nature"] == "compra_mercado")
        # Tenia 4.000 antes de comprar 1.000: la compra es un 25 % de lo que tenia.
        assert buy["pct_of_holdings"] == 25.0
        assert buy["source_url"].startswith("https://www.sec.gov/Archives/")
    finally:
        db.close()


def test_summary_flags_late_form4_but_not_form5():
    db = _db()
    try:
        # Operacion el viernes 2-oct, filing el miercoles 7-oct: 3 habiles -> tarde (1 dia).
        _store(db, "0000000002-26-000001", "2026-10-07", _xml(owner_cik="1", name="ANA", code="S", ad="D", shares=10, price=10, day="2026-10-02", after=90))
        # A tiempo: lunes 5-oct.
        _store(db, "0000000002-26-000002", "2026-10-05", _xml(owner_cik="2", name="BEA", code="S", ad="D", shares=10, price=10, day="2026-10-01", after=90))
        # Form 5 de un regalo de febrero: por definicion anual, no se mide retraso.
        _store(db, "0000000002-26-000003", "2026-10-06", _xml(owner_cik="3", name="CAR", code="G", ad="D", shares=10, price=0, day="2026-02-01", after=90, form="5"), form="5")
        out = insider_summary.insider_summary(db, "TSTX", as_of=date(2026, 11, 8))
        late = {t["accession_number"]: (t["late"], t["days_late"]) for t in out["transactions"]}
        assert late["0000000002-26-000001"] == (True, 1)
        assert late["0000000002-26-000002"] == (False, 0)
        assert late["0000000002-26-000003"] == (None, None)
        assert out["late"] == {"filings": 2, "late": 1}
    finally:
        db.close()


def test_summary_cluster_buys_need_three_insiders_within_30_days():
    db = _db()
    try:
        for i, (name, day) in enumerate([("ANA", "2026-06-01"), ("BEA", "2026-06-15"), ("CAR", "2026-06-29"), ("DAN", "2026-08-30")]):
            _store(db, f"0000000003-26-00000{i}", day, _xml(owner_cik=str(i + 1), name=name, code="P", ad="A", shares=100, price=10, day=day, after=1000))
        out = insider_summary.insider_summary(db, "TSTX", as_of=date(2026, 11, 8))
        assert len(out["clusters"]) == 1
        cluster = out["clusters"][0]
        assert (cluster["start"], cluster["end"], cluster["insiders"]) == ("2026-06-01", "2026-06-29", 3)
        assert cluster["names"] == ["ANA", "BEA", "CAR"]
    finally:
        db.close()


def test_summary_first_buy_in_years_and_amendment_not_double_counted():
    db = _db()
    try:
        _store(db, "0000000004-23-000001", "2023-01-05", _xml(owner_cik="1", name="ANA", code="P", ad="A", shares=100, price=10, day="2023-01-03", after=100))
        _store(db, "0000000004-26-000001", "2026-09-03", _xml(owner_cik="1", name="ANA", code="P", ad="A", shares=100, price=10, day="2026-09-01", after=200))
        # La enmienda repite la misma fila: no es otra compra.
        _store(db, "0000000004-26-000002", "2026-09-10", _xml(owner_cik="1", name="ANA", code="P", ad="A", shares=100, price=10, day="2026-09-01", after=200, form="4/A"), form="4/A")
        out = insider_summary.insider_summary(db, "TSTX", as_of=date(2026, 11, 8))
        w365 = next(w for w in out["windows"] if w["days"] == 365)
        assert w365["buys"]["trades"] == 1
        recent = [f for f in out["first_buys"] if f["tx_date"] == "2026-09-01"]
        assert recent and recent[0]["kind"] == "desde_compra_previa"
        assert recent[0]["years"] == 3.7 and recent[0]["previous_buy"] == "2023-01-03"
    finally:
        db.close()


def test_summary_without_rows_says_so():
    db = _db()
    try:
        out = insider_summary.insider_summary(db, "NOPE", as_of=date(2026, 11, 8))
        assert out["status"] == "sin_datos" and out["transactions"] == []
    finally:
        db.close()


def test_summary_route_is_deterministic():
    from fastapi import FastAPI

    from app.api.routes import insider as insider_module
    from app.core.database import get_db

    db = _db()
    _store(db, "0000950103-26-016314", "2026-10-28", META_XML)
    app = FastAPI()
    app.include_router(insider_module.router, prefix="/api/insider")

    def _override_db():
        yield db

    app.dependency_overrides[get_db] = _override_db
    with TestClient(app) as http:
        first = http.get("/api/insider/summary", params={"ticker": "META"})
        second = http.get("/api/insider/summary", params={"ticker": "META"})
    db.close()
    assert first.status_code == 200
    body = first.json()
    assert body == second.json()
    (row,) = body["transactions"]
    assert row["nature"] == "venta_mercado" and row["rule_10b5_1"] is True
    assert row["holdings_after"] == 2450.0 and row["late"] is False


def test_role_names_other_relationship_instead_of_generic_insider():
    xml = _xml(owner_cik="9", name="TOWER CO", code="S", ad="D", shares=10, price=10, day="2026-01-02", after=5).replace(
        "<reportingOwnerRelationship><isDirector>1</isDirector></reportingOwnerRelationship>",
        "<reportingOwnerRelationship><isDirector>0</isDirector><isOther>1</isOther>"
        "<otherText>Member of 13(d) group</otherText></reportingOwnerRelationship>",
    )
    (tx,) = form4_connector.parse_form4_xml(xml)["transactions"]
    assert tx["role"] == "other (Member of 13(d) group)"
