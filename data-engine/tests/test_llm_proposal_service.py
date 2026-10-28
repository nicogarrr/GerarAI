import asyncio
import json
from datetime import UTC, datetime

import pytest

from app.llm import LLMResponse, Message, Usage
from app.services import llm_output_guard as g
from app.services import llm_proposal_service as svc

NOW = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
QUOTE = {"live_c": 100.0, "live_t": NOW.timestamp() - 60, "currency": "USD"}
HEADLINES = [
    {
        "id": "news:1",
        "title": "Contrato nuevo con cliente grande",
        "published_at": "2026-10-08",
        "source": "Reuters",
    }
]


def _good(**over):
    base = {
        "direction": "long",
        "horizon": "short",
        "thesis": "El contrato nuevo mejora la visibilidad de ingresos del proximo trimestre.",
        "conviction": 0.6,
        "entry": 99.0,
        "stop": 92.0,
        "target": 115.0,
        "evidence_ids": ["news:1"],
        "inference_basis": "Inferencia mia: el contrato se traduce en ingresos recurrentes.",
    }
    base.update(over)
    return base


class P:
    name = "stub"

    def __init__(self, *outs):
        self.outs = list(outs)
        self.calls = 0

    async def complete(self, request):
        self.calls += 1
        out = self.outs.pop(0)
        text = out if isinstance(out, str) else json.dumps(out)
        return LLMResponse(Message("assistant", text), Usage(10, 10, 20), "m", "p")


def run(provider, **kw):
    args = {"quote": QUOTE, "headlines": HEADLINES, "now": NOW}
    args.update(kw)
    return asyncio.run(svc.propose(provider, "AAPL", **args))


@pytest.fixture(autouse=True)
def _reset():
    g.reset_guard_stats()


def test_valid_proposal_is_built_with_fixed_notional():
    p = run(P(_good()))
    assert p.ticker == "AAPL" and p.direction == "long"
    assert p.proposal_key.startswith("llm:AAPL:20261008:")
    assert round(p.quantity * p.proposed_entry) == 1000
    assert "news:1" in p.inference_basis


@pytest.mark.parametrize(
    "quote,reason",
    [
        (None, "sin_cotizacion"),
        ({"live_c": 100, "live_t": NOW.timestamp() - 90000, "currency": "USD"}, "cotizacion_vieja"),
        ({"live_c": 100, "live_t": None, "currency": "USD"}, "cotizacion_sin_fecha"),
        ({"live_c": 100, "live_t": NOW.timestamp(), "currency": None}, "cotizacion_invalida"),
    ],
)
def test_no_fresh_quote_fails_closed_without_calling_the_model(quote, reason):
    p = P(_good())
    with pytest.raises(svc.ProposalRejected) as exc:
        run(p, quote=quote)
    assert exc.value.reason == reason and p.calls == 0


def test_no_headlines_fails_closed():
    with pytest.raises(svc.ProposalRejected) as exc:
        run(P(_good()), headlines=[])
    assert exc.value.reason == "sin_titulares"


@pytest.mark.parametrize(
    "over,reason",
    [
        ({"evidence_ids": ["news:99"]}, "evidencia_no_recibida"),
        ({"evidence_ids": []}, "evidencia_no_recibida"),
        ({"conviction": 0}, "sin_conviccion"),
        ({"entry": 130.0, "stop": 120.0, "target": 150.0}, "entrada_lejos_de_cotizacion"),
        ({"stop": 105.0}, "niveles_invalidos"),
        ({"direction": "up"}, "niveles_invalidos"),
    ],
)
def test_invalid_model_output_is_rejected(over, reason):
    with pytest.raises(svc.ProposalRejected) as exc:
        run(P(_good(**over)))
    assert exc.value.reason == reason


def test_non_json_is_rejected():
    with pytest.raises(svc.ProposalRejected) as exc:
        run(P("lo siento, no puedo"))
    assert exc.value.reason == "json_invalido"


def test_cjk_output_retries_then_succeeds():
    bad = _good(thesis="El contrato nuevo mejora la visibilidad 문화 de ingresos.")
    p = P(bad, _good())
    out = run(p)
    assert p.calls == 2 and out.ticker == "AAPL"


def test_double_guard_rejection_is_a_rejected_proposal():
    bad = _good(thesis="El contrato nuevo mejora la visibilidad 문화 de ingresos.")
    p = P(bad, bad)
    with pytest.raises(svc.ProposalRejected) as exc:
        run(p)
    assert exc.value.reason.startswith("salida_rechazada:cjk") and p.calls == 2


def test_proposal_is_accepted_by_the_paper_ledger():
    from app.services.paper_trading_service import create_proposal

    class DB:
        def __init__(self):
            self.added = []

        def scalar(self, *_a, **_k):
            return None

        def add(self, row):
            self.added.append(row)

        def commit(self):
            pass

        def refresh(self, row):
            pass

    db = DB()
    row = create_proposal(db, run(P(_good())))
    assert db.added and row.ticker == "AAPL" and row.status in {None, "pending"}


@pytest.mark.parametrize(
    "over",
    [
        {"inference_basis": ""},
        {"inference_basis": "   "},
        {"inference_basis": None},
        {"entry": "NaN"},
        {"conviction": "NaN"},
        {"stop": "Infinity"},
        {"target": "NaN"},
        {"entry": True},
        {"evidence_ids": [{}]},
        {"evidence_ids": [["news:1"]]},
        {"thesis": None},
    ],
)
def test_malformed_fields_are_rejected_not_raised(over):
    with pytest.raises(svc.ProposalRejected):
        run(P(_good(**over)))


def test_missing_inference_basis_key_is_rejected():
    raw = _good()
    del raw["inference_basis"]
    with pytest.raises(svc.ProposalRejected, match="sin_base_de_inferencia"):
        run(P(raw))


def test_proposal_keeps_quote_currency_and_ledger_rejects_other_currency():
    from decimal import Decimal
    from types import SimpleNamespace

    from app.services import paper_trading_service as ledger

    proposal = run(P(_good()))
    assert proposal.currency == "USD"
    created = NOW.replace(minute=15)

    def row():
        return SimpleNamespace(
            **{**proposal.model_dump(), "ticker": "AAPL", "status": "pending", "created_at": NOW,
               "mark_at": None, "entry_price": None, "entry_at": None, "mark_price": None,
               "entry_fee": None,
               "exit_price": None, "exit_at": None, "close_reason": None, "price_source": None}
        )

    later = NOW.timestamp() + 600
    eur, usd = row(), row()
    assert ledger.apply_quote(eur, {"live_c": 98.0, "live_t": later, "currency": "EUR"}, created) is False
    assert eur.status == "pending" and eur.entry_price is None
    assert ledger.apply_quote(usd, {"live_c": 98.0, "live_t": later, "currency": "USD"}, created) is True
    assert usd.status == "open" and usd.entry_price == Decimal("98.0") and usd.currency == "USD"
