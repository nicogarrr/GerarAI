"""S2: per-manager 13F ingestion tests (no network; injectable httpx client)."""

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models.entities import Base, FundManager, ManagerHolding
from app.services.connectors import form13f
from app.services.manager_holding_ingestion_service import (
    REVIEWED_MANAGERS,
    ManagerHoldingIngestionService,
)

CIK = "0001067983"

SUBMISSIONS = {
    "filings": {
        "recent": {
            "accessionNumber": ["0000950123-26-000001", "0000950123-26-000002", "0000950123-25-000999"],
            "form": ["13F-HR", "13F-HR/A", "10-K"],
            "reportDate": ["2026-06-30", "2026-06-30", "2025-12-31"],
            "filingDate": ["2026-08-14", "2026-08-20", "2026-02-01"],
            "primaryDocument": ["primary_doc.xml", "primary_doc.xml", "k.htm"],
        }
    }
}

INDEX = {"directory": {"item": [{"name": "primary_doc.xml"}, {"name": "form13fInfoTable.xml"}, {"name": "readme.htm"}]}}

INFO_TABLE = """<?xml version="1.0"?>
<informationTable xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable">
  <infoTable>
    <nameOfIssuer>APPLE INC</nameOfIssuer>
    <titleOfClass>COM</titleOfClass>
    <cusip>037833100</cusip>
    <value>75000000</value>
    <shrsOrPrnAmt>
      <sshPrnamt>300000000</sshPrnamt>
      <sshPrnamtType>SH</sshPrnamtType>
    </shrsOrPrnAmt>
    <investmentDiscretion>SOLE</investmentDiscretion>
    <votingAuthority>
      <Sole>300000000</Sole>
      <Shared>0</Shared>
      <None>0</None>
    </votingAuthority>
  </infoTable>
  <infoTable>
    <nameOfIssuer>BANK OF AMERICA CORP</nameOfIssuer>
    <titleOfClass>COM</titleOfClass>
    <cusip>060505104</cusip>
    <value>40000000</value>
    <shrsOrPrnAmt>
      <sshPrnamt>1000000000</sshPrnamt>
      <sshPrnamtType>SH</sshPrnamtType>
    </shrsOrPrnAmt>
    <investmentDiscretion>SOLE</investmentDiscretion>
    <votingAuthority>
      <Sole>1000000000</Sole>
      <Shared>0</Shared>
      <None>0</None>
    </votingAuthority>
  </infoTable>
</informationTable>
"""


# Resumen minimo de una enmienda completa (sin totales): la enmienda se ingiere, sin verificar.
RESTATEMENT_DOC = (
    '<edgarSubmission xmlns="http://www.sec.gov/edgar/thirteenffiler"><formData>'
    "<amendmentInfo><amendmentType>RESTATEMENT</amendmentType></amendmentInfo>"
    "</formData></edgarSubmission>"
)


def _sec_client(fail: bool = False) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        if fail:
            return httpx.Response(503, text="down")
        url = str(request.url)
        if url.startswith("https://data.sec.gov/submissions/"):
            return httpx.Response(200, json=SUBMISSIONS)
        if url.endswith("index.json"):
            return httpx.Response(200, json=INDEX)
        if url.endswith("form13fInfoTable.xml"):
            return httpx.Response(200, text=INFO_TABLE)
        if url.endswith("primary_doc.xml"):
            return httpx.Response(200, text=RESTATEMENT_DOC)
        return httpx.Response(404, text="not found")

    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def test_parse_information_table_rows():
    rows = form13f.parse_information_table(INFO_TABLE)
    assert len(rows) == 2
    apple = rows[0]
    assert apple["name_of_issuer"] == "APPLE INC"
    assert apple["cusip"] == "037833100"
    assert apple["value_usd_thousands"] == "75000000"
    assert apple["ssh_prnamt"] == "300000000"
    assert apple["voting_sole"] == "300000000"


def test_recent_filings_filters_forms():
    filings = form13f.recent_13f_filings(CIK, client=_sec_client())
    assert [f["form"] for f in filings] == ["13F-HR", "13F-HR/A"]
    assert filings[1]["is_amendment"] is True


