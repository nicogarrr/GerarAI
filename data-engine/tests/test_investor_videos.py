from datetime import datetime

import httpx
import pytest

from app.services import investor_videos as service

CHANNEL = "UCyMGOTSE13Uf9Big_Ppj8Wg"
VIDEO = "abcdefghijk"

def feed(entry="", channel=CHANNEL):
    return f'''<feed xmlns="http://www.w3.org/2005/Atom" xmlns:yt="http://www.youtube.com/xml/schemas/2015"><yt:channelId>{channel}</yt:channelId><title>Archivo de referencia</title>{entry}</feed>'''.encode()


def entry(video=VIDEO, published="2026-10-01T10:00:00Z", channel=CHANNEL):
    return f'''<entry><yt:videoId>{video}</yt:videoId><yt:channelId>{channel}</yt:channelId><title>Titulo</title><published>{published}</published></entry>'''


def test_normalizes_source_date_and_explicit_archive():
    (video,) = service.parse_feed(feed(entry()), CHANNEL, "archive")
    assert video["video_id"] == VIDEO
    assert video["channel_name"] == "Archivo de referencia"
    assert video["channel_kind"] == "archive"
    assert video["channel_url"] == f"https://www.youtube.com/channel/{CHANNEL}"
    assert datetime.fromisoformat(video["published_at"]).tzinfo is not None


@pytest.mark.parametrize("bad", ["invalid", "../badvalue1", "abcdefghij!", "abcdefghijk2"])
def test_bad_video_ids_rejected(bad):
    assert service.parse_feed(feed(entry(video=bad)), CHANNEL, "archive") == []


@pytest.mark.parametrize("bad", ["invalid", "2026-10-01T10:00:00", "", "2026-99-01T00:00:00Z"])
def test_missing_invalid_or_naive_dates_rejected(bad):
    assert service.parse_feed(feed(entry(published=bad)), CHANNEL, "archive") == []


def test_channel_mismatch_and_xml_limits_fail_closed():
    assert service.parse_feed(feed(entry(), channel="another"), CHANNEL, "archive") == []
    assert service.parse_feed(feed(entry(channel="another")), CHANNEL, "archive") == []
    for xml in (b"broken", b"<!DOCTYPE feed><feed/>", b"<!ENTITY foo 'bar'><feed/>", b"x" * (service.MAX_BYTES + 1)):
        assert service.parse_feed(xml, CHANNEL, "archive") == []
    assert service.parse_feed(feed(entry()), "../invalid", "archive") == []


def test_dedupe_latest_six():
    xml = feed("".join(entry(video=f"abcdefghij{i}", published=f"2026-10-{i+1:02d}T10:00:00Z") for i in range(8)) + entry())
    rows = service.parse_feed(xml, CHANNEL, "archive")
    assert len(rows) == 6
    assert rows[0]["video_id"] == "abcdefghij7"


def test_unmapped_investor_never_fetches(monkeypatch):
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: pytest.fail("unexpected request"))
    assert service.investor_videos("munger") == []


def test_failure_cached_and_no_redirects(monkeypatch):
    service._CACHE.clear()
    calls = []
    class Client:
        def __init__(self, **kwargs):
            assert kwargs == {"timeout": 5.0, "follow_redirects": False}
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def stream(self, method, url, **kwargs):
            calls.append(url)
            assert kwargs["params"] == {"channel_id": CHANNEL}
            raise httpx.ConnectTimeout("blocked")
    monkeypatch.setattr(httpx, "Client", Client)
    assert service.investor_videos("buffett") == []
    assert service.investor_videos("buffett") == []
    assert len(calls) == 1
    service._CACHE.clear()


def test_detail_route_adds_videos_without_changing_identity(monkeypatch):
    from app.api.routes import investors
    detail = {"slug": "buffett", "cik": None}
    videos = service.parse_feed(feed(entry()), CHANNEL, "archive")
    monkeypatch.setattr(investors, "investor_detail", lambda db, slug: dict(detail))
    monkeypatch.setattr(investors, "investor_videos", lambda slug: videos, raising=False)
    out = investors.investor("buffett", db=None)
    assert out["slug"] == "buffett"
    assert out["videos"] == videos


