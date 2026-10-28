"""LLM analyst review of the ProPicks shortlist.

The deterministic funnel and gem score choose the shortlist. The model only
reviews that package: it sees the data points handed to it (value, source,
date) and nothing else. It may keep or veto a pick and explain why; it can
never add a name. Output is validated; anything that does not pass is dropped
and the pick is shown as "sin revision IA". Every verdict is logged so the
model's confidence can be scored later (Brier) against the score alone.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.llm import LLMRequest, Message, ResponseFormat, parse_json_response
from app.models import MarketPrice
from app.models.propick_review import PropickReview
from app.services.llm_output_guard import LLMOutputRejected, complete_guarded
from app.services.prompt_registry import get_prompt

REVIEW_TASK = "main_financial_analysis"
BATCH = 8
OUTCOME_DAYS = 90
MIN_FOR_BRIER = 30
NO_REVIEW = "sin_revision_ia"

_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["verdicts"],
    "properties": {
        "verdicts": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["ticker", "decision", "thesis", "risks", "invalidation", "confidence", "evidence_keys"],
                "properties": {
                    "ticker": {"type": "string"},
                    "decision": {"type": "string", "enum": ["keep", "veto"]},
                    "thesis": {"type": "string"},
                    "risks": {"type": "array", "items": {"type": "string"}},
                    "invalidation": {"type": "string"},
                    "confidence": {"type": "number"},
                    "evidence_keys": {"type": "array", "items": {"type": "string"}},
                    "veto_reason": {"type": "string"},
                },
            },
        }
    },
}

_PROMPT = get_prompt("propicks_review_service", allow_remote=False)
SYSTEM = _PROMPT.text

_NUM = re.compile(r"\d[\d.,]*")


@dataclass
class ReviewCandidate:
    ticker: str
    name: str
    score: float
    data: list[dict]  # {key, value, source}
    price: float | None = None
    price_date: date | None = None


@dataclass
class Review:
    ticker: str
    status: str  # reviewed | sin_revision_ia
    decision: str | None = None
    thesis: str | None = None
    risks: list[str] = field(default_factory=list)
    invalidation: str | None = None
    confidence: float | None = None
    veto_reason: str | None = None
    evidence_keys: list[str] = field(default_factory=list)
    reject_reason: str | None = None


def _packet(batch: list[ReviewCandidate]) -> str:
    return json.dumps(
        [
            {
                "ticker": c.ticker,
                "empresa": c.name,
                "score_determinista": c.score,
                "datos": c.data,
            }
            for c in batch
        ],
        ensure_ascii=False,
        default=str,
    )


def _numbers_grounded(text: str, packet: str) -> bool:
    """Every number in the model's text must appear in the packet it received
    (small counters up to 10 are allowed: "2 riesgos")."""
    for m in _NUM.findall(text):
        token = m.rstrip(".,")
        if not token:
            continue
        try:
            if float(token.replace(",", ".")) <= 10:
                continue
        except ValueError:
            pass
        if token not in packet:
            return False
    return True


def validate_verdict(raw: Any, cand: ReviewCandidate, packet: str) -> Review:
    def reject(reason: str) -> Review:
        return Review(cand.ticker, NO_REVIEW, reject_reason=reason)

    if not isinstance(raw, dict):
        return reject("json_invalido")
    decision = raw.get("decision")
    thesis, invalidation = raw.get("thesis"), raw.get("invalidation")
    risks, keys = raw.get("risks"), raw.get("evidence_keys")
    conf = raw.get("confidence")
    if decision not in ("keep", "veto"):
        return reject("decision_invalida")
    if not isinstance(thesis, str) or len(thesis.strip()) < 10:
        return reject("tesis_invalida")
    if not isinstance(invalidation, str) or not invalidation.strip():
        return reject("sin_invalidacion")
    if not isinstance(risks, list) or not (2 <= len(risks) <= 3) or any(
        not isinstance(r, str) or not r.strip() for r in risks
    ):
        return reject("riesgos_invalidos")
    if isinstance(conf, bool) or not isinstance(conf, (int, float)) or not (0 <= conf <= 1):
        return reject("confianza_invalida")
    allowed = {d["key"] for d in cand.data}
    if not isinstance(keys, list) or not keys or any(k not in allowed for k in keys):
        return reject("evidencia_no_recibida")
    veto_reason = raw.get("veto_reason")
    if decision == "veto" and (not isinstance(veto_reason, str) or not veto_reason.strip()):
        return reject("veto_sin_motivo")
    texts = [thesis, invalidation, *risks, veto_reason or ""]
    if any(not _numbers_grounded(t, packet) for t in texts):
        return reject("cifra_no_recibida")
    return Review(
        cand.ticker, "reviewed", decision, thesis.strip(), [r.strip() for r in risks],
        invalidation.strip(), float(conf), (veto_reason or None), list(keys),
    )


async def review_shortlist(
    provider: Any, candidates: list[ReviewCandidate], *, on_response=None
) -> list[Review]:
    """One Review per candidate, in input order. Never raises on model failure."""
    out: dict[str, Review] = {}
    for i in range(0, len(candidates), BATCH):
        batch = candidates[i : i + BATCH]
        packet = _packet(batch)
        request = LLMRequest(
            messages=[Message("system", SYSTEM), Message("user", packet)],
            task=REVIEW_TASK,
            temperature=0.2,
            max_tokens=3500,
            response_format=ResponseFormat.json_schema(_SCHEMA, name="propicks_review"),
            metadata=_PROMPT.trace_metadata(),
        )
        try:
            guarded = await complete_guarded(
                provider, request, source="propicks_review", on_response=on_response
            )
            raw = parse_json_response(guarded.response.text)
            verdicts = raw.get("verdicts") if isinstance(raw, dict) else None
        except (LLMOutputRejected, Exception):  # noqa: BLE001 - model failure = no review
            verdicts = None
        by_ticker = {}
        for v in verdicts or []:
            if isinstance(v, dict) and isinstance(v.get("ticker"), str):
                by_ticker.setdefault(v["ticker"].upper(), v)  # names outside the batch are ignored below
        for c in batch:
            v = by_ticker.get(c.ticker.upper())
            out[c.ticker] = (
                validate_verdict(v, c, packet)
                if v is not None
                else Review(c.ticker, NO_REVIEW, reject_reason="sin_veredicto")
            )
    return [out[c.ticker] for c in candidates]


def log_reviews(
    db: Session, candidates: list[ReviewCandidate], reviews: list[Review], *, model: str | None, now: datetime
) -> int:
    n = 0
    by_t = {c.ticker: c for c in candidates}
    for r in reviews:
        if r.status != "reviewed":
            continue
        c = by_t[r.ticker]
        db.add(
            PropickReview(
                reviewed_at=now, ticker=r.ticker, model=model, decision=r.decision or "keep",
                confidence=r.confidence or 0.0, base_score=c.score, price=c.price, price_date=c.price_date,
                verdict={
                    "thesis": r.thesis, "risks": r.risks, "invalidation": r.invalidation,
                    "veto_reason": r.veto_reason, "evidence_keys": r.evidence_keys,
                },
            )
        )
        n += 1
    db.commit()
    return n


def evaluate_outcomes(db: Session, *, today: date | None = None) -> int:
    """Fill the 90-day price return for reviews that are old enough. Uses stored
    prices only; a missing or stale end price leaves the row open."""
    today = today or date.today()
    rows = db.scalars(
        select(PropickReview).where(PropickReview.outcome_return.is_(None)).where(PropickReview.price.isnot(None))
    ).all()
    done = 0
    for r in rows:
        if r.price_date is None or r.price is None or r.price <= 0:
            continue
        end_day = r.price_date + timedelta(days=OUTCOME_DAYS)
        if end_day > today:
            continue
        from app.models import Company

        company = db.scalar(select(Company).where(Company.ticker == r.ticker))
        if company is None:
            continue
        px = db.scalar(
            select(MarketPrice)
            .where(MarketPrice.company_id == company.id, MarketPrice.date >= end_day,
                   MarketPrice.date <= end_day + timedelta(days=7), MarketPrice.close.isnot(None))
            .order_by(MarketPrice.date.asc())
        )
        if px is None:
            continue
        r.outcome_return = float(px.close) / r.price - 1.0
        r.outcome_date = px.date
        done += 1
    db.commit()
    return done


def brier_report(db: Session) -> dict:
    """Brier of the LLM confidence vs a score-only baseline (base rate), on
    reviews with a resolved 90-day outcome (return > 0 counts as success).
    Below MIN_FOR_BRIER resolved reviews the numbers are not evidence."""
    rows = db.scalars(select(PropickReview).where(PropickReview.outcome_return.isnot(None))).all()
    n = len(rows)
    if n == 0:
        return {"n": 0, "enough": False}
    y = [1.0 if r.outcome_return > 0 else 0.0 for r in rows]
    base = sum(y) / n
    llm = sum((r.confidence - o) ** 2 for r, o in zip(rows, y, strict=True)) / n
    ref = sum((base - o) ** 2 for o in y) / n
    kept = [r.outcome_return for r in rows if r.decision == "keep" and r.outcome_return is not None]
    vetoed = [r.outcome_return for r in rows if r.decision == "veto" and r.outcome_return is not None]
    return {
        "n": n,
        "enough": n >= MIN_FOR_BRIER,
        "brier_llm": round(llm, 4),
        "brier_base_rate": round(ref, 4),
        "mean_return_kept": round(sum(kept) / len(kept), 4) if kept else None,
        "mean_return_vetoed": round(sum(vetoed) / len(vetoed), 4) if vetoed else None,
    }