def test_information_table_url_skips_primary_document():
    url = form13f.information_table_url(
        CIK, "0000950123-26-000001", "primary_doc.xml", client=_sec_client()
    )
    assert url is not None and url.endswith("form13fInfoTable.xml")


def test_sync_ingests_latest_report_and_is_idempotent(db):
    service = ManagerHoldingIngestionService(client=_sec_client())
    result = service.sync_manager(db, cik=CIK)
    assert result["status"] == "ok"
    assert result["report_date"] == "2026-06-30"
    assert result["ingested_rows"] == 4  # 2 rows x (base + amendment, immutable each)
    assert result["provenance"]["source_kind"] == "official"

    manager = db.scalar(select(FundManager).where(FundManager.cik == CIK))
    assert manager.name == REVIEWED_MANAGERS[CIK]
    # El resumen de este fixture no trae totales: sin contraste no es "ok".
    assert manager.coverage == "unverified"
    assert result["verification_status"] == "unverified"
    rows = db.scalars(select(ManagerHolding)).all()
    assert len(rows) == 4
    accessions = {row.accession_number for row in rows}
    assert accessions == {"0000950123-26-000001", "0000950123-26-000002"}
    assert all(row.cusip and row.filing_url for row in rows)
    assert rows[0].name_of_issuer  # as filed, no ticker inference

    again = service.sync_manager(db, cik=CIK)
    assert again["ingested_rows"] == 0  # idempotent re-sync
    assert len(db.scalars(select(ManagerHolding)).all()) == 4


def test_sync_refuses_unreviewed_manager(db):
    result = ManagerHoldingIngestionService(client=_sec_client()).sync_manager(db, cik="0000000001")
    assert result["status"] == "unreviewed_manager"
    assert db.scalar(select(FundManager)) is None


def test_sync_marks_unavailable_on_http_error(db):
    result = ManagerHoldingIngestionService(client=_sec_client(fail=True)).sync_manager(db, cik=CIK)
    assert result["status"] == "unavailable"
    assert result["provenance"]["coverage"] == "unavailable"
    manager = db.scalar(select(FundManager).where(FundManager.cik == CIK))
    assert manager.coverage == "unavailable"


def test_latest_holdings_resolves_issuer_name_by_cusip(db):
    """La pestana 13F muestra el nombre completo de la referencia por CUSIP
    (el de la SEC viene truncado) y conserva el del filing."""
    from datetime import date

    from app.models.entities import InstrumentReference

    service = ManagerHoldingIngestionService(client=_sec_client())
    service.sync_manager(db, cik=CIK)
    db.add(
        InstrumentReference(
            ticker_normalized="AAPL",
            name="Apple Inc.",
            cusip="037833100",
            as_of=date(2026, 10, 1),
            source="financedatabase",
        )
    )
    db.commit()
    result = service.latest_holdings(db, cik=CIK)
    by_cusip = {h["cusip"]: h for h in result["holdings"]}
    assert by_cusip["037833100"]["name_of_issuer"] == "Apple Inc."
    assert by_cusip["037833100"]["name_of_issuer_filed"] == "APPLE INC"
    assert by_cusip["060505104"]["name_of_issuer"] == "BANK OF AMERICA CORP"


def test_latest_holdings_serves_latest_report(db):
    service = ManagerHoldingIngestionService(client=_sec_client())
    assert service.latest_holdings(db, cik=CIK)["status"] == "unavailable"
    service.sync_manager(db, cik=CIK)
    result = service.latest_holdings(db, cik=CIK)
    # Fixture sin totales en el resumen: se sirve, pero sin verificar.
    assert result["status"] == "unverified"
    assert result["coverage"] == "partial"
    assert result["report_date"] == "2026-06-30"
    # La enmienda (filing mas reciente) sustituye al base: 2 posiciones, no 4.
    assert len(result["holdings"]) == 2
    assert result["holdings"][0]["value_usd_thousands"] == 75000000.0
    assert all(h["is_amendment"] for h in result["holdings"])
    assert result["limitations"]


# --- Quarter-over-quarter changes (two report periods) ---

