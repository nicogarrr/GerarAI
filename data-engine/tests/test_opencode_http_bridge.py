"""Offline bridge transport canaries: no model, credentials or production traffic."""
import importlib.util
from pathlib import Path
from unittest.mock import patch

import pytest

spec = importlib.util.spec_from_file_location("oc_bridge", Path(__file__).parents[1] / "bridge/opencode_bridge.py")
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)

_REAL_STATUS_PROBE = bridge._StatusProbe


@pytest.fixture(autouse=True)
def deterministic_status_probe(request):
    if request.node.name.startswith(("test_http_", "test_slow_status_")):
        yield
        return
    class Probe:
        def __init__(self, sid): self.sid = sid
        def start(self): pass
        def close(self): pass
        def latest(self):
            try:
                statuses = bridge.serve_req("GET", "/session/status", timeout=2)
                return statuses.get(self.sid) if isinstance(statuses, dict) else None
            except (TimeoutError, ValueError):
                return None
    with patch.object(bridge, "_StatusProbe", Probe), patch.object(bridge.time, "sleep"):
        yield


def run_with_responses(responses):
    calls = []
    def request(method, path, body=None, **kwargs):
        calls.append((method, path, body, kwargs))
        if path == "/session": return {"id": "synthetic"}
        if path.endswith("prompt_async"): return None
        if path.endswith("abort") or method == "DELETE": return None
        if path == "/session/status": return responses.get("status", {})
        return responses["messages"].pop(0) if responses["messages"] else []
    return calls, request

def test_async_empty_response_and_latest_poll_only():
    pending = [{"info": {"role": "assistant"}, "parts": [{"type": "text", "text": "part"}]}]
    done = [{"info": {"role": "assistant", "finish": "stop"}, "parts": [{"type": "text", "text": "whole"}]}]
    calls, request = run_with_responses({"messages": [pending, done]})
    with patch.object(bridge, "serve_req", request), patch.object(bridge.time, "sleep"):
        assert bridge.complete("fixture-free", [{"role": "user", "content": "test"}]) == "whole"
    assert calls[0][2] == {"title": "GerarAI chat"}
    assert any(path.endswith("prompt_async") for _, path, _, _ in calls)
    assert calls[-2][1].endswith("abort") and calls[-1][0] == "DELETE"

def test_valid_primary_at_44_seconds_is_not_aborted():
    done = [{"info": {"role": "assistant", "finish": "stop"}, "parts": [{"type": "text", "text": "valid primary"}]}]
    calls, request = run_with_responses({"messages": [done]})
    with patch.object(bridge, "serve_req", request), patch.object(bridge.time, "monotonic", side_effect=[0, 44]):
        assert bridge.complete("fixture-free", [{"role": "user", "content": "test"}]) == "valid primary"
    assert calls[-1][0] == "DELETE"

def test_provider_error_aborts_and_cleans_up():
    calls, request = run_with_responses({"messages": [[{"info": {"role": "assistant", "error": {"name": "APIError"}}, "parts": []}]]})
    with patch.object(bridge, "serve_req", request):
        with pytest.raises(RuntimeError, match="serve error"): bridge.complete("fixture-free", [{"role": "user", "content": "test"}])
    assert calls[-2][1].endswith("abort") and calls[-1][0] == "DELETE"


def test_deadline_cancels_without_synchronous_message_call():
    calls, request = run_with_responses({"messages": []})
    with patch.object(bridge, "serve_req", request), patch.object(bridge.time, "monotonic", side_effect=[0, 151]):
        with pytest.raises(TimeoutError): bridge.complete("fixture-free", [{"role": "user", "content": "test"}])
    assert calls[-2][1].endswith("abort") and calls[-1][0] == "DELETE"
    assert not any(path.endswith("/message") and method == "POST" for method, path, _, _ in calls)