def test_unknown_investor_remains_404(monkeypatch):
    from fastapi import HTTPException

    from app.api.routes import investors
    monkeypatch.setattr(investors, "investor_detail", lambda db, slug: None)
    with pytest.raises(HTTPException) as error:
        investors.investor("unknown", db=None)
    assert error.value.status_code == 404


@pytest.mark.parametrize("date", [
    "2026-10-01T10:00:00+02:60", "2026-10-01 10:00:00+02:00",
    "2026-10-01T10:00:00+24:00", "2026-10-01T10:00:00+0200",
])
def test_dates_never_repaired(date):
    assert service.parse_feed(feed(entry(published=date)), CHANNEL, "archive") == []


@pytest.mark.parametrize("encoding", ["utf-8", "utf-16", "utf-16-be", "utf-16-le"])
def test_dtd_entity_rejected_independent_of_encoding(encoding):
    xml = feed(entry()).decode().replace("<title>Titulo</title>", "<title>&fabricated;</title>")
    xml = '<!DOCTYPE feed [<!ENTITY fabricated "Fabricated title">]>' + xml
    assert service.parse_feed(xml.encode(encoding), CHANNEL, "archive") == []


def test_non_utf8_declaration_rejected():
    xml = b'<?xml version="1.0" encoding="UTF-16"?>' + feed(entry())
    assert service.parse_feed(xml, CHANNEL, "archive") == []


def test_published_at_shared_frontend_contract_preserves_microseconds():
    import json
    from pathlib import Path
    cases = json.loads((Path(__file__).resolve().parents[2] / "scripts/investor-video-timestamp-contract.json").read_text())
    for case in cases:
        (video,) = service.parse_feed(feed(entry(published=case["input"])), CHANNEL, "archive")
        assert video["published_at"] == case["output"]
        assert datetime.fromisoformat(case["output"]) == datetime.fromisoformat(case["input"].replace("Z", "+00:00"))
    # Python datetime only supports microseconds: never silently truncate finer input.
    assert service.parse_feed(feed(entry(published="2026-10-01T10:00:00.1234567Z")), CHANNEL, "archive") == []


def test_feed_level_channel_id_without_uc_prefix_accepted():
    # YouTube sirve a veces el channelId del feed sin el prefijo "UC".
    xml = feed(entry(), channel=CHANNEL.removeprefix("UC"))
    (video,) = service.parse_feed(xml, CHANNEL, "archive")
    assert video["video_id"] == VIDEO


def test_feed_level_channel_id_mismatch_still_rejected():
    assert service.parse_feed(feed(entry(), channel="UCotrocanal0000000000"), CHANNEL, "archive") == []
    assert service.parse_feed(feed(entry(), channel="otrocanal"), CHANNEL, "archive") == []


@pytest.mark.parametrize("junk", ["🎥", "🔴 🔵", "…", ""])
def test_titles_without_letters_or_digits_rejected(junk):
    xml = feed(entry().replace("<title>Titulo</title>", f"<title>{junk}</title>"))
    assert service.parse_feed(xml, CHANNEL, "archive") == []


@pytest.mark.parametrize("good", ["Terry Smith on short-term trading #fundsmith", "A", "2026 outlook"])
def test_titles_with_letters_or_digits_kept(good):
    xml = feed(entry().replace("<title>Titulo</title>", f"<title>{good}</title>"))
    (video,) = service.parse_feed(xml, CHANNEL, "archive")
    assert video["title"] == good


def test_confirmed_channels_mapped():
    assert service.CHANNELS["pabrai"] == ("UCw-OcYmKtk7ut-Ay7hIBaWg", "personal_confirmed")
    assert service.CHANNELS["terry-smith"] == ("UCEW0yRVs0CbqT9CrP8i3mSQ", "firm_confirmed")


def test_firm_confirmed_kind_accepted():
    (video,) = service.parse_feed(feed(entry()), CHANNEL, "firm_confirmed")
    assert video["channel_kind"] == "firm_confirmed"