SUBMISSIONS_TWO = {
    "filings": {
        "recent": {
            "accessionNumber": [
                "0000950123-26-000001",
                "0000950123-26-000002",
                "0000950123-26-000003",
            ],
            "form": ["13F-HR", "13F-HR/A", "13F-HR"],
            "reportDate": ["2026-06-30", "2026-06-30", "2026-03-31"],
            "filingDate": ["2026-08-14", "2026-08-20", "2026-05-15"],
            "primaryDocument": ["primary_doc.xml", "primary_doc.xml", "primary_doc.xml"],
        }
    }
}


def _table(rows: list[tuple[str, str, str, str]]) -> str:
    body = "".join(
        f"""<infoTable><nameOfIssuer>{name}</nameOfIssuer><titleOfClass>COM</titleOfClass>
        <cusip>{cusip}</cusip><value>{value}</value>
        <shrsOrPrnAmt><sshPrnamt>{shares}</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt>
        <investmentDiscretion>SOLE</investmentDiscretion>
        <votingAuthority><Sole>{shares}</Sole><Shared>0</Shared><None>0</None></votingAuthority>
        </infoTable>"""
        for name, cusip, value, shares in rows
    )
    return (
        '<?xml version="1.0"?>\n<informationTable '
        'xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable">'
        f"{body}</informationTable>"
    )


# Acciones realistas (precio implicito 40-250 USD): la escala del valor se infiere de value/shares.
# latest period base (acc1): AAPL up, BAC flat, GOOG new
TABLE_ACC1 = _table([
    ("APPLE INC", "037833100", "75000000", "300000"),
    ("BANK OF AMERICA CORP", "060505104", "40000000", "1000000"),
    ("ALPHABET INC", "02079K305", "9000000", "50000"),
])
# latest period amendment (acc2, filed later): supersedes acc1, AAPL value restated
TABLE_ACC2 = _table([
    ("APPLE INC", "037833100", "75000001", "300000"),
    ("BANK OF AMERICA CORP", "060505104", "40000000", "1000000"),
    ("ALPHABET INC", "02079K305", "9000000", "50000"),
])
# previous period (acc3): AAPL smaller, BAC flat, MSFT closed since
TABLE_ACC3 = _table([
    ("APPLE INC", "037833100", "60000000", "250000"),
    ("BANK OF AMERICA CORP", "060505104", "40000000", "1000000"),
    ("MICROSOFT CORP", "594918104", "10000", "100"),
])

TABLES = {
    "000095012326000001": TABLE_ACC1,
    "000095012326000002": TABLE_ACC2,
    "000095012326000003": TABLE_ACC3,
}


def _sec_client_two() -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.startswith("https://data.sec.gov/submissions/"):
            return httpx.Response(200, json=SUBMISSIONS_TWO)
        if url.endswith("index.json"):
            return httpx.Response(200, json=INDEX)
        for key, table in TABLES.items():
            if key in url and url.endswith("form13fInfoTable.xml"):
                return httpx.Response(200, text=table)
        if url.endswith("primary_doc.xml"):
            return httpx.Response(200, text=RESTATEMENT_DOC)
        return httpx.Response(404, text="not found")

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_latest_holdings_serves_only_the_winning_amendment(db):
    """Regresion lista 11.2: con 13F-HR + 13F-HR/A del mismo periodo,
    latest_holdings duplicaba cada posicion (base + enmienda)."""
    service = ManagerHoldingIngestionService(client=_sec_client_two())
    service.sync_manager(db, cik=CIK)
    result = service.latest_holdings(db, cik=CIK)
    assert result["status"] == "unverified"  # resumen del fixture sin totales
    keys = [(h["cusip"], h["title_of_class"], h["put_call"]) for h in result["holdings"]]
    assert len(keys) == len(set(keys)), "ninguna posicion puede aparecer dos veces"
    aapl = next(h for h in result["holdings"] if h["cusip"] == "037833100")
    assert aapl["value_usd_thousands"] == 75000001.0, (
        "se sirve el valor de la enmienda (RESTATEMENT), no el del filing base"
    )
    assert all(h["accession_number"] == "0000950123-26-000002" for h in result["holdings"])


