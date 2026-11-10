"""Video feed streaming cap and cache-copy behavior without YouTube requests."""

from contextlib import contextmanager

import httpx
import pytest

from app.services import investor_videos as service
from tests.test_investor_videos import CHANNEL, entry, feed


@pytest.mark.parametrize("content", [b"<not-a-feed/>", feed(entry()).replace(b"Archivo de referencia", b" ")])
def test_wrong_root_or_empty_channel_title_has_no_videos(content):
    assert service.parse_feed(content, CHANNEL, "archive") == []


def test_invalid_mapped_channel_does_not_open_client(monkeypatch):
    monkeypatch.setitem(service.CHANNELS, "test-invalid", ("bad", "archive"))
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: pytest.fail("invalid channel must not fetch"))
    assert service.investor_videos("test-invalid") == []


def test_success_cache_returns_copies_and_refreshes_at_expiry(monkeypatch):
    monkeypatch.setattr(service, "_CACHE", {})
    clock = [100.0]
    calls = []
    monkeypatch.setattr(service.time, "monotonic", lambda: clock[0])

    class Client:
        def __init__(self, **kwargs):
            assert kwargs == {"timeout": 5.0, "follow_redirects": False}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        @contextmanager
        def stream(self, method, url, **kwargs):
            calls.append((method, url, kwargs))
            response = httpx.Response(200, content=feed(entry()), request=httpx.Request(method, url))
            try:
                yield response
            finally:
                response.close()

    monkeypatch.setattr(httpx, "Client", Client)
    first = service.investor_videos("buffett")
    assert first[0]["video_id"] == "abcdefghijk"
    first[0]["title"] = "changed by consumer"
    clock[0] += service.TTL_SECONDS - 1
    second = service.investor_videos("buffett")
    assert second[0]["title"] == "Titulo" and len(calls) == 1
    second.clear()
    assert service.investor_videos("buffett")[0]["title"] == "Titulo"
    clock[0] += 1
    assert service.investor_videos("buffett")[0]["title"] == "Titulo" and len(calls) == 2
    assert calls[0][2] == {"params": {"channel_id": CHANNEL}}


def test_oversized_stream_stops_after_cap_closes_and_caches_empty(monkeypatch):
    monkeypatch.setattr(service, "_CACHE", {})
    events = []

    class Chunks(httpx.SyncByteStream):
        def __iter__(self):
            events.append("read")
            yield b"x" * (service.MAX_BYTES + 1)
            raise AssertionError("must not read beyond oversized first chunk")

        def close(self):
            events.append("close")

    class Client:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        @contextmanager
        def stream(self, method, url, **kwargs):
            response = httpx.Response(200, stream=Chunks(), request=httpx.Request(method, url))
            try:
                yield response
            finally:
                response.close()

    monkeypatch.setattr(httpx, "Client", Client)
    assert service.investor_videos("buffett") == []
    assert service.investor_videos("buffett") == []
    assert events == ["read", "close"]
