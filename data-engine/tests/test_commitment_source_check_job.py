"""Job de comprobacion de fuentes: fetchers inyectados (sin red), almacen en tmp."""
import json
from datetime import date

import pytest

from app.services import commitment_primary_pipeline as pp
from app.services.commitment_source_check_job import (
    JsonSourceCheckStore,
    check_financial_assets,
    run_job,
)
from tests.test_commitment_financial_release import ASSET, HEADER_ROW, ROW, _html
from tests.test_commitment_primary_ops import OK, URL

TODAY = date(2026, 10, 22)


def _fake_transcripts(ticker, url, *, today):
    from tests.test_commitment_primary_pipeline import _doc

    return _doc(), {"cache_hit": False, "previous_bytes_sha256": None, "bytes_changed": None}


def test_financial_extraction_is_recorded_with_labels_and_no_full_text():
    [rec] = check_financial_assets(today=TODAY, fetch_html=lambda url: _html())
    assert rec.outcome == "extraido" and rec.kind == "press_release" and rec.independent is False
    assert rec.provenance == "emisor_reportado" and len(rec.content_sha256) == 64
    kinds = {f["metric"]: f["adjusted"] for f in rec.facts}
    assert kinds["gross_bookings_growth_yoy_constant_currency"] is True
    assert kinds["gross_bookings_growth_yoy_reported"] is False
    assert "html" not in json.dumps(rec.facts).lower()


def test_abstention_and_error_are_recorded_with_reason():
    [ab] = check_financial_assets(today=TODAY, fetch_html=lambda url: _html(rows=ROW))
    assert (ab.outcome, ab.facts) == ("abstencion", ()) and ab.reason
    def boom(url):
        raise TimeoutError("x")
    [er] = check_financial_assets(today=TODAY, fetch_html=boom)
    assert (er.outcome, er.reason) == ("error", "TimeoutError")


def test_job_stores_last_check_and_flags_content_change(tmp_path):
    store = JsonSourceCheckStore(tmp_path / "checks.json")
    run_job(store, today=TODAY, fetch_html=lambda url: _html(rows=HEADER_ROW + ROW),
            fetch=_fake_transcripts)
    first = store.load()[ASSET.url]
    assert first["content_changed"] is None and first["checked_on"] == "2026-10-22"
    changed = ROW.replace("46,756", "46,757")
    run_job(store, today=date(2026, 10, 23), fetch_html=lambda url: _html(rows=HEADER_ROW + changed),
            fetch=_fake_transcripts)
    second = store.load()[ASSET.url]
    assert second["content_changed"] is True and second["checked_on"] == "2026-10-23"
    assert second["previous_content_sha256"] == first["content_sha256"]
    assert second["note"].startswith("contraste_documental")


def test_transcript_check_failure_is_an_abstention_not_a_crash(tmp_path):
    def refuse(ticker, url, *, today):
        raise pp.PrimarySourceError("Tiempo total excedido al obtener la fuente")
    store = JsonSourceCheckStore(tmp_path / "c.json")
    recs = run_job(store, today=TODAY, fetch_html=lambda u: _html(), fetch=refuse)
    tr = [r for r in recs if r.kind == "transcript"]
    assert tr and all(r.outcome == "abstencion" for r in tr)


@pytest.mark.parametrize("data", ["not json", "[1]"])
def test_corrupt_store_is_replaced_not_trusted(tmp_path, data):
    p = tmp_path / "c.json"
    p.write_text(data)
    assert JsonSourceCheckStore(p).load() == {}


def test_store_is_bounded(tmp_path):
    from app.services.commitment_source_check_job import MAX_RECORDS, SourceCheckRecord

    store = JsonSourceCheckStore(tmp_path / "c.json")
    recs = [SourceCheckRecord("T", f"https://x.example/{i}", "press_release", "Q1 2026",
                              "2026-10-22", "abstencion", "r") for i in range(MAX_RECORDS + 20)]
    assert len(store.save(recs)) == MAX_RECORDS
    _ = (OK, URL)