def test_changes_compute_quarter_over_quarter(db):
    service = ManagerHoldingIngestionService(client=_sec_client_two())
    sync = service.sync_manager(db, cik=CIK)
    assert sync["report_window"] == ["2026-06-30", "2026-03-31"]
    assert len(db.scalars(select(ManagerHolding)).all()) == 9  # 3 rows x 3 accessions

    result = service.changes(db, cik=CIK)
    assert result["status"] == "ok"
    assert result["latest_report"] == "2026-06-30"
    assert result["previous_report"] == "2026-03-31"
    # amendment (filed later) supersedes the base filing in the comparison
    assert result["compared_accessions"]["latest"] == "0000950123-26-000002"
    assert result["compared_accessions"]["previous"] == "0000950123-26-000003"

    by_cusip = {c["cusip"]: c for c in result["changes"]}
    assert by_cusip["037833100"]["change"] == "increased"
    assert by_cusip["037833100"]["shares_latest"] == 300000.0
    assert by_cusip["037833100"]["shares_previous"] == 250000.0
    # restated value comes from the amendment, not the base filing
    assert by_cusip["037833100"]["value_usd_thousands_latest"] == 75000001.0
    assert by_cusip["060505104"]["change"] == "unchanged"
    assert by_cusip["02079K305"]["change"] == "new"
    assert by_cusip["594918104"]["change"] == "closed"
    assert by_cusip["594918104"]["shares_latest"] is None


def test_changes_insufficient_history_is_honest(db):
    service = ManagerHoldingIngestionService(client=_sec_client())
    service.sync_manager(db, cik=CIK)
    result = service.changes(db, cik=CIK)
    assert result["status"] == "insufficient_history"
    assert result["changes"] == []


def test_changes_unknown_manager_is_unavailable(db):
    result = ManagerHoldingIngestionService(client=_sec_client()).changes(db, cik=CIK)
    assert result["status"] == "unavailable"


# --- filas repetidas por clave (secciones "other manager") ------------------


def _info_row(cusip: str, value: str, shares: str, issuer: str = "APPLE INC") -> str:
    return f"""<infoTable><nameOfIssuer>{issuer}</nameOfIssuer><titleOfClass>COM</titleOfClass>
    <cusip>{cusip}</cusip><value>{value}</value>
    <shrsOrPrnAmt><sshPrnamt>{shares}</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt>
    <investmentDiscretion>DFND</investmentDiscretion>
    <votingAuthority><Sole>{shares}</Sole><Shared>0</Shared><None>0</None></votingAuthority></infoTable>"""


# Forma real del 13F de Berkshire (acc. 0001193125-26-352200, 30-06-2026): Apple
# aparece en varias filas con la misma clave; solo la suma cuadra con tableValueTotal.
MULTI_ROWS = (
    [_info_row("037833100", "200237120", "692000")]
    + [_info_row("037833100", "1000", "10")] * 3
    + [_info_row("060505104", "40000000", "1000000", "BANK OF AMERICA CORP")]
)


def _primary_doc(value_total: str, entry_total: int, amendment_type: str | None = None) -> str:
    amendment = f"<amendmentInfo><amendmentType>{amendment_type}</amendmentType></amendmentInfo>" if amendment_type else ""
    return (
        '<edgarSubmission xmlns="http://www.sec.gov/edgar/thirteenffiler"><formData>'
        f"{amendment}<summaryPage><tableEntryTotal>{entry_total}</tableEntryTotal>"
        f"<tableValueTotal>{value_total}</tableValueTotal></summaryPage></formData></edgarSubmission>"
    )


def _multi_client(primary: str | None, submissions: dict | None = None) -> httpx.Client:
    table = (
        '<informationTable xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable">'
        + "".join(MULTI_ROWS)
        + "</informationTable>"
    )
    subs = submissions or {
        "filings": {
            "recent": {
                "accessionNumber": ["0000950123-26-000010"],
                "form": ["13F-HR"],
                "reportDate": ["2026-06-30"],
                "filingDate": ["2026-08-14"],
                "primaryDocument": ["primary_doc.xml"],
            }
        }
    }

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.startswith("https://data.sec.gov/submissions/"):
            return httpx.Response(200, json=subs)
        if url.endswith("index.json"):
            return httpx.Response(200, json=INDEX)
        if url.endswith("form13fInfoTable.xml"):
            return httpx.Response(200, text=table)
        if url.endswith("primary_doc.xml") and primary is not None:
            return httpx.Response(200, text=primary)
        return httpx.Response(404, text="not found")

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_aggregate_rows_sums_value_and_shares_per_key():
    merged = form13f.aggregate_rows(form13f.parse_information_table(
        '<informationTable xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable">'
        + "".join(MULTI_ROWS)
        + "</informationTable>"
    ))
    apple = next(r for r in merged if r["cusip"] == "037833100")
    assert apple["value_usd_thousands"] == "200240120"
    assert apple["ssh_prnamt"] == "692030"
    assert len(merged) == 2


