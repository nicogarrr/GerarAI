"""Cobertura de los helpers de insider_service (gate >=85% por fichero).

Nacen con el fix de procedencia (fetched_at honesto): el fichero quedaba en
81% por caminos de utilidad sin test directo. Cada test fija el contrato real
del helper, no relleno: cache de XML best-effort, parseo tolerante de fechas y
numeros del Form 4, mapa ticker->CIK cacheado y alertas Telegram que nunca
rompen el flujo.
"""

from datetime import UTC, date, datetime

import pytest

from app.services import insider_service
from app.services.insider_service import (
    _parse_date,
    _to_float,
    insider_buy_alert_text,
    maybe_notify_insider_buy,
)


@pytest.fixture(autouse=True)
def _clean_caches(monkeypatch):
    insider_service.clear_filing_xml_cache()
    monkeypatch.setattr(insider_service, "_CIK_MAP_CACHE", None)
    monkeypatch.setattr(insider_service, "_CIK_MAP_LOADED_AT", 0.0)
    yield
    insider_service.clear_filing_xml_cache()


def test_parse_date_formatos_y_basura():
    assert _parse_date(None) is None
    assert _parse_date(date(2024, 3, 15)) == date(2024, 3, 15)
    assert _parse_date(datetime(2024, 3, 15, 10, 30, tzinfo=UTC)) == date(2024, 3, 15)
    assert _parse_date("2024-03-15") == date(2024, 3, 15)
    assert _parse_date("03/15/2024") == date(2024, 3, 15)  # formato US del XML
    assert _parse_date("no es una fecha") is None
    assert _parse_date("") is None


def test_to_float_tolerante():
    assert _to_float(None) is None
    assert _to_float(True) is None  # bool no es importe
    assert _to_float("1234.5") == 1234.5
    assert _to_float(42) == 42.0
    assert _to_float("garbage") is None
    assert _to_float(-3) is None  # importes de Form 4 no negativos
    assert _to_float(float("inf")) is None


def test_load_cik_map_cachea_por_proceso():
    calls = []

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"0": {"ticker": "acme", "cik_str": 12345}, "1": "fila rota ignorada"}

    class _Client:
        def get(self, url, headers=None):
            calls.append(url)
            return _Resp()

    first = insider_service._load_cik_map(client=_Client())
    second = insider_service._load_cik_map(client=_Client())
    assert first == {"ACME": "0000012345"}
    assert second is first  # cache de proceso: una sola descarga
    assert len(calls) == 1


def test_cik_for_ticker_exacto():
    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"0": {"ticker": "ACME", "cik_str": 12345}}

    class _Client:
        def get(self, url, headers=None):
            return _Resp()

    assert insider_service._cik_for_ticker("acme", client=_Client()) == "0000012345"
    assert insider_service._cik_for_ticker("NOPE", client=_Client()) is None


def test_alert_text_y_notify_nunca_rompen(monkeypatch):
    sig = {"signal": "cluster_buy", "detail": "3 insiders compran ACME en 30 dias"}
    text = insider_buy_alert_text("acme", [sig, {"signal": "sale", "detail": "no cuenta"}])
    assert "Insider buy — ACME" in text
    assert "cluster_buy" in text and "no cuenta" not in text

    monkeypatch.setattr(
        insider_service, "get_settings",
        lambda: type("S", (), {"insider_alerts_enabled": False})(),
    )
    assert maybe_notify_insider_buy("ACME", [sig])["status"] == "skipped"

    monkeypatch.setattr(
        insider_service, "get_settings",
        lambda: type("S", (), {"insider_alerts_enabled": True})(),
    )
    assert maybe_notify_insider_buy("ACME", [])["reason"] == "no buy signals"
    sent = maybe_notify_insider_buy("ACME", [sig], notifier=lambda payload: {"status": "sent", "payload": payload})
    assert sent["status"] == "sent"
    assert sent["payload"]["alert_id"] == "insider-ACME"

    def _boom(payload):
        raise RuntimeError("telegram caido")

    failed = maybe_notify_insider_buy("ACME", [sig], notifier=_boom)
    assert failed["status"] == "skipped"  # notificar jamas rompe el flujo


