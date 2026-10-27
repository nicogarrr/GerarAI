"""Senales insider (Form 4 EDGAR): tests hermeticos, sin red.

- Parse de XML Form 4 de ejemplo (mock): ticker, insider, rol, P/S,
  acciones, precio, valor.
- Deteccion: cluster_buy (>=3 insiders / 30 dias), c_suite_buy (CEO/CFO),
  big_buy (>$1M).
- Endpoint GET /api/insider/signals con EDGAR mockeado.
- Enganche Telegram: apagado por defecto y nunca rompe.
"""

from fastapi.testclient import TestClient

import main
from app.services import insider_service
from app.services.connectors import form4 as form4_connector

CEO_BUY_XML = """<ownershipDocument>
  <schemaVersion>X0306</schemaVersion>
  <documentType>4</documentType>
  <periodOfReport><value>2024-03-15</value></periodOfReport>
  <issuer>
    <issuerCik>0001234567</issuerCik>
    <issuerName>ACME Corp</issuerName>
    <issuerTradingSymbol>ACME</issuerTradingSymbol>
  </issuer>
  <reportingOwner>
    <reportingOwnerId>
      <rptOwnerCik>0001111111</rptOwnerCik>
      <rptOwnerName>DOE JANE</rptOwnerName>
    </reportingOwnerId>
    <reportingOwnerRelationship>
      <isDirector>1</isDirector>
      <isOfficer>1</isOfficer>
      <officerTitle><value>Chief Executive Officer</value></officerTitle>
    </reportingOwnerRelationship>
  </reportingOwner>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <securityTitle><value>Common Stock</value></securityTitle>
      <transactionDate><value>2024-03-10</value></transactionDate>
      <transactionCoding>
        <transactionCode><value>P</value></transactionCode>
      </transactionCoding>
      <transactionAmounts>
        <transactionShares><value>5000</value></transactionShares>
        <transactionPricePerShare><value>250</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
</ownershipDocument>"""

SALE_XML = """<ownershipDocument>
  <documentType>4</documentType>
  <periodOfReport><value>2024-03-15</value></periodOfReport>
  <issuer>
    <issuerCik>0001234567</issuerCik>
    <issuerName>ACME Corp</issuerName>
    <issuerTradingSymbol>ACME</issuerTradingSymbol>
  </issuer>
  <reportingOwner>
    <reportingOwnerId>
      <rptOwnerCik>0002222222</rptOwnerCik>
      <rptOwnerName>SMITH JOHN</rptOwnerName>
    </reportingOwnerId>
    <reportingOwnerRelationship>
      <isDirector>1</isDirector>
      <isOfficer>0</isOfficer>
    </reportingOwnerRelationship>
  </reportingOwner>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <securityTitle><value>Common Stock</value></securityTitle>
      <transactionDate><value>2024-03-11</value></transactionDate>
      <transactionCoding>
        <transactionCode><value>S</value></transactionCode>
      </transactionCoding>
      <transactionAmounts>
        <transactionShares><value>1000</value></transactionShares>
        <transactionPricePerShare><value>260</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>D</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
</ownershipDocument>"""


def _buy(insider, cik, title, day, value=100.0, shares=100.0):
    return {
        "ticker": "ACME",
        "insider": insider,
        "insider_cik": cik,
        "role": f"officer ({title})" if title else "director",
        "officer_title": title,
        "type": "P",
        "acquired_disposed": "A",
        "shares": shares,
        "price": value / shares,
        "value": value,
        "date": f"2024-03-{day:02d}",
    }


# ---------------- Parse ----------------


def test_form4_parse_extracts_ticker_insider_role_and_amounts():
    parsed = form4_connector.parse_form4_xml(CEO_BUY_XML)
    assert parsed["ticker"] == "ACME"
    assert parsed["issuer_name"] == "ACME Corp"
    assert len(parsed["transactions"]) == 1
    tx = parsed["transactions"][0]
    assert tx["insider"] == "DOE JANE"
    assert "Chief Executive Officer" in tx["role"]
    assert tx["type"] == "P"
    assert tx["shares"] == 5000
    assert tx["price"] == 250
    assert tx["value"] == 5000 * 250
    assert tx["date"] == "2024-03-10"


def test_form4_parse_rejects_non_ownership_document():
    import pytest

    with pytest.raises(ValueError):
        form4_connector.parse_form4_xml("<html></html>")