def test_sync_stores_the_sum_of_repeated_keys_and_matches_declared_total(db):
    total = 200237120 + 3 * 1000 + 40000000
    client = _multi_client(_primary_doc(str(total), 5))
    result = ManagerHoldingIngestionService(client).sync_manager(db, cik=CIK)
    assert result["verification"][0]["status"] == "ok"
    assert result["errors"] == []
    rows = db.scalars(select(ManagerHolding)).all()
    assert len(rows) == 2
    assert sum(float(r.value_usd_thousands) for r in rows) == float(total)
    apple = next(r for r in rows if r.cusip == "037833100")
    assert float(apple.value_usd_thousands) == 200240120.0


def test_sync_flags_partial_coverage_when_totals_do_not_match(db):
    client = _multi_client(_primary_doc("999", 5))
    result = ManagerHoldingIngestionService(client).sync_manager(db, cik=CIK)
    assert result["verification"][0]["status"] == "mismatch"
    assert {"accession": "0000950123-26-000010", "error": "totals_mismatch"} in result["errors"]
    manager = db.scalar(select(FundManager))
    # Auditoria A: se guarda el motivo exacto; hacia fuera sigue siendo "partial".
    assert manager is not None and manager.coverage == "mismatch"
    assert result["verification_status"] == "mismatch"
    assert result["provenance"]["coverage"] == "partial"


def test_sync_without_primary_doc_is_unverified_not_ok_claim(db):
    result = ManagerHoldingIngestionService(_multi_client(None)).sync_manager(db, cik=CIK)
    assert result["verification"][0]["status"] == "unverified"


def test_partial_amendment_is_not_ingested_as_the_period_portfolio(db):
    subs = {
        "filings": {
            "recent": {
                "accessionNumber": ["0000950123-26-000011", "0000950123-26-000010"],
                "form": ["13F-HR/A", "13F-HR"],
                "reportDate": ["2026-06-30", "2026-06-30"],
                "filingDate": ["2026-08-20", "2026-08-14"],
                "primaryDocument": ["primary_doc.xml", "primary_doc.xml"],
            }
        }
    }
    client = _multi_client(_primary_doc("1", 1, "NEW HOLDINGS"), subs)
    result = ManagerHoldingIngestionService(client).sync_manager(db, cik=CIK)
    assert [a["accession"] for a in result["skipped_amendments"]] == ["0000950123-26-000011"]
    accessions = {r.accession_number for r in db.scalars(select(ManagerHolding))}
    assert accessions == {"0000950123-26-000010"}


def test_most_bought_counts_a_manager_once_per_cusip_even_with_two_classes(db):
    from datetime import date
    from decimal import Decimal

    from app.services.investors import most_bought

    manager = FundManager(cik=CIK, name=REVIEWED_MANAGERS[CIK], last_report_date=date(2026, 6, 30))
    db.add(manager)
    db.flush()
    for period, acc, shares in ((date(2026, 3, 31), "Q1", "1"), (date(2026, 6, 30), "Q2", "5")):
        for title in ("CL A", "CL B"):
            db.add(
                ManagerHolding(
                    manager_id=manager.id,
                    accession_number=acc,
                    report_date=period,
                    filing_date=period,
                    name_of_issuer="EMISOR X",
                    title_of_class=title,
                    cusip="XXX",
                    # valor proporcional a las acciones: una compra real; con el
                    # valor fijo, 1 → 5 acciones al mismo valor es la firma de
                    # un split 5:1 y ya no cuenta como compra
                    value_usd_thousands=Decimal("10") * Decimal(shares),
                    shares=Decimal(shares),
                    is_amendment=False,
                )
            )
    db.commit()
    item = most_bought(db)["items"][0]
    assert item["buyers_count"] == 1
    assert [b["slug"] for b in item["buyers"]] == ["buffett"]