def test_explicit_free_limit_aborts_then_cached_model_does_not_create_session():
    bridge._free_retry_at.clear()
    state = {"synthetic": {"type": "retry", "action": {"reason": "free_tier_limit"}, "next": 2000000}}
    calls, request = run_with_responses({"status": state, "messages": []})
    with patch.object(bridge, "serve_req", request), patch.object(bridge.time, "time", return_value=1000):
        with pytest.raises(bridge.FreeTierLimitError): bridge.complete("fixture-free", [{"role": "user", "content": "test"}])
        before = len(calls)
        with pytest.raises(bridge.FreeTierLimitError): bridge.complete("fixture-free", [{"role": "user", "content": "test"}])
        assert len(calls) == before
    assert calls[-2][1].endswith("abort") and calls[-1][0] == "DELETE"
    bridge._free_retry_at.clear()


def test_transient_retry_without_explicit_free_limit_keeps_valid_primary():
    done = [{"info": {"role": "assistant", "finish": "stop"}, "parts": [{"type": "text", "text": "valid"}]}]
    calls, request = run_with_responses({"status": {"synthetic": {"type": "retry", "message": "temporary busy"}}, "messages": [[], done]})
    with patch.object(bridge, "serve_req", request):
        assert bridge.complete("fixture-free", [{"role": "user", "content": "test"}]) == "valid"