def test_open_market_buy_distinguishes_sale():
    buy = form4_connector.parse_form4_xml(CEO_BUY_XML)["transactions"][0]
    sale = form4_connector.parse_form4_xml(SALE_XML)["transactions"][0]
    assert form4_connector.is_open_market_buy(buy) is True
    assert form4_connector.is_open_market_buy(sale) is False
    assert insider_service.open_market_buys([buy, sale]) == [buy]


def test_sec_rate_limit_and_user_agent_contact():
    assert form4_connector.MIN_INTERVAL_SECONDS == 0.1  # 10 req/s
    assert "@" in form4_connector.resolve_user_agent()


# ---------------- Senales ----------------


def test_big_buy_over_one_million():
    txs = [_buy("DOE JANE", "0001111111", "Chief Executive Officer", 10, value=1_250_000.0)]
    signals = insider_service.detect_signals(txs)
    big = [s for s in signals if s["signal"] == "big_buy"]
    assert len(big) == 1
    assert big[0]["value"] == 1_250_000.0


def test_no_big_buy_below_threshold():
    txs = [_buy("DOE JANE", "0001111111", "Chief Executive Officer", 10, value=50_000.0)]
    assert [s for s in insider_service.detect_signals(txs) if s["signal"] == "big_buy"] == []


def test_c_suite_buy_ceo_and_cfo():
    txs = [
        _buy("DOE JANE", "0001111111", "Chief Executive Officer", 10),
        _buy("ROE RICH", "0003333333", "Chief Financial Officer", 11),
        _buy("SMITH JOHN", "0002222222", None, 12),  # director: no es c-suite
    ]
    c_suite = [s for s in insider_service.detect_signals(txs) if s["signal"] == "c_suite_buy"]
    assert {s["insider"] for s in c_suite} == {"DOE JANE", "ROE RICH"}


def test_cluster_buy_needs_three_insiders_in_30_days():
    txs = [
        _buy("A", "0000000001", None, 1),
        _buy("B", "0000000002", None, 10),
        _buy("C", "0000000003", None, 20),
    ]
    clusters = [s for s in insider_service.detect_signals(txs) if s["signal"] == "cluster_buy"]
    assert len(clusters) == 1
    assert clusters[0]["insider_count"] == 3
    assert clusters[0]["ticker"] == "ACME"

    two = txs[:2]  # solo 2 insiders -> sin cluster
    assert [s for s in insider_service.detect_signals(two) if s["signal"] == "cluster_buy"] == []

    spread = [
        _buy("A", "0000000001", None, 1),
        _buy("B", "0000000002", None, 1),
        _buy("C", "0000000003", None, 1),
    ]
    # Mismo insider 3 veces no es cluster (cuenta insiders distintos).
    same = [_buy("A", "0000000001", None, d) for d in (1, 2, 3)]
    assert spread and [s for s in insider_service.detect_signals(same) if s["signal"] == "cluster_buy"] == []


def test_sales_never_produce_buy_signals():
    sale = form4_connector.parse_form4_xml(SALE_XML)["transactions"][0]
    assert insider_service.detect_signals([sale]) == []


# ---------------- Enganche Telegram (nunca rompe) ----------------


def test_notify_skipped_when_flag_disabled(monkeypatch):
    monkeypatch.setenv("INSIDER_ALERTS_ENABLED", "false")
    from app.core.config import get_settings

    get_settings.cache_clear()
    try:
        result = insider_service.maybe_notify_insider_buy(
            "ACME", [{"signal": "big_buy", "detail": "x"}]
        )
    finally:
        get_settings.cache_clear()
    assert result["status"] == "skipped"


def test_notify_never_raises_even_if_notifier_booms(monkeypatch):
    monkeypatch.setenv("INSIDER_ALERTS_ENABLED", "true")
    from app.core.config import get_settings

    get_settings.cache_clear()
    try:
        def boom(_payload):
            raise RuntimeError("telegram caido")

        result = insider_service.maybe_notify_insider_buy(
            "ACME", [{"signal": "cluster_buy", "detail": "x"}], notifier=boom
        )
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()
    assert result["status"] == "skipped"


