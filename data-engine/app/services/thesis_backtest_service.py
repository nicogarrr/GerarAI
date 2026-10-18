"""Point-in-time backtest of theses: does the alpha exist, or only the prose?

The product question this answers is "¿mis tesis tienen alfa o solo coherencia
narrativa?". Answering it honestly requires replaying each thesis *as it was
visible on the day it was written*, using only data that was public that day.
Anything else produces a beautiful chart and a worthless conclusion, which is
worse than not having the feature.

The unit of work is :meth:`ThesisBacktestService.cell` — one ticker, one day,
no side effects. The grid in :meth:`run` is a loop over it, and
:meth:`report` only aggregates persisted cells.

Three rules drive the whole module:

1. **Abstain, never improvise.** No data for the cutoff means
   ``status="insufficient_data"`` with a NULL fair value. Not zero, and not the
   current price wearing a fair-value label.
2. **A thesis that did not exist yet is not a miss.** ``published_at > as_of``
   yields ``status="not_yet_published"``, an empty cell, and no contribution to
   any hit-rate. Scoring it as a failure would punish the backtest for
   information it was not allowed to have.
3. **A rejected replay is a finding, not a discarded row.** When the public
   guard raises :class:`LookaheadError` the cell is stored as
   ``status="rejected_lookahead"`` and counted. Silently dropping it would make
   a broken filter look like a clean run.

How the replay is wired: ``ValuationService.value_company`` already accepts
``as_of`` and raises ``LookaheadError`` on future trace periods, so it is the
primitive we drive. But it resolves its snapshot through the base
``FinancialSnapshotBuilder`` (which reads "the latest") and its price through
``_position_price`` (which reads the newest close). Both are look-ahead leaks in
a replay, so :func:`pit_replay_scope` swaps in point-in-time versions of exactly
those two lookups for the duration of the call and restores them afterwards. No
shared file is modified, and the live valuation path is untouched.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import math
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Claim, Company, Document, MarketPrice, ThesisSection, ThesisVersion
from app.models.thesis_backtest import (
    ABSTENTION_STATUSES,
    STATUS_ERROR,
    STATUS_INSUFFICIENT_DATA,
    STATUS_NOT_YET_PUBLISHED,
    STATUS_OK,
    STATUS_REJECTED_LOOKAHEAD,
    BacktestCellRow,
    BacktestResult,
    BacktestRun,
)
from app.services.source_auditor import SourceAuditor
from app.services.valuation_service import ValuationService
from app.valuation.engines.base import MODEL_VERSION
from app.valuation.engines.registry import resolve_engine_key
from app.valuation.financial_snapshot import FinancialSnapshot, FinancialSnapshotBuilder
from app.valuation.period_bounds import (
    AS_OF_SOURCE_TODAY_DEFAULT,
    AsOfResolution,
    resolve_as_of,
    to_date,
)
from app.valuation.point_in_time import LookaheadError
from app.valuation.point_in_time_snapshot import PointInTimeSnapshotBuilder

# Realized-return horizons in calendar days. 1Q/3Q/1A/2A as the brief asks; the
# day counts are the convention used across the repo for horizon labels.
HORIZONS: dict[str, int] = {"1Q": 91, "3Q": 273, "1A": 365, "2A": 730}

# The S&P 500 is how `market_regime_quant.portfolio_beta` resolves its
# benchmark; we accept a small ladder so a European-only dataset still gets an
# alpha instead of a silent blank.
BENCHMARK_TICKERS = ("^GSPC", "^STOXX", "SPY", "^IBEX")

# Below this many scored cells a hit rate is noise, not evidence. The report
# refuses to declare alpha below the line and says so in words.
MIN_CELLS_FOR_ALPHA = 20
# Above this hit rate we suspect a leak rather than a genius, because a real
# thesis process does not win nine times out of ten.
SUSPICIOUS_HIT_RATE = 0.90

ND = "N/D"

# The replay patches two module attributes for the duration of one valuation.
# A lock keeps concurrent replays (the worker and a request could overlap)
# from interleaving patches and reading each other's price.
_PIT_LOCK = threading.RLock()


def _pit_builder_factory(
    inner: PointInTimeSnapshotBuilder,
) -> type[FinancialSnapshotBuilder]:
    """A real subclass of the shared builder, carrying the cutoff in a closure.

    A subclass (not a stub) so the patched symbol keeps the type the engines
    expect, and a closure (not an ``__init__`` argument) because every engine
    constructs it as ``FinancialSnapshotBuilder()`` with no arguments.
    """

    class _PointInTimeBuilder(FinancialSnapshotBuilder):
        def build(self, db: Session, company: Company) -> FinancialSnapshot:
            return inner.build(db, company)

    return _PointInTimeBuilder


@contextmanager
def pit_replay_scope(
    *, builder: PointInTimeSnapshotBuilder, price: float | None
) -> Iterator[None]:
    """Make ``value_company`` see only what was public at the cutoff.

    Only the two lookups that reach around the cutoff are replaced: the
    snapshot builder and the price resolver. Everything else in the valuation
    stack — engines, DCF, blockers, the public ``as_of`` guard — runs unmodified,
    so a replay exercises the same code the product ships.
    """
    engines_base = importlib.import_module("app.valuation.engines.base")
    valuation_service = importlib.import_module("app.services.valuation_service")
    with _PIT_LOCK:
        original_builder = engines_base.FinancialSnapshotBuilder
        original_price = valuation_service._position_price

        def _pit_price(_db: Session, _company_id: int, *_a, **_kw) -> float | None:
            return price

        engines_base.FinancialSnapshotBuilder = _pit_builder_factory(builder)
        valuation_service._position_price = _pit_price  # type: ignore[assignment]
        try:
            yield
        finally:
            engines_base.FinancialSnapshotBuilder = original_builder
            valuation_service._position_price = original_price


@dataclass
class BacktestCell:
    """One replayed (ticker, as_of). Every numeric field may be None — and a
    None fair value always travels with a status and a reason."""

    ticker: str
    as_of: date
    status: str
    evidence_cutoff: date
    fair_value: float | None = None
    bear_value: float | None = None
    base_value: float | None = None
    bull_value: float | None = None
    current_price: float | None = None
    upside: float | None = None
    price_date: date | None = None
    price_source: str | None = None
    engine_key: str | None = None
    model_version: str | None = None
    n_claims: int = 0
    n_claims_with_evidence: int = 0
    source_coverage_score: int | None = None
    debate_verdict: str | None = None
    debate_verdict_note: str | None = None
    degraded: bool = False
    degraded_reason: str | None = None
    lookahead_violations: list[str] = field(default_factory=list)
    excluded_future_inputs: list[str] = field(default_factory=list)
    unverifiable_inputs: list[str] = field(default_factory=list)
    missing_inputs: list[str] = field(default_factory=list)
    publication_blockers: list[str] = field(default_factory=list)
    point_in_time: dict = field(default_factory=dict)
    claims: list[dict] = field(default_factory=list)
    realized: dict = field(default_factory=dict)
    cell_hash: str = ""

    @property
    def is_abstention(self) -> bool:
        return self.status in ABSTENTION_STATUSES

    def hashable(self) -> dict:
        """The subset that must be identical on a replay.

        Explicit allow-list, not "everything but the timestamp": a hash that
        silently absorbs a new field would keep passing while the replay drifts.
        ``moat`` and the raw valuation dict are excluded on purpose — they are
        narrative layers, not the number the cell claims.
        """
        return {
            "ticker": self.ticker,
            "as_of": self.as_of.isoformat(),
            "status": self.status,
            "evidence_cutoff": self.evidence_cutoff.isoformat(),
            "fair_value": _round(self.fair_value),
            "bear_value": _round(self.bear_value),
            "base_value": _round(self.base_value),
            "bull_value": _round(self.bull_value),
            "current_price": _round(self.current_price),
            "upside": _round(self.upside),
            "price_date": self.price_date.isoformat() if self.price_date else None,
            "engine_key": self.engine_key,
            "model_version": self.model_version,
            "n_claims": self.n_claims,
            "n_claims_with_evidence": self.n_claims_with_evidence,
            "source_coverage_score": self.source_coverage_score,
            "debate_verdict": self.debate_verdict,
            "degraded": self.degraded,
            "degraded_reason": self.degraded_reason,
            "lookahead_violations": sorted(self.lookahead_violations),
            "excluded_future_inputs": sorted(self.excluded_future_inputs),
            "unverifiable_inputs": sorted(self.unverifiable_inputs),
            "missing_inputs": sorted(self.missing_inputs),
        }

    def compute_hash(self) -> str:
        payload = json.dumps(self.hashable(), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def as_dict(self) -> dict:
        data = self.hashable()
        data.update(
            {
                "publication_blockers": list(self.publication_blockers),
                "point_in_time": dict(self.point_in_time),
                "claims": list(self.claims),
                "realized": dict(self.realized),
                "debate_verdict_note": self.debate_verdict_note,
                "cell_hash": self.cell_hash or self.compute_hash(),
            }
        )
        return data


def _used_future(builder: PointInTimeSnapshotBuilder) -> list[str]:
    """Kept facts that are nonetheless dated after the cutoff: a filter bug.

    ``_candidates`` only keeps facts whose knowledge date is on or before the
    cutoff, so anything here means the filter let a future period through. It is
    reported as a violation rather than repaired, because a filter that
    silently repairs itself is a filter you can no longer trust.
    """
    out: list[str] = []
    for verdict in builder.audit.kept:
        known_on = verdict.bounds.known_on
        if known_on is not None and known_on > builder.as_of:
            out.append(
                f"{verdict.metric} (fact {verdict.fact_id}): USADO con fecha de "
                f"conocimiento {known_on.isoformat()} > corte {builder.as_of.isoformat()}"
            )
    return out


def _round(value: float | None, digits: int = 6) -> float | None:
    return None if value is None else round(float(value), digits)


def month_end(year: int, month: int) -> date:
    if month == 12:
        return date(year, 12, 31)
    return date(year, month + 1, 1) - timedelta(days=1)


def build_grid(start: date, end: date, step: str = "1M") -> list[date]:
    """Month-end or quarter-end cutoffs from ``start`` to ``end`` inclusive.

    Month/quarter *ends* on purpose: a cutoff in the middle of a period implies
    a knowledge state that no filing date ever produces. A quarterly grid is
    additionally aligned to calendar quarters, so it never emits a 31 January
    "Q1" cutoff that no company has ever reported against.
    """
    if step not in {"1M", "1Q"}:
        raise ValueError(f"step no soportado: {step!r}; usa '1M' o '1Q'")
    months = 1 if step == "1M" else 3
    year, month = start.year, start.month
    if step == "1Q":
        # Jump to the first calendar quarter end on or after `start`.
        while month % 3 != 0:
            year, month = _advance(year, month, 1)
    grid: list[date] = []
    while True:
        anchor = month_end(year, month)
        if anchor < start:
            year, month = _advance(year, month, months)
            continue
        if anchor > end:
            break
        grid.append(anchor)
        year, month = _advance(year, month, months)
    return grid


def _advance(year: int, month: int, months: int) -> tuple[int, int]:
    total = (year * 12 + (month - 1)) + months
    return total // 12, (total % 12) + 1


class ThesisBacktestService:
    """Replay theses across a ticker x date grid and score the outcome."""

    # ------------------------------------------------------------- cell (the heart)

    def cell(self, db: Session, ticker: str, as_of: date | None = None) -> BacktestCell:
        """Replay one ticker as it was visible on ``as_of``. No writes.

        With ``as_of=None`` the cutoff falls back to today and the cell is
        flagged ``AS_OF_SOURCE_TODAY_DEFAULT``: that is a live valuation with a
        date glued on, not a replay, and the report must be able to say so.
        """
        company = db.scalar(select(Company).where(Company.ticker == ticker))
        if company is None:
            raise ValueError(f"empresa desconocida: {ticker}")

        resolution: AsOfResolution = resolve_as_of(as_of=as_of)
        cutoff = resolution.cutoff
        pit_builder = PointInTimeSnapshotBuilder(as_of=cutoff)
        price_row = self._pit_price(db, company.id, cutoff)
        price = float(price_row.close) if price_row and price_row.close else None
        pit_block: dict = {
            **resolution.as_dict(),
            "as_of_strategy": "replay",
            "price_cutoff": cutoff.isoformat(),
            "price_date": price_row.date.isoformat() if price_row else None,
        }

        thesis = self._pit_thesis(db, company.id, cutoff)
        if thesis is None:
            return self._abstain(
                ticker=ticker,
                cutoff=cutoff,
                resolution=resolution,
                status=STATUS_NOT_YET_PUBLISHED,
                reason=f"N/D: no hay tesis publicada en {cutoff.isoformat()}",
                pit_block=pit_block,
                price_row=price_row,
                price=price,
            )

        claims, claim_audit = self._pit_claims(db, thesis.id, cutoff)
        n_with_evidence = sum(1 for item in claims if item["has_evidence"])
        audit = SourceAuditor().audit(
            [
                {
                    "claim": item["statement"],
                    "material": item["material"],
                    "source_id": item["source_id"],
                    "confidence": item["confidence"],
                }
                for item in claims
            ],
            calculation_trace={"as_of": cutoff.isoformat(), "thesis_version_id": thesis.id},
        )
        verdict, verdict_note = self._pit_debate(db, thesis.id, cutoff)

        try:
            with pit_replay_scope(builder=pit_builder, price=price):
                result = ValuationService().value_company(db, company, as_of=cutoff)
        except LookaheadError as exc:
            # The public guard fired. This cell is a FINDING: it proves the
            # filter let a future period reach the engine. Keep every trace it
            # left behind and count it; never let it masquerade as a valuation.
            return self._abstain(
                ticker=ticker,
                cutoff=cutoff,
                resolution=resolution,
                status=STATUS_REJECTED_LOOKAHEAD,
                reason=f"look-ahead rechazado por el guard publico: {exc}",
                pit_block=pit_block,
                price_row=price_row,
                price=price,
                lookahead=pit_builder.audit.lookahead_violations + [str(exc)],
                excluded_future=pit_builder.audit.lookahead_violations,
                unverifiable=pit_builder.audit.unverifiable_inputs,
                # `value_company` raised, so there is no result dict to read the
                # engine from. The registry is deterministic, so the engine that
                # was attempted is still nameable — and a rejection nobody can
                # attribute to an engine is a finding nobody can act on.
                engine_key=resolve_engine_key(company),
                model_version=MODEL_VERSION,
                claims=claims,
                n_claims=len(claims),
                n_with_evidence=n_with_evidence,
                coverage=audit.source_coverage_score,
                verdict=verdict,
                verdict_note=verdict_note,
            )
        except Exception as exc:  # noqa: BLE001 - a cell must never kill the grid
            return self._abstain(
                ticker=ticker,
                cutoff=cutoff,
                resolution=resolution,
                status=STATUS_ERROR,
                reason=f"error al valorar: {type(exc).__name__}: {exc}",
                pit_block=pit_block,
                price_row=price_row,
                price=price,
                claims=claims,
                n_claims=len(claims),
                n_with_evidence=n_with_evidence,
                coverage=audit.source_coverage_score,
                verdict=verdict,
                verdict_note=verdict_note,
            )

        engine_key = str((result.get("trace") or {}).get("resolved_engine") or "")
        model_version = str((result.get("trace") or {}).get("model_version") or "")
        # Facts the filter refused. NOT violations: a working point-in-time
        # filter is supposed to encounter future rows in the database on every
        # single replay. They are reported because their absence would mean
        # nobody checked, and their presence is the proof the trap was sprung
        # and survived.
        excluded_future = list(pit_builder.audit.lookahead_violations)

        # Violations are facts that were USED and are dated after the cutoff,
        # plus anything the engine's own trace still places in the future.
        # `value_company` only inspects the periods it can parse, so the trace
        # pass catches shapes its regex misses.
        violations = _used_future(pit_builder) + self._trace_violations(
            result.get("trace") or {}, cutoff
        )
        try:
            pit_builder.assert_no_lookahead(None)
        except AssertionError as exc:  # pragma: no cover - the filter should prevent it
            violations.append(str(exc))
        pit_block = {
            **pit_block,
            "snapshot": pit_builder.audit.as_dict(),
            "claims_audit": claim_audit,
            "valuation_periods": (result.get("trace") or {}).get("periods") or {},
        }

        if violations:
            return self._abstain(
                ticker=ticker,
                cutoff=cutoff,
                resolution=resolution,
                status=STATUS_REJECTED_LOOKAHEAD,
                reason=(
                    f"{len(violations)} periodo(s) posterior(es) al corte "
                    f"{cutoff.isoformat()} llegaron a la valoración"
                ),
                pit_block=pit_block,
                price_row=price_row,
                price=price,
                lookahead=violations,
                excluded_future=excluded_future,
                unverifiable=pit_builder.audit.unverifiable_inputs,
                engine_key=engine_key,
                model_version=model_version,
                claims=claims,
                n_claims=len(claims),
                n_with_evidence=n_with_evidence,
                coverage=audit.source_coverage_score,
                verdict=verdict,
                verdict_note=verdict_note,
            )

        missing = [str(item) for item in (result.get("missing_inputs") or [])]
        unverifiable = list(pit_builder.audit.unverifiable_inputs)
        blockers = [str(item) for item in (result.get("publication_blockers") or [])]
        base_value = _as_float(result.get("base_value"))
        expected = _as_float(result.get("expected_value")) or base_value
        status = str(result.get("status") or STATUS_INSUFFICIENT_DATA)
        if status != STATUS_OK or expected is None:
            missing = missing or ["fair_value"]
            return self._abstain(
                ticker=ticker,
                cutoff=cutoff,
                resolution=resolution,
                status=STATUS_INSUFFICIENT_DATA,
                reason=(
                    f"{ND}: datos insuficientes a {cutoff.isoformat()} "
                    f"({', '.join(missing) or 'sin fair value'})"
                ),
                pit_block=pit_block,
                price_row=price_row,
                price=price,
                missing=missing,
                excluded_future=excluded_future,
                unverifiable=unverifiable,
                claims=claims,
                n_claims=len(claims),
                n_with_evidence=n_with_evidence,
                coverage=audit.source_coverage_score,
                verdict=verdict,
                verdict_note=verdict_note,
            )

        blockers_degraded = bool(blockers) or not bool(result.get("publishable"))
        degraded = blockers_degraded or bool(unverifiable)
        reasons: list[str] = []
        if blockers:
            reasons.append("publication_blockers: " + "; ".join(blockers[:3]))
        if not result.get("publishable") and not blockers:
            reasons.append(f"valoracion no publicable (status={status})")
        if unverifiable:
            reasons.append(
                f"{len(unverifiable)} insumo(s) sin fecha de publicacion verificable"
            )

        cell = BacktestCell(
            ticker=ticker,
            as_of=cutoff,
            status=STATUS_OK,
            evidence_cutoff=cutoff,
            fair_value=expected,
            bear_value=_as_float(result.get("bear_value")),
            base_value=base_value,
            bull_value=_as_float(result.get("bull_value")),
            current_price=price,
            upside=(expected / price - 1.0) if price else None,
            price_date=price_row.date if price_row else None,
            price_source="MarketPrice.close<=as_of" if price_row else None,
            engine_key=engine_key,
            model_version=model_version,
            n_claims=len(claims),
            n_claims_with_evidence=n_with_evidence,
            source_coverage_score=audit.source_coverage_score,
            debate_verdict=verdict,
            debate_verdict_note=verdict_note,
            degraded=degraded,
            degraded_reason="; ".join(reasons) if reasons else None,
            lookahead_violations=[],
            excluded_future_inputs=excluded_future,
            unverifiable_inputs=unverifiable,
            missing_inputs=missing,
            publication_blockers=blockers,
            point_in_time=pit_block,
            claims=claims,
        )
        cell.realized = self._realized(db, company.id, cutoff, price_row)
        cell.cell_hash = cell.compute_hash()
        return cell

    # ------------------------------------------------------------------ helpers

    def _abstain(
        self,
        *,
        ticker: str,
        cutoff: date,
        resolution: AsOfResolution,
        status: str,
        reason: str,
        pit_block: dict,
        price_row: MarketPrice | None,
        price: float | None,
        lookahead: list[str] | None = None,
        excluded_future: list[str] | None = None,
        unverifiable: list[str] | None = None,
        missing: list[str] | None = None,
        engine_key: str | None = None,
        model_version: str | None = None,
        claims: list[dict] | None = None,
        n_claims: int = 0,
        n_with_evidence: int = 0,
        coverage: int | None = None,
        verdict: str | None = None,
        verdict_note: str | None = None,
    ) -> BacktestCell:
        """Build a cell that refuses to produce a number, and says why.

        ``current_price`` is still recorded — it is a fact about that day, not a
        stand-in for a valuation — but ``fair_value`` stays ``None``. That
        separation is the whole point: the current price must never be able to
        masquerade as a fair value.

        The cell is marked ``degraded`` even when the abstention is the correct
        answer (a thesis that did not exist yet). Degradation here means "this
        cell is not a publishable result", which is what the report's
        degradation rate has to count; the *reason* distinguishes a broken
        replay from a correctly empty one.
        """
        cell = BacktestCell(
            ticker=ticker,
            as_of=cutoff,
            status=status,
            evidence_cutoff=cutoff,
            fair_value=None,
            current_price=price,
            # The engine that produced the trace is recorded even when its
            # output was rejected: "which engine leaks" is the first question
            # anyone asks about a look-ahead rejection, and a NULL here would
            # make the finding unattributable.
            engine_key=engine_key,
            model_version=model_version,
            price_date=price_row.date if price_row else None,
            price_source="MarketPrice.close<=as_of" if price_row else None,
            n_claims=n_claims,
            n_claims_with_evidence=n_with_evidence,
            source_coverage_score=coverage,
            debate_verdict=verdict,
            debate_verdict_note=verdict_note,
            degraded=True,
            degraded_reason=reason,
            lookahead_violations=list(lookahead or []),
            excluded_future_inputs=list(excluded_future or []),
            unverifiable_inputs=list(unverifiable or []),
            missing_inputs=list(missing or []),
            point_in_time={
                **pit_block,
                "abstention_reason": reason,
                "as_of_inferred": resolution.inferred,
            },
            claims=list(claims or []),
        )
        cell.cell_hash = cell.compute_hash()
        return cell

    @staticmethod
    def _pit_price(db: Session, company_id: int, cutoff: date) -> MarketPrice | None:
        """Last stored close on or before the cutoff.

        A price row dated after the cutoff exists in plenty of datasets; the
        filter is the guard. It is not a "violation" because the backtest never
        *used* it — using it would be.
        """
        return db.scalar(
            select(MarketPrice)
            .where(MarketPrice.company_id == company_id, MarketPrice.date <= cutoff)
            .order_by(MarketPrice.date.desc())
            .limit(1)
        )

    @staticmethod
    def _pit_thesis(db: Session, company_id: int, cutoff: date) -> ThesisVersion | None:
        """Latest thesis version created on or before the cutoff.

        ``ThesisVersion`` has no explicit ``published_at``; ``created_at`` is
        the row's own timestamp and is what ordering and freshness elsewhere in
        the repo already use, so the replay uses it too rather than inventing a
        second notion of publication.
        """
        end_of_day = cutoff + timedelta(days=1)
        return db.scalar(
            select(ThesisVersion)
            .where(
                ThesisVersion.company_id == company_id,
                ThesisVersion.created_at < end_of_day,
            )
            .order_by(ThesisVersion.created_at.desc(), ThesisVersion.version.desc())
            .limit(1)
        )

    def _pit_claims(self, db: Session, thesis_id: int, cutoff: date) -> tuple[list[dict], dict]:
        """Claims of the thesis, with evidence that was already published.

        A claim whose only evidence is a document filed after the cutoff counts
        as *unsupported*, not as supported-with-a-later-filing. That is the
        difference between measuring source coverage and pretending to.
        """
        end_of_day = cutoff + timedelta(days=1)
        rows = list(
            db.scalars(
                select(Claim)
                .where(Claim.thesis_version_id == thesis_id, Claim.created_at < end_of_day)
                .order_by(Claim.id)
            ).all()
        )
        out: list[dict] = []
        excluded_evidence = 0
        for claim in rows:
            claim_evidence = list(claim.evidence or [])
            usable: list[Claim] = []
            for item in claim_evidence:
                document = (
                    db.get(Document, item.document_id) if item.document_id else None
                )
                published = to_date(document.published_at) if document else None
                if published is not None and published > cutoff:
                    excluded_evidence += 1
                    continue
                usable.append(item)
            out.append(
                {
                    "id": claim.id,
                    "statement": claim.statement,
                    "metric": (claim.metadata_ or {}).get("metric"),
                    "material": True,
                    # Only evidence that was actually public by the cutoff can
                    # vouch for a claim. Attributing the claim to its first
                    # evidence row regardless of that row's filing date is the
                    # same look-ahead leak one layer up: the coverage score would
                    # report 100% for a thesis whose only support arrived later.
                    "source_id": usable[0].document_id if usable else None,
                    "confidence": float(claim.confidence or 0),
                    "has_evidence": bool(usable),
                    "n_evidence": len(claim_evidence),
                }
            )
        audit = {
            "n_claims": len(out),
            "n_claims_with_evidence": sum(1 for item in out if item["has_evidence"]),
            "evidence_excluded_after_cutoff": excluded_evidence,
        }
        return out, audit

    @staticmethod
    def _pit_debate(db: Session, thesis_id: int, cutoff: date) -> tuple[str | None, str]:
        """Stored debate verdict for this thesis, if it existed by the cutoff.

        The debate is an LLM service and is deliberately not replayed here: a
        backtest that re-asks a model what it thought in the past is measuring
        today's model, not the past. Only a verdict persisted on or before the
        cutoff counts, and its absence is reported rather than imputed.
        """
        end_of_day = cutoff + timedelta(days=1)
        section = db.scalar(
            select(ThesisSection).where(
                ThesisSection.thesis_version_id == thesis_id,
                ThesisSection.section_key == "thesis_debate",
                ThesisSection.created_at < end_of_day,
            )
        )
        if section is None:
            return None, f"{ND}: no hay veredicto de debate persistido en la fecha de corte"
        verdict = str((section.metadata_ or {}).get("verdict") or "").strip().lower()
        if verdict not in {"bullish", "bearish", "neutral"}:
            return None, f"{ND}: veredicto de debate persistido sin valor reconocible"
        return verdict, "persistido en thesis_debate antes de la fecha de corte"

    @staticmethod
    def _trace_violations(trace: dict, cutoff: date) -> list[str]:
        """Periods the engine's own trace places after the cutoff."""
        from app.valuation.period_bounds import parse_period_bounds

        found: list[str] = []
        periods = trace.get("periods") or {}
        if not isinstance(periods, dict):
            return found
        for label, raw in periods.items():
            bounds = parse_period_bounds(period=str(raw))
            if bounds.end_date is not None and bounds.end_date > cutoff:
                found.append(
                    f"valuation {label}: periodo {raw!r} termina "
                    f"{bounds.end_date.isoformat()} > corte {cutoff.isoformat()}"
                )
        return found

    # ---------------------------------------------------------- realized returns

    def _adjusted_series(
        self, db: Session, company_id: int
    ) -> list[tuple[date, float]]:
        """``(date, adj_close)`` for positive adjusted closes, ascending.

        The repository's rule, from ``market_regime_quant.portfolio_beta`` and
        the ``adj_close`` column comment: a NULL adjusted close means the source
        gave a spot, not a series adjusted for splits and dividends, and a
        fabricated adjustment would silently corrupt compounded returns. So only
        ``adj_close > 0`` counts and a missing one yields "N/D", never a
        reconstructed number.
        """
        rows = db.scalars(
            select(MarketPrice)
            .where(MarketPrice.company_id == company_id)
            .order_by(MarketPrice.date)
        ).all()
        return [
            (row.date, float(row.adj_close))
            for row in rows
            if row.adj_close is not None and float(row.adj_close) > 0
        ]

    def _realized(
        self,
        db: Session,
        company_id: int,
        cutoff: date,
        entry_row: MarketPrice | None,
    ) -> dict:
        """Forward return, MAE/MFE and benchmark alpha per horizon.

        Everything here is measured from the *adjusted* close, so splits and
        dividends are handled by the same convention the rest of the repo uses
        instead of a second, home-grown adjustment rule.
        """
        series = self._adjusted_series(db, company_id)
        if entry_row is None or entry_row.adj_close is None or float(entry_row.adj_close) <= 0:
            return {
                "available": False,
                "reason": f"{ND}: la fila de precio del {cutoff.isoformat()} no trae adj_close",
            }
        entry = float(entry_row.adj_close)
        after = [(day, px) for day, px in series if day > cutoff]
        benchmark = self._benchmark_series(db)
        out: dict[str, dict] = {}
        for label, days in HORIZONS.items():
            target = cutoff + timedelta(days=days)
            window = [(day, px) for day, px in after if day <= target]
            if not window:
                out[label] = {
                    "status": "sin_datos",
                    "reason": f"{ND}: no hay cierres ajustados hasta {target.isoformat()}",
                }
                continue
            last_day, last_px = window[-1]
            path = [px / entry - 1.0 for _, px in window]
            row: dict[str, object] = {
                "status": "ok",
                "days": (last_day - cutoff).days,
                "exit_date": last_day.isoformat(),
                "return": round(last_px / entry - 1.0, 6),
                "mae": round(min(path), 6),
                "mfe": round(max(path), 6),
            }
            bench = self._benchmark_return(benchmark, cutoff, last_day)
            if bench is None:
                row["alpha"] = None
                row["alpha_reason"] = f"{ND}: sin serie de índice en BD para la ventana"
            else:
                row["alpha"] = round(float(row["return"]) - bench, 6)
            out[label] = row
        out["available"] = True
        out["entry_adj_close"] = entry
        return out

    def _benchmark_series(self, db: Session) -> tuple[str, list[tuple[date, float]]] | None:
        for ticker in BENCHMARK_TICKERS:
            company = db.scalar(select(Company).where(Company.ticker == ticker))
            if company is None:
                continue
            series = self._adjusted_series(db, company.id)
            if series:
                return ticker, series
        return None

    @staticmethod
    def _benchmark_return(
        benchmark: tuple[str, list[tuple[date, float]]] | None,
        start: date,
        end: date,
    ) -> float | None:
        """Benchmark return over ``(start, end]``, same rule as the stock leg.

        "Last close on or before the endpoint" on both series. It is not
        forward filling: no price is ever invented or carried across a missing
        session, each leg is priced at the last session that actually exists.
        Using the same rule for the stock and the index is what makes the
        difference between them an alpha rather than two different date
        conventions.
        """
        if benchmark is None:
            return None
        series = benchmark[1]
        entry = next((px for day, px in reversed(series) if day <= start), None)
        exit_px = next((px for day, px in reversed(series) if day <= end), None)
        if entry is None or exit_px is None or entry <= 0:
            return None
        return exit_px / entry - 1.0

    # ----------------------------------------------------------------- grid run

    def run(
        self,
        db: Session,
        *,
        tickers: list[str],
        start: date,
        end: date,
        step: str = "1M",
        as_of_strategy: str = "replay",
        thesis_filter: str | None = None,
        commit: bool = True,
    ) -> BacktestRun:
        """Replay the whole grid and persist one row per cell, idempotently.

        Re-running updates the existing ``(ticker, as_of)`` rows instead of
        appending: the unique constraint is the mechanism, and a changed cell
        hash is recorded rather than silently overwriting history.
        """
        if as_of_strategy != "replay":
            raise ValueError(
                f"as_of_strategy no soportado: {as_of_strategy!r}; solo 'replay' "
                "(una estrategia que no reproduce el pasado no es un backtest)"
            )
        grid = build_grid(start, end, step)
        if not grid:
            raise ValueError("la rejilla esta vacia: start > end")

        run_row = BacktestRun(
            tickers=[t.upper() for t in tickers],
            start=start,
            end=end,
            step=step,
            as_of_strategy=as_of_strategy,
            status="running",
            cells_total=len(grid) * len(tickers),
            params={
                "thesis_filter": thesis_filter,
                "grid": [day.isoformat() for day in grid],
            },
        )
        db.add(run_row)
        db.flush()

        done = 0
        try:
            for ticker in tickers:
                for cutoff in grid:
                    if thesis_filter and thesis_filter.lower() not in ticker.lower():
                        continue
                    try:
                        cell = self.cell(db, ticker, cutoff)
                    except ValueError:
                        # Unknown ticker: recorded as an honest gap, not a crash.
                        cell = BacktestCell(
                            ticker=ticker,
                            as_of=cutoff,
                            status=STATUS_ERROR,
                            evidence_cutoff=cutoff,
                            degraded=True,
                            degraded_reason=f"{ND}: ticker sin ficha en BD",
                            point_in_time={"as_of": cutoff.isoformat()},
                        )
                        cell.cell_hash = cell.compute_hash()
                    self._upsert_cell(db, run_row.id, cell)
                    done += 1
            run_row.cells_done = done
            run_row.status = "succeeded"
        except Exception as exc:  # noqa: BLE001 - the run row must record the cause
            run_row.status = "failed"
            run_row.error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            run_row.finished_at = datetime.now(UTC)
            if commit:
                db.commit()
        self._persist_result(db, run_row, commit=commit)
        return run_row

    def _upsert_cell(self, db: Session, run_id: int, cell: BacktestCell) -> BacktestCellRow:
        existing = db.scalar(
            select(BacktestCellRow).where(
                BacktestCellRow.run_id == run_id,
                BacktestCellRow.ticker == cell.ticker,
                BacktestCellRow.as_of == cell.as_of,
            )
        )
        payload = {
            "status": cell.status,
            "engine_key": cell.engine_key,
            "model_version": cell.model_version,
            "evidence_cutoff": cell.evidence_cutoff,
            "fair_value": cell.fair_value,
            "bear_value": cell.bear_value,
            "base_value": cell.base_value,
            "bull_value": cell.bull_value,
            "current_price": cell.current_price,
            "upside": cell.upside,
            "price_date": cell.price_date,
            "price_source": cell.price_source,
            "n_claims": cell.n_claims,
            "n_claims_with_evidence": cell.n_claims_with_evidence,
            "source_coverage_score": cell.source_coverage_score,
            "debate_verdict": cell.debate_verdict,
            "degraded": cell.degraded,
            "degraded_reason": cell.degraded_reason,
            "lookahead_violations": list(cell.lookahead_violations),
            "excluded_future_inputs": list(cell.excluded_future_inputs),
            "unverifiable_inputs": list(cell.unverifiable_inputs),
            "missing_inputs": list(cell.missing_inputs),
            "publication_blockers": list(cell.publication_blockers),
            "point_in_time": dict(cell.point_in_time),
            "realized": dict(cell.realized),
            "claims": list(cell.claims),
            "cell_hash": cell.cell_hash,
        }
        if existing is None:
            existing = BacktestCellRow(
                run_id=run_id, ticker=cell.ticker, as_of=cell.as_of, **payload
            )
            db.add(existing)
        else:
            for key, value in payload.items():
                setattr(existing, key, value)
        db.flush()
        return existing

    def cells(
        self, db: Session, run_id: int, *, ticker: str | None = None, as_of: date | None = None
    ) -> list[BacktestCellRow]:
        statement = select(BacktestCellRow).where(BacktestCellRow.run_id == run_id)
        if ticker:
            statement = statement.where(BacktestCellRow.ticker == ticker.upper())
        if as_of:
            statement = statement.where(BacktestCellRow.as_of == as_of)
        return list(db.scalars(statement.order_by(BacktestCellRow.ticker, BacktestCellRow.as_of)).all())

    # ------------------------------------------------------------------- report

    def _persist_result(self, db: Session, run_row: BacktestRun, *, commit: bool) -> BacktestResult:
        metrics = self.compute_metrics(db, run_row.id)
        row = db.scalar(
            select(BacktestResult).where(
                BacktestResult.run_id == run_row.id, BacktestResult.tenant_id == run_row.tenant_id
            )
        )
        if row is None:
            row = BacktestResult(run_id=run_row.id)
            db.add(row)
        row.metrics = metrics
        row.warnings = list(metrics.get("advertencias", []))
        row.computed_at = datetime.now(UTC)
        db.flush()
        if commit:
            db.commit()
        return row

    def report(self, db: Session, run_id: int) -> dict:
        """The honest answer, including the parts that undercut it.

        Always reports the cell count and the dispersion next to any hit rate:
        a 100% hit rate over four cells is not a result, and printing it without
        the denominator is how a backtest ends up quoted as proof of alpha.
        """
        run_row = db.get(BacktestRun, run_id)
        if run_row is None:
            raise ValueError(f"backtest no encontrado: {run_id}")
        result_row = db.scalar(
            select(BacktestResult).where(BacktestResult.run_id == run_id)
        )
        metrics = dict(result_row.metrics) if result_row and result_row.metrics else {}
        metrics.update(self.compute_metrics(db, run_id))
        return {
            "run_id": run_id,
            "tickers": list(run_row.tickers or []),
            "start": run_row.start.isoformat(),
            "end": run_row.end.isoformat(),
            "step": run_row.step,
            "as_of_strategy": run_row.as_of_strategy,
            "status": run_row.status,
            "error": run_row.error,
            **metrics,
        }

    def compute_metrics(self, db: Session, run_id: int) -> dict:
        """Aggregate the persisted cells. Pure read; safe to call repeatedly."""
        rows = self.cells(db, run_id)
        by_status: dict[str, int] = {}
        for row in rows:
            by_status[row.status] = by_status.get(row.status, 0) + 1

        scored = [row for row in rows if row.status == STATUS_OK and row.fair_value is not None]
        warnings: list[str] = []
        rejections = [row for row in rows if row.status == STATUS_REJECTED_LOOKAHEAD]

        horizons: dict[str, dict] = {}
        for label in HORIZONS:
            horizons[label] = _horizon_stats(scored, label)

        hits = 0
        hits_n = 0
        for row in scored:
            realized = (row.realized or {}).get("1A") or {}
            if realized.get("status") != "ok" or row.upside is None:
                continue
            if float(row.upside) <= 0:
                continue
            hits_n += 1
            if float(realized.get("return", 0.0)) > 0:
                hits += 1
        hit_rate = (hits / hits_n) if hits_n else None

        coverages = [row.source_coverage_score for row in scored if row.source_coverage_score is not None]
        total_claims = sum(row.n_claims for row in rows)
        with_evidence = sum(row.n_claims_with_evidence for row in rows)
        degraded_rows = [row for row in rows if row.degraded]
        degraded_reasons: dict[str, int] = {}
        for row in degraded_rows:
            key = _degradation_bucket(row)
            degraded_reasons[key] = degraded_reasons.get(key, 0) + 1

        inferred = [
            row
            for row in rows
            if (row.point_in_time or {}).get("as_of_source") == AS_OF_SOURCE_TODAY_DEFAULT
        ]

        warnings.append(_alpha_verdict(hit_rate, hits_n, len(rows), len(scored)))

        return {
            "celdas": {
                "total": len(rows),
                "por_estado": by_status,
                "validas_para_puntuar": len(scored),
                "con_tenesis_no_publicada": by_status.get(STATUS_NOT_YET_PUBLISHED, 0),
                "datos_insuficientes": by_status.get(STATUS_INSUFFICIENT_DATA, 0),
                "rechazadas_por_lookahead": len(rejections),
                "errores": by_status.get(STATUS_ERROR, 0),
                "as_of_inferido_por_defecto": len(inferred),
            },
            "hit_rate_1A": {
                "aciertos": hits,
                "muestra": hits_n,
                "tasa": round(hit_rate, 4) if hit_rate is not None else None,
                "metodo": (
                    "celdas con upside>0 cuyo retorno realizado a 1 año (adj_close) "
                    "tambien fue >0; el denominador excluye abstenciones"
                ),
            },
            "retornos_realizados": horizons,
            "dispersion": _dispersion(scored),
            "source_coverage_score": {
                "n": len(coverages),
                "min": min(coverages) if coverages else None,
                "mediana": _median(coverages),
                "max": max(coverages) if coverages else None,
                "histograma": _histogram(coverages),
            },
            "cobertura_claims": {
                "claims_totales": total_claims,
                "claims_con_evidencia": with_evidence,
                "pct": round(100.0 * with_evidence / total_claims, 2) if total_claims else None,
            },
            "degradadas": {
                "n": len(degraded_rows),
                "pct": round(100.0 * len(degraded_rows) / len(rows), 2) if rows else None,
                "desglose": degraded_reasons,
            },
            "rechazos_lookahead": {
                "n": len(rejections),
                "detalle": [
                    {
                        "ticker": row.ticker,
                        "as_of": row.as_of.isoformat(),
                        "violaciones": list(row.lookahead_violations or []),
                    }
                    for row in rejections
                ],
            },
            "advertencias": warnings,
        }