def test_http_replay_of_observed_free_limit_returns_429_then_no_new_session():
    import json
    import threading
    import time
    import urllib.error
    import urllib.request
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    counts = {"sessions": 0, "prompts": 0}
    class Replay(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def respond(self, code, data=None):
            raw = json.dumps(data).encode() if data is not None else b""
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            if self.path == "/session":
                counts["sessions"] += 1
                return self.respond(200, {"id": "synthetic"})
            if self.path.endswith("prompt_async"):
                counts["prompts"] += 1
            self.respond(204)
        def do_GET(self):
            if self.path.endswith("/message"):
                return self.respond(200, [])
            self.respond(200, {"synthetic": {"type": "retry", "message": "Free usage exceeded, subscribe to Go", "action": {"reason": "free_tier_limit"}, "next": int((time.time() + 3600) * 1000)}})
        def do_DELETE(self):
            self.respond(200, True)
    fake = ThreadingHTTPServer(("127.0.0.1", 0), Replay)
    api = ThreadingHTTPServer(("127.0.0.1", 0), bridge.Handler)
    bridge._free_retry_at.clear()
    threads = [threading.Thread(target=server.serve_forever, daemon=True) for server in (fake, api)]
    for thread in threads: thread.start()
    try:
        with patch.object(bridge, "SERVE_URL", f"http://127.0.0.1:{fake.server_port}"), patch.object(bridge, "POLL_S", 0.01):
            for _ in range(2):
                start = time.monotonic()
                request = urllib.request.Request(f"http://127.0.0.1:{api.server_port}/v1/chat/completions", data=json.dumps({"model": "fixture-free", "messages": [{"role": "user", "content": "test"}]}).encode(), headers={"Content-Type": "application/json"})
                with pytest.raises(urllib.error.HTTPError) as failure:
                    urllib.request.urlopen(request, timeout=3)
                assert failure.value.code == 429
                body = json.loads(failure.value.read())
                assert body["error"]["type"] == "FreeTierLimitError"
                assert "subscribe" not in body["error"]["message"]
                assert time.monotonic() - start < 2
        assert counts == {"sessions": 1, "prompts": 1}
    finally:
        for server in (fake, api): server.shutdown(); server.server_close()
        for thread in threads: thread.join(timeout=2)
        bridge._free_retry_at.clear()


@pytest.mark.parametrize("status", [None, [], {"synthetic": None}, {"synthetic": {"type": "retry", "action": "invalid"}}])
def test_malformed_status_does_not_discard_valid_primary(status):
    done = [{"info": {"role": "assistant", "finish": "stop"}, "parts": [{"type": "text", "text": "valid"}]}]
    _, request = run_with_responses({"status": status, "messages": [[], done]})
    with patch.object(bridge, "serve_req", request):
        assert bridge.complete("fixture-free", [{"role": "user", "content": "test"}]) == "valid"


def test_status_transport_failure_does_not_discard_valid_primary():
    done = [{"info": {"role": "assistant", "finish": "stop"}, "parts": [{"type": "text", "text": "valid"}]}]
    _, original = run_with_responses({"messages": [[], done]})
    def request(method, path, body=None, **kwargs):
        if path == "/session/status": raise TimeoutError("offline fixture")
        return original(method, path, body, **kwargs)
    with patch.object(bridge, "serve_req", request):
        assert bridge.complete("fixture-free", [{"role": "user", "content": "test"}]) == "valid"


@pytest.mark.parametrize("next_ms", [None, True, "2000000", -1, float("nan"), float("inf"), 99999999999999999999])
def test_invalid_next_is_not_cached(next_ms):
    bridge._free_retry_at.clear()
    state = {"synthetic": {"type": "retry", "action": {"reason": "free_tier_limit"}, "next": next_ms}}
    _, request = run_with_responses({"status": state, "messages": []})
    with patch.object(bridge, "serve_req", request), patch.object(bridge.time, "time", return_value=1000):
        with pytest.raises(bridge.FreeTierLimitError): bridge.complete("fixture-free", [{"role": "user", "content": "test"}])
    assert bridge._free_retry_at == {}


def test_expired_cache_and_other_model_can_create_session():
    bridge._free_retry_at.clear()
    bridge._free_retry_at.update({"expired-free": 999, "limited-free": 2000})
    for model in ["expired-free", "other-free"]:
        done = [{"info": {"role": "assistant", "finish": "stop"}, "parts": [{"type": "text", "text": "valid"}]}]
        calls, request = run_with_responses({"messages": [done]})
        with patch.object(bridge, "serve_req", request), patch.object(bridge.time, "time", return_value=1000):
            assert bridge.complete(model, [{"role": "user", "content": "test"}]) == "valid"
        assert calls[0][1] == "/session"
    bridge._free_retry_at.clear()


def test_slow_status_cannot_consume_remaining_backend_45_second_deadline():
    import asyncio
    import threading
    import time

    status_started = threading.Event()
    release_status = threading.Event()
    # The backend's 45-second budget has already spent 43 seconds in prompt.
    # Use a virtual offset instead of sleeping 43 seconds on every CI run.
    backend_budget = 45
    spent_in_prompt = 43
    start = time.monotonic()
    calls = []
    def request(method, path, body=None, **kwargs):
        calls.append(path)
        if path == "/session": return {"id": "slow-status"}
        if path.endswith("prompt_async"): return None
        if path == "/session/status":
            status_started.set()
            release_status.wait(timeout=2)
            return {}
        if path.endswith("/message"):
            assert status_started.wait(timeout=0.2)
            time.sleep(1)  # primary completes at virtual t44, status still blocked
            return [{"info": {"role": "assistant", "finish": "stop"}, "parts": [{"type": "text", "text": "valid at t44"}]}]
        return None
    async def backend():
        return await asyncio.wait_for(asyncio.to_thread(bridge.complete, "slow-status-model", [{"role": "user", "content": "test"}]), timeout=backend_budget - spent_in_prompt)
    try:
        with patch.object(bridge, "serve_req", request), patch.object(bridge, "_StatusProbe", _REAL_STATUS_PROBE):
            assert asyncio.run(backend()) == "valid at t44"
        assert time.monotonic() - start < backend_budget - spent_in_prompt
        assert not release_status.is_set()
        assert calls[-2:] == ["/session/slow-status/abort", "/session/slow-status"]
    finally:
        release_status.set()


def test_completed_primary_wins_even_if_free_limit_status_is_already_present():
    done = [{"info": {"role": "assistant", "finish": "stop"}, "parts": [{"type": "text", "text": "valid"}]}]
    state = {"synthetic": {"type": "retry", "action": {"reason": "free_tier_limit"}, "next": 2000000}}
    calls, request = run_with_responses({"status": state, "messages": [done]})
    with patch.object(bridge, "serve_req", request):
        assert bridge.complete("fixture-free", [{"role": "user", "content": "test"}]) == "valid"
    assert not any(path == "/session/status" for _, path, _, _ in calls)