def test_notify_delivers_through_injected_notifier(monkeypatch):
    monkeypatch.setenv("INSIDER_ALERTS_ENABLED", "true")
    from app.core.config import get_settings

    get_settings.cache_clear()
    seen = {}
    try:
        def fake(payload):
            seen["text"] = payload["message"]
            return {"status": "delivered"}

        result = insider_service.maybe_notify_insider_buy(
            "ACME",
            [{"signal": "c_suite_buy", "detail": "CEO DOE JANE compra en mercado abierto"}],
            notifier=fake,
        )
    finally:
        get_settings.cache_clear()
    assert result["status"] == "delivered"
    assert "insider buy" in seen["text"].lower()


# ---------------- Endpoint ----------------


def test_insider_signals_endpoint_with_mocked_edgar(monkeypatch):
    from app.services import insider_persistence

    # La persistencia tiene sus propios tests; aqui el contrato es la lectura.
    monkeypatch.setattr(insider_persistence, "persist_filing", lambda *a, **k: None)
    monkeypatch.setattr(
        insider_service, "_cik_for_ticker", lambda ticker, client=None: "0001234567"
    )
    monkeypatch.setattr(
        form4_connector,
        "recent_form4_filings",
        lambda cik, limit=20, client=None: [
            {
                "accession_number": "0001234567-24-000001",
                "filing_date": "2024-03-12",
                "document_url": "https://www.sec.gov/Archives/edgar/data/1234567/x.xml",
            }
        ],
    )
    monkeypatch.setattr(
        form4_connector, "fetch_filing_xml", lambda url, client=None: CEO_BUY_XML
    )

    client = TestClient(main.app, raise_server_exceptions=False)
    response = client.get("/api/insider/signals?ticker=ACME")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ticker"] == "ACME"
    assert payload["status"] == "ok"
    kinds = {s["signal"] for s in payload["signals"]}
    assert {"big_buy", "c_suite_buy"} <= kinds


def test_insider_signals_endpoint_survives_persistence_integrity_error(monkeypatch):
    """Un IntegrityError al guardar no convierte el escaneo en 500 ni en
    'todas las transacciones fallaron': hay lectura parcial con aviso."""
    from sqlalchemy.exc import IntegrityError

    from app.services import insider_persistence

    monkeypatch.setattr(
        insider_service, "_cik_for_ticker", lambda ticker, client=None: "0001234567"
    )
    monkeypatch.setattr(
        form4_connector,
        "recent_form4_filings",
        lambda cik, limit=20, client=None: [
            {
                "accession_number": "0001234567-24-000099",
                "filing_date": "2024-03-12",
                "document_url": "https://www.sec.gov/Archives/edgar/data/1234567/x.xml",
            }
        ],
    )
    monkeypatch.setattr(
        form4_connector, "fetch_filing_xml", lambda url, client=None: CEO_BUY_XML
    )

    def boom(*args, **kwargs):
        raise IntegrityError("INSERT", {}, Exception("duplicate key"))

    monkeypatch.setattr(insider_persistence, "persist_filing", boom)
    client = TestClient(main.app, raise_server_exceptions=False)
    response = client.get("/api/insider/signals?ticker=ACME")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "partial"
    assert payload["filings_parsed"] == 1
    assert payload["filings_failed"] == 0
    assert payload["persist_error_count"] == 1
    assert payload["warnings"]
    assert payload["signals"]


def test_insider_signals_endpoint_degrades_without_network(monkeypatch):
    def boom(*args, **kwargs):
        raise ConnectionError("red caida")

    monkeypatch.setattr(insider_service, "_cik_for_ticker", boom)
    client = TestClient(main.app, raise_server_exceptions=False)
    response = client.get("/api/insider/signals?ticker=ACME")
    assert response.status_code == 200
    assert response.json()["signals"] == []


# ---------------- PR-1 correctness: 4/A, multi-reporter, wording, source URL ----------------

AMENDMENT_SUBMISSIONS = {
    "filings": {
        "recent": {
            "accessionNumber": ["0001234567-24-000001", "0001234567-24-000002", "0001234567-24-000003"],
            "form": ["4", "4/A", "8-K"],
            "filingDate": ["2024-03-01", "2024-03-05", "2024-03-06"],
            "reportDate": ["2024-02-28", "2024-02-28", "2024-03-06"],
            "primaryDocument": ["f4.xml", "f4a.xml", "pr.htm"],
        }
    }
}


def test_recent_filings_include_4a_amendments_and_preserve_form():
    """Las enmiendas 4/A no deben quedar invisibles; el form crudo se conserva."""
    import httpx

    def handler(request):
        return httpx.Response(200, json=AMENDMENT_SUBMISSIONS)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    filings = form4_connector.recent_form4_filings(1234567, client=client)
    forms = [f["form"] for f in filings]
    assert forms == ["4", "4/A"]


