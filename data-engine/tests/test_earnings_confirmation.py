"""La ausencia del flag Yahoo no confirma una fecha de resultados."""
from datetime import UTC, datetime

import httpx
import pytest

from app.services import earnings_dates_service as svc


@pytest.mark.parametrize("flag", [None, "missing", "false", 0, 1, False, True])
@pytest.mark.parametrize("nasdaq", [False, True])
def test_confirmacion_requiere_booleano_explicito(monkeypatch, flag, nasdaq):
    stamp = datetime(2026, 12, 20, 20, tzinfo=UTC)
    earnings = {"earningsDate": [{"raw": int(stamp.timestamp())}]}
    if flag != "missing":
        earnings["isEarningsDateEstimate"] = flag
    payload = {"quoteSummary": {"result": [{"calendarEvents": {"earnings": earnings}}]}}
    client = httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload)))
    monkeypatch.setattr(svc, "_yahoo_session", lambda: (client, "crumb"))
    monkeypatch.setattr(svc, "YAHOO_PAUSE_S", 0)
    yahoo = svc.fetch_yahoo_dates({"ABC": "ABC"})["ABC"]
    other = {"date": yahoo["date"], "session": None, "fiscal": None} if nasdaq else None
    candidate = svc.merge_candidate(yahoo, other)
    expected = not flag if type(flag) is bool else None
    assert candidate["confirmed"] is expected
    assert yahoo["estimate"] is (flag if type(flag) is bool else None)


def test_desacuerdo_sigue_sin_confirmar():
    yahoo = {"date": datetime(2026, 12, 20).date(), "estimate": False}
    nasdaq = {"date": datetime(2026, 12, 21).date()}
    assert svc.merge_candidate(yahoo, nasdaq)["confirmed"] is False