def _degradation_bucket(row: BacktestCellRow) -> str:
    """A stable category for a degraded cell, not its full sentence.

    Keying the breakdown by the raw ``degraded_reason`` produced one entry per
    cell — every message embeds its own date — which turned a readable summary
    into a wall of unique keys. The full reason stays on the cell; this is the
    roll-up a reader can act on.
    """
    reason = (row.degraded_reason or "").lower()
    if row.status == STATUS_REJECTED_LOOKAHEAD:
        return "rechazo_lookahead"
    if row.status == STATUS_NOT_YET_PUBLISHED:
        return "tesis_no_publicada_en_la_fecha"
    if row.status == STATUS_ERROR:
        return "error_de_ejecucion"
    if "sin fecha de publicacion verificable" in reason:
        return "provenance_no_verificable"
    if "publication_blockers" in reason:
        return "publication_blockers"
    if "no hay tesis publicada" in reason:
        return "tesis_no_publicada_en_la_fecha"
    if "datos insuficientes" in reason or "sin fair value" in reason:
        return "datos_insuficientes"
    if not reason:
        return "sin_motivo_declarado"
    return "otra"


def _as_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[mid])
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def _rounded(value: float | None, sample: list[float]) -> float | None:
    """Round a statistic only when there is a sample behind it.

    Every aggregate in the report goes through here so that "no data" is always
    ``None`` and never a rounded zero. A median of an empty list printed as
    ``0.0`` is indistinguishable from a genuinely flat result.
    """
    if value is None or not sample:
        return None
    return round(value, 6)