MULTI_REPORTER_XML = CEO_BUY_XML.replace(
    "</reportingOwner>",
    """</reportingOwner>
  <reportingOwner>
    <reportingOwnerId>
      <rptOwnerCik>0003333333</rptOwnerCik>
      <rptOwnerName>SECOND REPORTER</rptOwnerName>
    </reportingOwnerId>
    <reportingOwnerRelationship>
      <isDirector>1</isDirector>
    </reportingOwnerRelationship>
  </reportingOwner>""",
    1,
)


def test_multi_reporter_filing_is_never_silently_attributed():
    """Un filing conjunto marca multi_reporter y lista a todos, sin atribuir al primero."""
    parsed = form4_connector.parse_form4_xml(MULTI_REPORTER_XML)
    tx = parsed["transactions"][0]
    assert tx["multi_reporter"] is True
    assert tx["reporters_count"] == 2
    assert tx["attribution"] == "joint_filing"
    assert "DOE JANE" in tx["insider"] and "SECOND REPORTER" in tx["insider"]
    assert tx["insider_cik"] == ""
    assert tx["role"] == "multiple insiders"

    single = form4_connector.parse_form4_xml(CEO_BUY_XML)["transactions"][0]
    assert single["multi_reporter"] is False
    assert single["attribution"] == "single_reporter"
    assert single["insider"] == "DOE JANE"


def test_c_suite_wording_never_overstates_open_market():
    tx = _buy("DOE JANE", "0001111111", "Chief Executive Officer", 10, value=100.0)
    signals = insider_service.detect_signals([tx])
    c_suite = [s for s in signals if s["signal"] == "c_suite_buy"]
    assert c_suite, "expected a c_suite_buy signal"
    assert "mercado abierto o privado" in c_suite[0]["detail"]
    assert "compra en mercado abierto" not in c_suite[0]["detail"]


def test_signals_carry_sec_source_url(monkeypatch):
    """Las senales enlazan al filing SEC de origen (trazabilidad)."""
    monkeypatch.setattr(
        insider_service,
        "_cik_for_ticker",
        lambda ticker, client=None: "0001234567",
    )
    filing = {
        "form": "4",
        "accession_number": "0001234567-24-000001",
        "filing_date": "2024-03-16",
        "document_url": "https://www.sec.gov/Archives/edgar/data/1234567/000123456724000001/f4.xml",
    }
    monkeypatch.setattr(
        form4_connector,
        "recent_form4_filings",
        lambda cik, limit=20, client=None: [filing],
    )
    big_xml = CEO_BUY_XML.replace("<value>5000</value>", "<value>50000</value>")
    result = insider_service.get_signals_for_ticker("ACME", fetcher=lambda f: big_xml)
    assert result["status"] == "ok"
    big = [s for s in result["signals"] if s["signal"] == "big_buy"]
    assert big and big[0]["source_url"] == filing["document_url"]
    assert big[0]["form"] == "4"
    c_suite = [s for s in result["signals"] if s["signal"] == "c_suite_buy"]
    assert c_suite and c_suite[0]["source_url"] == filing["document_url"]


def test_cluster_survives_malformed_value_strings():
    # Form 4 fields arrive from XML: a non-numeric value must not crash
    # signal detection, and unknown values simply do not add to the total.
    txs = [
        _buy("A", "0000000001", None, 1, value=100_000.0),
        _buy("B", "0000000002", None, 2, value=50_000.0),
        _buy("C", "0000000003", None, 3, value=25_000.0),
    ]
    txs[1]["value"] = "not-a-number"
    txs[2]["value"] = None
    signals = insider_service.detect_signals(txs)
    cluster = [s for s in signals if s["signal"] == "cluster_buy"]
    assert len(cluster) == 1
    assert cluster[0]["total_value"] == 100_000.0
    assert cluster[0]["insider_count"] == 3


def test_big_buy_ignores_malformed_value():
    tx = _buy("DOE JANE", "0001111111", "Chief Executive Officer", 10, value=1_500_000.0)
    tx["value"] = "$1.5M"
    txs = [tx]
    signals = insider_service.detect_signals(txs)
    assert [s for s in signals if s["signal"] == "big_buy"] == []
    # The c-suite signal still fires, with an honest null value.
    c_suite = [s for s in signals if s["signal"] == "c_suite_buy"]
    assert len(c_suite) == 1 and c_suite[0]["value"] is None


