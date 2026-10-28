"""Cliente Flex de IBKR: ningún error ni mensaje puede contener el token, el
sondeo reintenta solo los códigos transitorios y se rinde con motivo claro.

Run from data-engine/:
    pytest tests/test_ibkr_flex_client.py -v
"""

import asyncio

import httpx
import pytest

from app.services.connectors import ibkr as ibkr_module
from app.services.connectors.ibkr import IBKRFlexClient, IBKRFlexError

TOKEN = "SUPERSECRETTOKEN"


def _ok(ref="REF123"):
    return f"<FlexStatementResponse><Status>Success</Status><ReferenceCode>{ref}</ReferenceCode></FlexStatementResponse>"


def _fail(code, msg="Server said token SUPERSECRETTOKEN is bad"):
    return (f"<FlexStatementResponse><Status>Fail</Status><ErrorCode>{code}</ErrorCode>"
            f"<ErrorMessage>{msg}</ErrorMessage></FlexStatementResponse>")


STATEMENT = "<FlexQueryResponse><FlexStatements/></FlexQueryResponse>"


@pytest.fixture()
def http(monkeypatch):
    """Sustituye httpx.AsyncClient por uno con transporte simulado."""
    state = {"responses": [], "requests": []}
    real = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        state["requests"].append(request)
        item = state["responses"].pop(0)
        if isinstance(item, Exception):
            raise item
        status, text = item
        return httpx.Response(status, text=text, request=request)

    monkeypatch.setattr(ibkr_module.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))

    async def no_sleep(_):
        return None

    monkeypatch.setattr(ibkr_module.asyncio, "sleep", no_sleep)
    return state


def _client():
    return IBKRFlexClient(token=TOKEN, query_id="Q1")


def run(coro):
    return asyncio.run(coro)


def test_explicit_credentials_never_fall_back_to_global_settings():
    c = IBKRFlexClient(token="", query_id="")
    assert c.configured() is False
    with pytest.raises(RuntimeError, match="not configured"):
        run(c.request_statement())
    with pytest.raises(RuntimeError, match="not configured"):
        run(c.fetch_statement("X"))


def test_request_returns_reference_and_sends_range_params(http):
    http["responses"].append((200, _ok("R9")))
    assert run(_client().request_statement("20250101", "20251231")) == "R9"
    q = http["requests"][0].url.params
    assert q["fd"] == "20250101" and q["td"] == "20251231" and q["q"] == "Q1" and q["v"] == "3"


def test_request_without_range_omits_dates(http):
    http["responses"].append((200, _ok()))
    run(_client().request_statement())
    assert "fd" not in http["requests"][0].url.params


@pytest.mark.parametrize("fd,td", [("20250101", None), (None, "20251231")])
def test_half_open_range_is_rejected_before_any_request(http, fd, td):
    with pytest.raises(IBKRFlexError, match="both from_date and to_date"):
        run(_client().request_statement(fd, td))
    assert http["requests"] == []


def test_failed_request_exposes_only_numeric_code_not_server_text(http):
    http["responses"].append((200, _fail("1012")))
    with pytest.raises(IBKRFlexError) as exc:
        run(_client().request_statement())
    assert "1012" in str(exc.value) and TOKEN not in str(exc.value)
    http["responses"].append((200, _fail("evil " + TOKEN)))
    with pytest.raises(IBKRFlexError) as exc2:
        run(_client().request_statement())
    assert "n/d" in str(exc2.value) and TOKEN not in str(exc2.value)


def test_success_without_reference_code_fails(http):
    http["responses"].append((200, "<FlexStatementResponse><Status>Success</Status></FlexStatementResponse>"))
    with pytest.raises(IBKRFlexError, match="ReferenceCode"):
        run(_client().request_statement())


def test_http_status_and_network_errors_do_not_leak_url_or_token(http):
    http["responses"].append((503, "down"))
    with pytest.raises(IBKRFlexError) as e1:
        run(_client().request_statement())
    assert "503" in str(e1.value) and TOKEN not in str(e1.value) and e1.value.__cause__ is None
    http["responses"].append(httpx.ConnectError("boom " + TOKEN))
    with pytest.raises(IBKRFlexError) as e2:
        run(_client().request_statement())
    assert "ConnectError" in str(e2.value) and TOKEN not in str(e2.value)


def test_fetch_statement_retries_transient_codes_then_returns_xml(http):
    http["responses"] += [(200, _fail("1019")), (200, _fail("1001")), (200, STATEMENT)]
    assert run(_client().fetch_statement("REF")) == STATEMENT
    assert len(http["requests"]) == 3
    assert http["requests"][0].url.params["q"] == "REF"


def test_fetch_statement_gives_up_after_poll_attempts(http):
    http["responses"] += [(200, _fail("1019"))] * 6
    with pytest.raises(IBKRFlexError, match=r"not ready \(code 1019\)"):
        run(_client().fetch_statement("REF"))
    assert len(http["requests"]) == 6


def test_fetch_statement_does_not_retry_permanent_errors(http):
    http["responses"].append((200, _fail("1003")))
    with pytest.raises(IBKRFlexError, match=r"failed \(code 1003\)"):
        run(_client().fetch_statement("REF"))
    assert len(http["requests"]) == 1


def test_range_and_latest_chain_request_then_fetch(http):
    http["responses"] += [(200, _ok("RR")), (200, STATEMENT)]
    assert run(_client().fetch_range_xml("20250101", "20250131")) == STATEMENT
    assert http["requests"][1].url.params["q"] == "RR"
    http["responses"] += [(200, _ok("RL")), (200, STATEMENT)]
    assert run(_client().fetch_latest_xml()) == STATEMENT
    assert http["requests"][3].url.params["q"] == "RL"


def test_status_of_non_xml_is_all_none():
    assert IBKRFlexClient._status("<<not xml") == (None, None, None)
    assert IBKRFlexClient._status(_fail("1019"))[:2] == ("Fail", "1019")