def test_fetch_filing_xml_cache_best_effort(monkeypatch):
    from app.services.connectors import form4 as form4_connector

    monkeypatch.setattr(
        form4_connector, "fetch_filing_xml",
        lambda url, client=None: "<xml>filing</xml>",
    )

    class _Client:
        pass

    text, fetched_at = insider_service._cached_filing_xml(
        {"document_url": "https://sec.gov/x.xml", "accession_number": "0001-24-000001"},
        client=_Client(),
    )
    assert text == "<xml>filing</xml>"
    assert fetched_at is None  # primer fetch: sin fecha cacheada

    # Segunda llamada: sirve la cache y devuelve su fecha real de descarga.
    text2, fetched_at2 = insider_service._cached_filing_xml(
        {"document_url": "https://sec.gov/x.xml", "accession_number": "0001-24-000001"},
        client=_Client(),
    )
    assert text2 == "<xml>filing</xml>"
    datetime.fromisoformat(fetched_at2)

    # La cache nunca rompe el fetch: un dict que lanza se traga el error.
    class _Exploding(dict):
        def get(self, *a, **k):
            raise RuntimeError("cache rota")

        def __setitem__(self, *a, **k):
            raise RuntimeError("cache rota")

    monkeypatch.setattr(insider_service, "_xml_cache", _Exploding())
    text3, _ = insider_service._cached_filing_xml(
        {"document_url": "https://sec.gov/y.xml", "accession_number": "0002-24-000002"},
        client=_Client(),
    )
    assert text3 == "<xml>filing</xml>"


_XML = """<?xml version="1.0"?>
<ownershipDocument>
  <issuer><issuerCik>0001234567</issuerCik><issuerTradingSymbol>ACME</issuerTradingSymbol></issuer>
  <reportingOwner><reportingOwnerId><rptOwnerCik>0001111111</rptOwnerCik><rptOwnerName>Jane CEO</rptOwnerName></reportingOwnerId>
  <reportingOwnerRelationship><isOfficer>true</isOfficer><officerTitle>CEO</officerTitle></reportingOwnerRelationship></reportingOwner>
  <nonDerivativeTable><nonDerivativeTransaction>
    <transactionDate><value>2024-03-15</value></transactionDate>
    <transactionCoding><transactionFormType>4</transactionFormType><transactionCode>P</transactionCode></transactionCoding>
    <transactionAmounts><transactionShares><value>1000</value></transactionShares>
    <transactionPricePerShare><value>10.0</value></transactionPricePerShare>
    <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode></transactionAmounts>
  </nonDerivativeTransaction></nonDerivativeTable>
</ownershipDocument>"""


def _signals_with_cache(monkeypatch, stamps):
    """stamps: fecha cacheada por accession (None = descarga fresca)."""
    from app.services import insider_service
    from app.services.connectors import form4 as form4_connector

    monkeypatch.setattr(insider_service, "_cik_for_ticker", lambda ticker, client=None: "0001234567")
    filings = [{"form": "4", "accession_number": f"0001-24-{i:06d}", "filing_date": "2024-03-16",
                "document_url": f"https://sec.gov/f{i}.xml"} for i in range(len(stamps))]
    monkeypatch.setattr(form4_connector, "recent_form4_filings", lambda cik, limit=20, client=None: filings)
    monkeypatch.setattr(
        insider_service, "_cached_filing_xml",
        lambda filing, client=None: (_XML, stamps[int(filing["document_url"].split("/f")[1].split(".")[0])]))
    return insider_service.get_signals_for_ticker("ACME", db=None)


def test_xml_cacheado_conserva_su_fecha_no_finge_descarga(monkeypatch):
    """Regresion del Auditor: cache servido con fetched_at=now era frescura fabricada."""
    result = _signals_with_cache(monkeypatch, ["2026-11-10T08:00:00+00:00"])
    assert result["fetched_at"] == "2026-11-10T08:00:00+00:00"
    assert result["provenance"]["fetched_at"] == "2026-11-10T08:00:00+00:00"


def test_mezcla_cache_y_fresco_la_respuesta_es_tan_fresca_como_el_mas_viejo(monkeypatch):
    result = _signals_with_cache(monkeypatch, ["2026-11-10T08:00:00+00:00", None])
    assert result["fetched_at"] == "2026-11-10T08:00:00+00:00"  # politica: min
    result2 = _signals_with_cache(monkeypatch, [None, None])
    assert result2["fetched_at"] is not None
    assert result2["fetched_at"] != "2026-11-10T08:00:00+00:00"


def test_sin_ningun_filing_legible_no_hay_fecha(monkeypatch):
    from app.services import insider_service
    from app.services.connectors import form4 as form4_connector

    monkeypatch.setattr(insider_service, "_cik_for_ticker", lambda ticker, client=None: "0001234567")
    monkeypatch.setattr(form4_connector, "recent_form4_filings", lambda cik, limit=20, client=None: [
        {"form": "4", "accession_number": "a", "filing_date": "2024-03-16", "document_url": "https://sec.gov/x.xml"}])
    monkeypatch.setattr(insider_service, "_cached_filing_xml",
                        lambda filing, client=None: (_ for _ in ()).throw(RuntimeError("sec caido")))
    result = insider_service.get_signals_for_ticker("ACME", db=None)
    assert result["fetched_at"] is None
    assert result["provenance"]["fetched_at"] is None