def test_sec_user_agent_wraps_product_style(monkeypatch):
    """Regresion F11: UA de producto con contacto -> 403 en SEC. Se envuelve
    en UA tipo navegador extrayendo el email, aunque venga mal concatenado."""
    monkeypatch.setenv("SEC_USER_AGENT", "GerarAI/0.1nicogarrr@users.noreply.github.com")
    ua = form4_connector.resolve_user_agent()
    assert ua.startswith("Mozilla/5.0")
    assert "+mailto:nicogarrr@users.noreply.github.com" in ua


def test_sec_user_agent_respects_custom_browser_ua(monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", "Mozilla/5.0 (X11; Linux) custom/1.0 mailto:a@b.c")
    assert form4_connector.resolve_user_agent().startswith("Mozilla/5.0 (X11; Linux)")


def test_two_buys_same_insider_date_form_file_have_distinct_identity():
    """Dos lotes codigo P del mismo insider en la misma fecha, formulario y
    fichero: la identidad por transaccion (accession + linea) los distingue;
    una clave compartida hacia que React reutilizara la fila equivocada."""
    first = _buy("DOE JANE", "0001111111", "Chief Executive Officer", 10, value=100_000.0, shares=400.0)
    second = _buy("DOE JANE", "0001111111", "Chief Executive Officer", 10, value=250_000.0, shares=1_000.0)
    for tx in (first, second):
        tx["accession_number"] = "0001234567-24-000042"
    first["tx_line"] = 0
    second["tx_line"] = 1

    signals = [s for s in insider_service.detect_signals([first, second]) if s["signal"] == "c_suite_buy"]
    assert len(signals) == 2
    identities = {(s["accession_number"], s["tx_line"]) for s in signals}
    assert identities == {("0001234567-24-000042", 0), ("0001234567-24-000042", 1)}
    # Campos de ejecucion presentes para respuestas que distingan por lote.
    assert all("shares" in s and "price" in s for s in signals)


def test_signals_propagate_execution_identity_fields():
    """big_buy y c_suite_buy llevan accession_number/tx_line/shares/price:
    sin ellos el frontend no puede componer una clave por transaccion."""
    tx = _buy("DOE JANE", "0001111111", "Chief Executive Officer", 10, value=1_250_000.0)
    tx["accession_number"] = "0001234567-24-000043"
    tx["tx_line"] = 2
    signals = insider_service.detect_signals([tx])
    for signal in signals:
        assert signal["accession_number"] == "0001234567-24-000043"
        assert signal["tx_line"] == 2


def test_all_filings_failing_with_sec_403_declares_the_reason(monkeypatch):
    class _Forbidden(Exception):
        class response:  # noqa: N801 - imita httpx.HTTPStatusError
            status_code = 403

    filings = [
        {"form": "4", "accession_number": f"0000000000-26-00000{i}", "filing_date": "2026-10-01",
         "document_url": f"https://www.sec.gov/Archives/edgar/data/1/{i}/form4.xml"}
        for i in range(3)
    ]
    monkeypatch.setattr(form4_connector, "recent_form4_filings", lambda *a, **k: filings)

    def _blocked(_filing):
        raise _Forbidden("403")

    result = insider_service.get_signals_for_ticker("ACME", cik="1234567", fetcher=_blocked)
    assert result["status"] == "degraded"
    assert result["filings_failed"] == 3
    assert result["reason"] == "sec_bloquea_datacenter"


def test_mixed_failure_causes_do_not_claim_a_single_reason(monkeypatch):
    class _Forbidden(Exception):
        class response:  # noqa: N801
            status_code = 403

    filings = [
        {"form": "4", "accession_number": f"0000000000-26-00000{i}", "filing_date": "2026-10-01",
         "document_url": f"https://www.sec.gov/Archives/edgar/data/1/{i}/form4.xml"}
        for i in range(2)
    ]
    monkeypatch.setattr(form4_connector, "recent_form4_filings", lambda *a, **k: filings)
    calls = iter([_Forbidden("403"), ValueError("parse")])

    def _mixed(_filing):
        raise next(calls)

    result = insider_service.get_signals_for_ticker("ACME", cik="1234567", fetcher=_mixed)
    assert result["status"] == "degraded"
    assert "reason" not in result