def test_amendment_without_readable_summary_is_skipped_not_ingested(db):
    subs = {
        "filings": {
            "recent": {
                "accessionNumber": ["0000950123-26-000011", "0000950123-26-000010"],
                "form": ["13F-HR/A", "13F-HR"],
                "reportDate": ["2026-06-30", "2026-06-30"],
                "filingDate": ["2026-08-20", "2026-08-14"],
                "primaryDocument": ["primary_doc.xml", "primary_doc.xml"],
            }
        }
    }
    client = _multi_client(None, subs)
    result = ManagerHoldingIngestionService(client).sync_manager(db, cik=CIK)
    assert result["skipped_amendments"] == [
        {"accession": "0000950123-26-000011", "reason": "summary_unreadable"}
    ]
    accessions = {r.accession_number for r in db.scalars(select(ManagerHolding))}
    assert accessions == {"0000950123-26-000010"}


def test_investor_api_exposes_partial_coverage_after_a_totals_mismatch(db):
    from app.services.investors import INVESTORS, investor_detail, list_investors

    ManagerHoldingIngestionService(_multi_client(_primary_doc("999", 5))).sync_manager(db, cik=CIK)
    slug = next(i.slug for i in INVESTORS if i.cik == CIK)
    listed = next(i for i in list_investors(db)["investors"] if i["slug"] == slug)
    detail = investor_detail(db, slug)
    assert detail is not None
    assert listed["coverage"] == "partial"
    assert detail["coverage"] == "partial"
    others = [i for i in list_investors(db)["investors"] if i["slug"] != slug]
    assert all(i["coverage"] is None for i in others)


def test_information_table_url_handles_styled_primary_document_and_hyphenated_name():
    """Trian: primaryDocument con carpeta xsl y tabla 'Q22026-tfmlp-info-table.xml' daba 0 filas."""
    index = {"directory": {"item": [{"name": "primary_doc.xml"}, {"name": "Q22026-tfmlp-info-table.xml"}]}}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=index)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        url = form13f.information_table_url(
            "0001345471", "0001345471-26-000035", "xslForm13F_X02/primary_doc.xml", client=client
        )
    assert url is not None and url.endswith("/Q22026-tfmlp-info-table.xml")


# --- Escala del valor 13F (heuristica por filing) ---------------------------------
# Filas reales guardadas (BD de produccion, 2026-06-30): Baupost, Duquesne y AKO
# declaran el valor en miles aunque el periodo sea posterior a 2022-12-31; Berkshire
# (MULTI_ROWS, Apple 200237120 / 692000 acciones = ~289 USD) declara en dolares.
_THOUSANDS_FILERS = {
    "baupost": [("023135106", "892310", "3743854"), ("28176E108", "493140", "1275154"),
                ("76131D103", "597208", "8080112")],
    "duquesne": [("632307104", "864923", "3186306"), ("00287Y109", "120000", "900000"),
                 ("594918104", "90000", "250000")],
    "ako": [("H01301128", "651941", "9683004"), ("G0176J109", "200000", "2000000"),
            ("N070592100", "150000", "1500000")],
}


def _rows_for(name: str) -> list[dict]:
    return form13f.aggregate_rows(
        [
            {"cusip": c, "title_of_class": "COM", "put_call": "", "value_usd_thousands": v,
             "ssh_prnamt": s, "ssh_prnamt_type": "SH"}
            for c, v, s in _THOUSANDS_FILERS[name]
        ]
    )


@pytest.mark.parametrize("name", ["baupost", "duquesne", "ako"])
def test_infer_value_scale_detects_filers_that_still_report_in_thousands(name):
    info = form13f.infer_value_scale(_rows_for(name), "2026-06-30")
    assert info["scale"] == form13f.SCALE_THOUSANDS
    assert float(info["median_implied_price"]) < 1
    scaled = form13f.apply_value_scale(_rows_for(name), info["scale"])
    first = _THOUSANDS_FILERS[name][0]
    assert next(r for r in scaled if r["cusip"] == first[0])["value_usd_thousands"] == str(int(first[1]) * 1000)