def _mean(values: list[float]) -> float | None:
    """Arithmetic mean, or ``None`` on an empty sample.

    The emptiness check comes before the division on purpose: ``sum([]) / 0``
    would take down a report over a column that legitimately has no rows, and
    the one moment the reader most needs an answer is the one where the grid
    produced no data.
    """
    if not values:
        return None
    return round(sum(values) / len(values), 6)


def _histogram(values: list[float], buckets: int = 5) -> dict[str, int]:
    if not values:
        return {}
    low, high = min(values), max(values)
    if high == low:
        return {f"{low:.0f}": len(values)}
    width = (high - low) / buckets
    out: dict[str, int] = {}
    for value in values:
        index = min(int((value - low) / width), buckets - 1)
        key = f"{low + index * width:.0f}-{low + (index + 1) * width:.0f}"
        out[key] = out.get(key, 0) + 1
    return out


def _horizon_stats(scored: list[BacktestCellRow], label: str) -> dict:
    returns: list[float] = []
    alphas: list[float] = []
    maes: list[float] = []
    mfes: list[float] = []
    for row in scored:
        realized = (row.realized or {}).get(label) or {}
        if realized.get("status") != "ok":
            continue
        returns.append(float(realized.get("return", 0.0)))
        maes.append(float(realized.get("mae", 0.0)))
        mfes.append(float(realized.get("mfe", 0.0)))
        if realized.get("alpha") is not None:
            alphas.append(float(realized["alpha"]))
    return {
        "n": len(returns),
        "retorno_medio": _mean(returns),
        "retorno_mediano": _rounded(_median(returns), returns),
        "mae_medio": _mean(maes),
        "mfe_medio": _mean(mfes),
        "alpha_medio": _mean(alphas),
        "alpha_n": len(alphas),
    }


