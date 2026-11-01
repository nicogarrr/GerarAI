import asyncio
import json
from datetime import UTC, date, datetime
from decimal import Decimal

from app.llm import LLMResponse, Message, Usage
from app.models import MarketPrice
from app.models.propick_review import PropickReview
from app.services.propicks_review_service import (
    NO_REVIEW,
    ReviewCandidate,
    brier_report,
    evaluate_outcomes,
    log_reviews,
    review_shortlist,
)
from tests.test_propicks_funnel import _company, _db


def _cand(t="AAA"):
    return ReviewCandidate(
        t, f"{t} Co", 72.5,
        [
            {"key": "fcf_yield", "value": 0.1234, "source": "SEC FY2025 + precio 2026-10-16"},
            {"key": "net_debt_to_ebitda", "value": 1.2, "source": "Métricas calculadas"},
        ],
        price=10.0, price_date=date(2026, 7, 1),
    )


def _v(t="AAA", **over):
    base = {
        "ticker": t, "decision": "keep",
        "thesis": "Rendimiento de caja libre de 0.1234 con deuda baja segun los datos recibidos.",
        "risks": ["Depende de un solo cliente", "Margen presionado por costes"],
        "invalidation": "Un recorte del flujo de caja libre.",
        "confidence": 0.6, "evidence_keys": ["fcf_yield"],
    }
    return base | over


class P:
    name = "stub"

    def __init__(self, *outs):
        self.outs = list(outs)

    async def complete(self, request):
        out = self.outs.pop(0)
        text = out if isinstance(out, str) else json.dumps(out)
        return LLMResponse(Message("assistant", text), Usage(10, 10, 20), "m", "p")


def run(provider, cands):
    return asyncio.run(review_shortlist(provider, cands))


def test_valid_verdict_is_accepted():
    r = run(P({"verdicts": [_v()]}), [_cand()])[0]
    assert r.status == "reviewed" and r.decision == "keep" and r.confidence == 0.6


def test_model_cannot_add_names_outside_shortlist():
    out = run(P({"verdicts": [_v(), _v("ZZZ")]}), [_cand()])
    assert [r.ticker for r in out] == ["AAA"]


def test_invented_number_evidence_or_missing_risks_are_rejected():
    assert run(P({"verdicts": [_v(thesis="Crece un 87654 por ciento segun los datos recibidos.")]}), [_cand()])[0].reject_reason == "cifra_no_recibida"
    assert run(P({"verdicts": [_v(evidence_keys=["roic"])]}), [_cand()])[0].reject_reason == "evidencia_no_recibida"
    assert run(P({"verdicts": [_v(risks=["uno"])]}), [_cand()])[0].reject_reason == "riesgos_invalidos"
    assert run(P({"verdicts": [_v(decision="veto")]}), [_cand()])[0].reject_reason == "veto_sin_motivo"


def test_model_failure_degrades_to_sin_revision_ia():
    out = run(P("no es json", "tampoco"), [_cand()])
    assert out[0].status == NO_REVIEW


def test_brier_needs_resolved_outcomes_and_flags_small_samples():
    with _db() as db:
        c = _company("AAA")
        db.add(c)
        db.flush()
        db.add(MarketPrice(company_id=c.id, date=date(2026, 10, 1), close=Decimal("12"), volume=1))
        db.commit()
        reviews = run(P({"verdicts": [_v()]}), [_cand()])
        log_reviews(db, [_cand()], reviews, model="m", now=datetime(2026, 7, 1, tzinfo=UTC))
        assert brier_report(db) == {"n": 0, "enough": False}
        assert evaluate_outcomes(db, today=date(2026, 7, 10)) == 0  # too early
        assert evaluate_outcomes(db, today=date(2026, 10, 19)) == 1
        rep = brier_report(db)
        assert rep["n"] == 1 and rep["enough"] is False
        assert abs(rep["brier_llm"] - 0.16) < 1e-9  # (0.6 - 1)^2
        row = db.query(PropickReview).one()
        assert abs(row.outcome_return - 0.2) < 1e-9


def test_review_request_uses_registered_prompt_and_traces_it():
    from app.services import prompt_registry

    class Capturing(P):
        seen = []

        async def complete(self, request):
            self.seen.append(request)
            return await super().complete(request)

    run(Capturing({"verdicts": [_v()]}), [_cand()])
    resolved = prompt_registry.get_prompt("propicks_review_service", allow_remote=False)
    request = Capturing.seen[0]
    assert request.messages[0].content == resolved.text
    assert request.metadata == resolved.trace_metadata()


def test_outcome_ajusta_un_split_dentro_de_los_90_dias():
    """Split 4:1 tras la revision: el cierre sin ajustar cae de 10 a 3.

    Precio guardado 10 (2026-07-01); tras el split el adj_close de esa fecha es
    2,5. A los 90 dias cierra 3 (adj 3): +20 % real, no -70 %.
    """
    with _db() as db:
        c = _company("AAA")
        db.add(c)
        db.flush()
        for day, close, adj in [(date(2026, 7, 1), "10", "2.5"), (date(2026, 10, 1), "3", "3")]:
            db.add(MarketPrice(company_id=c.id, date=day, close=Decimal(close), adj_close=Decimal(adj), volume=1))
        db.commit()
        reviews = run(P({"verdicts": [_v()]}), [_cand()])
        log_reviews(db, [_cand()], reviews, model="m", now=datetime(2026, 7, 1, tzinfo=UTC))
        assert evaluate_outcomes(db, today=date(2026, 10, 19)) == 1
        row = db.query(PropickReview).one()
        assert abs(row.outcome_return - 0.2) < 1e-9
        assert brier_report(db)["mean_return_kept"] == 0.2