def test_infer_value_scale_keeps_berkshire_in_dollars_as_control():
    rows = form13f.aggregate_rows(form13f.parse_information_table(
        '<informationTable xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable">'
        + "".join(MULTI_ROWS) + "</informationTable>"
    ))
    # Solo 2 claves (Apple, BofA): sin filas suficientes no se decide y no se escala.
    info = form13f.infer_value_scale(rows, "2026-06-30")
    assert info["scale"] == form13f.SCALE_DOLLARS and info["reason"] == "insufficient_rows"
    assert form13f.apply_value_scale(rows, info["scale"]) is rows
    many = [{"cusip": str(i), "title_of_class": "COM", "put_call": "", "value_usd_thousands": "3000000000",
             "ssh_prnamt": "10000000", "ssh_prnamt_type": "SH"} for i in range(5)]
    assert form13f.infer_value_scale(many, "2026-06-30")["scale"] == form13f.SCALE_DOLLARS


def test_infer_value_scale_does_not_touch_legacy_periods_or_option_rows():
    legacy = form13f.infer_value_scale(_rows_for("baupost"), "2020-06-30")
    assert legacy["scale"] is None and legacy["reason"] == "legacy_period"
    options_only = [{"cusip": str(i), "title_of_class": "COM", "put_call": "Call", "value_usd_thousands": "5",
                     "ssh_prnamt": "1000", "ssh_prnamt_type": "SH"} for i in range(5)]
    assert form13f.infer_value_scale(options_only, "2026-06-30")["reason"] == "insufficient_rows"


def test_sync_scales_a_thousands_filing_and_stores_which_scale_was_used(db):
    global MULTI_ROWS
    original = MULTI_ROWS
    try:
        MULTI_ROWS = [_info_row(c, v, s, "ISSUER") for c, v, s in _THOUSANDS_FILERS["baupost"]]
        total_raw = sum(int(v) for _, v, _ in _THOUSANDS_FILERS["baupost"])
        client = _multi_client(_primary_doc(str(total_raw), 3))
        result = ManagerHoldingIngestionService(client).sync_manager(db, cik=CIK)
    finally:
        MULTI_ROWS = original
    check = result["verification"][0]
    assert check["status"] == "ok"  # el total declarado (en miles) x1000 cuadra con lo guardado
    assert check["value_scale"]["scale"] == form13f.SCALE_THOUSANDS
    rows = db.scalars(select(ManagerHolding)).all()
    assert {r.value_scale for r in rows} == {form13f.SCALE_THOUSANDS}
    assert sum(float(r.value_usd_thousands) for r in rows) == float(total_raw * 1000)


def test_sync_of_a_dollar_filing_stores_raw_values_and_flags_the_scale(db):
    total = 200237120 + 3 * 1000 + 40000000
    result = ManagerHoldingIngestionService(_multi_client(_primary_doc(str(total), 5))).sync_manager(db, cik=CIK)
    assert result["verification"][0]["value_scale"]["scale"] == form13f.SCALE_DOLLARS
    assert {r.value_scale for r in db.scalars(select(ManagerHolding)).all()} == {form13f.SCALE_DOLLARS}


def test_detect_scale_jump_flags_100x_between_quarters() -> None:
    from decimal import Decimal

    from app.services.manager_holding_ingestion_service import detect_scale_jump

    jump = detect_scale_jump({"2026-03-31": Decimal("5115380"), "2026-06-30": Decimal("5415853000")})
    assert jump is not None
    assert jump["periods"] == ["2026-03-31", "2026-06-30"]


def test_detect_scale_jump_ignores_normal_moves_and_missing_data() -> None:
    from decimal import Decimal

    from app.services.manager_holding_ingestion_service import detect_scale_jump

    assert detect_scale_jump({"2026-03-31": Decimal("5000"), "2026-06-30": Decimal("9000")}) is None
    assert detect_scale_jump({"2026-03-31": Decimal("0"), "2026-06-30": Decimal("9000")}) is None
    assert detect_scale_jump({"2026-06-30": Decimal("9000")}) is None