def _dispersion(scored: list[BacktestCellRow]) -> dict:
    up = [float(row.upside) for row in scored if row.upside is not None]
    values = [float(row.fair_value) for row in scored if row.fair_value is not None]
    return {
        "upside_min": _rounded(min(up) if up else None, up),
        "upside_max": _rounded(max(up) if up else None, up),
        "upside_mediana": _rounded(_median(up), up),
        "upside_desviacion": _rounded(_stdev(up) if len(up) > 1 else None, up),
        "fair_value_distintos": len({round(value, 6) for value in values}),
        "fair_value_valores": len(values),
    }


def _stdev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    return math.sqrt(variance)


def _alpha_verdict(
    hit_rate: float | None, hits_n: int, total: int, scored: int
) -> str:
    """One sentence, and the only sentence that may be quoted on its own.

    It is deliberately conservative in both directions: too few cells is not
    evidence of no alpha, it is absence of evidence, and a suspiciously perfect
    rate is called a possible leak rather than a triumph.
    """
    if not scored or hits_n == 0 or hit_rate is None:
        return (
            f"Sin veredicto: no hay celdas con precio de salida a 1 año "
            f"({scored} celdas validas de {total}). No se puede afirmar ni alfa ni su ausencia."
        )
    if scored < MIN_CELLS_FOR_ALPHA:
        return (
            f"Muestra insuficiente ({scored} celdas validas, minimo {MIN_CELLS_FOR_ALPHA}): "
            f"el hit-rate de {hit_rate:.1%} es ruido, no evidencia. "
            "No publicar este numero sin agrandar la rejilla."
        )
    if hit_rate > SUSPICIOUS_HIT_RATE:
        return (
            f"SOSPECHOSO: hit-rate de {hit_rate:.1%} sobre {hits_n} celdas. Un proceso de "
            "tesis real no gana 9 de cada 10; antes de leerlo como alfa, suspecta de "
            f"look-ahead o de sobreajuste. {total - scored} celdas quedaron fuera de la puntuacion."
        )
    if hit_rate <= 0.55:
        return (
            f"Sin alfa demostrable: hit-rate de {hit_rate:.1%} sobre {hits_n} celdas, "
            f"es compatible con el azar. En este tramo las tesis aportan coherencia "
            "narrativa, no ventaja medible."
        )
    return (
        f"Hit-rate de {hit_rate:.1%} sobre {hits_n} celdas: por encima del azar, pero "
        f"la dispersion y el alpha por horizonte ({total - scored} celdas sin puntuacion) "
        "deben leerse antes de llamarlo alfa."
    )