def _sec_client_latest_down() -> httpx.Client:
    """El trimestre mas reciente falla (503) y el anterior se descarga bien."""

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.startswith("https://data.sec.gov/submissions/"):
            return httpx.Response(200, json=SUBMISSIONS_TWO)
        if url.endswith("index.json"):
            return httpx.Response(200, json=INDEX)
        if url.endswith("form13fInfoTable.xml"):
            if "000095012326000003" in url:
                return httpx.Response(200, text=TABLE_ACC3)
            return httpx.Response(503, text="down")
        if url.endswith("primary_doc.xml"):
            return httpx.Response(200, text=RESTATEMENT_DOC)
        return httpx.Response(404, text="not found")

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_latest_report_failing_keeps_serving_last_stored_period(db):
    """Si el 13F mas reciente no se pudo descargar, last_report_date no puede
    apuntar a un periodo sin filas: la ficha salia «ok» con 0 posiciones."""
    service = ManagerHoldingIngestionService(client=_sec_client_latest_down())
    out = service.sync_manager(db, cik=CIK)
    assert out["errors"], "el fallo del trimestre reciente se declara"
    result = service.latest_holdings(db, cik=CIK)
    assert result["status"] == "unverified"  # nunca "ok" con 0 posiciones ni sin contraste
    assert result["report_date"] == "2026-03-31"
    assert result["coverage"] == "partial"
    assert {h["cusip"] for h in result["holdings"]} == {"037833100", "060505104", "594918104"}


def test_latest_report_failing_does_not_regress_a_newer_stored_period(db):
    """Un re-sync con el trimestre nuevo caido no retrocede a uno anterior
    si el nuevo ya estaba guardado de una corrida previa."""
    ManagerHoldingIngestionService(client=_sec_client_two()).sync_manager(db, cik=CIK)
    service = ManagerHoldingIngestionService(client=_sec_client_latest_down())
    service.sync_manager(db, cik=CIK)
    result = service.latest_holdings(db, cik=CIK)
    assert result["report_date"] == "2026-06-30"
    assert len(result["holdings"]) == 3



def test_latest_holdings_reports_mismatch_not_ok_after_totals_mismatch(db):
    """Auditoria A: con totales que no cuadran se ingerian las filas y
    ``latest_holdings`` devolvia status="ok". Ahora el estado es exacto."""
    ManagerHoldingIngestionService(_multi_client(_primary_doc("999", 5))).sync_manager(db, cik=CIK)
    served = ManagerHoldingIngestionService().latest_holdings(db, cik=CIK)
    assert served["status"] == "mismatch"
    assert served["verification"] == "mismatch"
    assert served["coverage"] == "partial"
    assert served["provenance"]["coverage"] == "partial"
    assert len(served["holdings"]) == 2  # las cifras se ven, pero marcadas


def test_unreadable_summary_marks_unverified_and_partial_coverage(db):
    """Sin resumen legible no hay contraste: antes quedaba coverage="ok"."""
    result = ManagerHoldingIngestionService(_multi_client(None)).sync_manager(db, cik=CIK)
    assert result["verification_status"] == "unverified"
    served = ManagerHoldingIngestionService().latest_holdings(db, cik=CIK)
    assert served["status"] == "unverified"
    assert served["verification"] == "unverified"
    assert served["coverage"] == "partial"
    from app.services.investors import INVESTORS, investor_detail, list_investors

    slug = next(i.slug for i in INVESTORS if i.cik == CIK)
    detail = investor_detail(db, slug)
    assert detail is not None
    assert detail["coverage"] == "partial"
    assert detail["verification"] == "unverified"
    listed = next(i for i in list_investors(db)["investors"] if i["slug"] == slug)
    assert listed["coverage"] == "partial"
    assert listed["verification"] == "unverified"


def test_verified_totals_keep_status_ok(db):
    total = 200237120 + 3 * 1000 + 40000000
    result = ManagerHoldingIngestionService(_multi_client(_primary_doc(str(total), 5))).sync_manager(db, cik=CIK)
    assert result["verification_status"] == "verified"
    served = ManagerHoldingIngestionService().latest_holdings(db, cik=CIK)
    assert served["status"] == "ok"
    assert served["verification"] == "verified"
    assert served["coverage"] == "ok"
