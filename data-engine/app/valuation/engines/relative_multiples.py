"""Relative-multiples engine: the subject's multiple against a peer set.

Engine *and* sanity-check. A relative multiple is the screening tool people
actually use and the easiest one to lie with, because the peer set can be
chosen until the answer agrees with the price. Three things make this engine
defensible:

1. **The peer set is not invented and its provenance is published.** The set
   comes from ``PeerComparisonService`` (manual overrides first, then a
   scored multifactor selection that returns its own ``selection_trace``), and
   the basis travels to ``trace["peer_set"]``. A stored provider multiple
   (``multiple_{kind}_{ticker}``) is preferred over a derived one and carries
   its ``source_type`` and ``period``; without a declared source the entry is
   marked ``source="N/D"`` and the result says so.
2. **A negative denominator is N/D, not a cheap share.** ``P/E`` on a
   loss-making company is returned as ``None`` with the reason attached.
3. **The engine reports where it disagrees with the DCF.** A 4x gap between the
   peer-implied price and the intrinsic value is the single most informative
   number in a relative screen, and it is published as
   ``trace["dcf_vs_relative_divergence"]`` with a sentence naming the two
   possible explanations rather than resolving the tie silently.

Multiple arithmetic is **not** reimplemented: ``app/valuation/relative_multiples.py``
holds the pure primitives and reuses the exact formulas of
``HistoricalValuationService`` (``pe = price / eps``,
``EV = price * shares + debt - cash``), which is verified by a test that runs
both over the same inputs.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.models import Company, FinancialFact, MarketPrice
from app.services.price_units import close_in_company_currency
from app.valuation.engines.base import (
    MODEL_VERSION,
    ValuationContext,
    ValuationEngine,
    adr_comparable_price,
    adr_ratio,
    apply_publication_blockers,
    context_split_cutoff,
    insufficient_result,
    is_adr_without_ratio,
    margin_of_safety,
)
from app.valuation.engines.standard_dcf import StandardDCFEngine
from app.valuation.fact_reference import SourcedFact, latest_facts
from app.valuation.moat_framework import empty_moat_framework
from app.valuation.relative_multiples import (
    MIN_PEER_SET_SIZE,
    MULTIPLE_KINDS,
    MultipleReading,
    PeerMultiple,
    RelativeMultipleError,
    derive_multiple,
    describe_peer_sample,
    divergence_report,
    implied_value,
    relative_diagnostics,
)
from app.valuation.scenario_definitions import evidence_weighted_probabilities
from app.valuation.scenario_model import Scenario, probability_weighted_value

# Fundamentals a peer (or the subject) may contribute to a multiple. Aliased
# because ingestion writes several names for the same economic quantity.
FUNDAMENTAL_ALIASES: dict[str, tuple[str, ...]] = {
    "eps": ("eps", "eps_diluted"),
    "free_cash_flow": ("free_cash_flow", "normalized_fcf"),
    "revenue": ("revenue",),
    "ebitda": ("ebitda", "normalized_ebitda"),
    "book_value": ("book_value", "common_equity", "total_equity", "equity"),
    "net_income": ("net_income", "profit_loss", "net_profit"),
    "shares_diluted": ("shares_diluted",),
    "total_debt": ("total_debt",),
    "cash_and_equivalents": ("cash_and_equivalents", "cash"),
}

#: Order in which a *headline* multiple is chosen. P/E first because it is
#: what a screen shows, then the enterprise multiples that survive a capital
#: structure the subject and its peers share, then the equity-side cash one.
MULTIPLE_PREFERENCE = (
    "pe",
    "ev_to_ebitda",
    "ev_to_sales",
    "p_to_fcf",
    "ev_to_fcf",
    "pb",
)

#: Metric name template for a provider-sourced multiple: the *peer* ticker is
#: part of the key so a screen's multiples are facts with an owner, and the
#: subject's own multiple uses its own ticker under the same template.
PROVIDER_MULTIPLE_TEMPLATE = "multiple_{kind}_{ticker}"
UNDECLARED_SOURCE = "N/D"

PEER_LIMIT = 8
DIVERGENCE_THRESHOLD = 0.40


def _as_sourced(row: FinancialFact) -> SourcedFact | None:
    """A stored multiple as a sourced fact, or ``None`` if it is unusable.

    A NaN/inf multiple is dropped at the boundary (Postgres ``Numeric`` admits
    them) and a missing source becomes the literal ``"N/D"`` so the trace says
    "nobody declared where this came from" rather than showing an empty string
    a reader has to interpret.
    """
    if row.value is None:
        return None
    value = float(row.value)
    if not math.isfinite(value):
        return None
    return SourcedFact(
        metric=row.metric,
        value=value,
        fact_id=row.id,
        period=row.period,
        confidence=float(row.confidence) if row.confidence is not None else 0.0,
        source_type=(row.source_type or "").strip() or UNDECLARED_SOURCE,
        is_reported=bool(row.is_reported),
    )


def _formula_declaration(spec: dict) -> dict:
    """The exact expression used for one multiple, in both directions.

    Published per kind so a reader can recompute any of the six by hand, and
    generated from the same ``MULTIPLE_KINDS`` entry the arithmetic uses, so
    the documentation cannot drift from the code the way a hand-written string
    in the trace would.
    """
    denominator = spec["denominator"]
    per_share = spec["denominator_basis"] == "per_share"
    if spec["side"] == "equity":
        own = f"price / {denominator}" if per_share else f"price * shares / {denominator}"
        implied = (
            f"multiple * {denominator}"
            if per_share
            else f"multiple * {denominator} / shares"
        )
    else:
        own = f"(price * shares + total_debt - cash_and_equivalents) / {denominator}"
        implied = (
            f"(multiple * {denominator} - total_debt + cash_and_equivalents) / shares"
        )
    return {
        "side": spec["side"],
        "denominator": denominator,
        "denominator_basis": spec["denominator_basis"],
        "own": own,
        "implied": implied,
        "requires_debt_and_cash": spec["requires_debt"],
        "source_of_formula": (
            "app/valuation/relative_multiples.py; the pe / ev_to_fcf / "
            "ev_to_revenue expressions are the same ones "
            "app/services/historical_valuation_service.py computes per year, "
            "verified by test"
        ),
    }


@dataclass(frozen=True)
class _PeerBundle:
    ticker: str
    price: float | None
    price_as_of: str | None
    fundamentals: dict[str, float]
    provider_multiples: dict[str, SourcedFact]


def _insufficient(
    context: ValuationContext, *, missing: list[str], reason: str, extra_trace: dict | None = None
) -> dict:
    result = insufficient_result(
        ticker=context.company.ticker,
        model_type=context.company.valuation_model,
        engine_key=context.engine_key,
        current_price=context.current_price,
        missing_inputs=missing,
        reason=reason,
        snapshot=context.snapshot,
        extra_trace=extra_trace,
    )
    result["moat"] = empty_moat_framework(
        context.company.company_type,
        context.company.factor_tags or [],
        context.company.special_risks or [],
    )
    return result


def _latest_price(db, company: Company) -> tuple[float | None, str | None]:
    """Ultimo cierre del par en la divisa de SUS cuentas (la de sus hechos).

    Un par de Londres cotiza en GBp y reporta en GBP (o USD): el cierre crudo
    en peniques contra un EPS en libras daba un PER x100 que entraba en la
    mediana del grupo. Misma conversion que el screener; sin FX, sin precio.
    """
    row = db.scalar(
        select(MarketPrice)
        .where(MarketPrice.company_id == company.id)
        .order_by(MarketPrice.date.desc())
        .limit(1)
    )
    if row is None or row.close is None:
        return None, None
    converted = close_in_company_currency(
        db, Decimal(str(row.close)), quote_currency=row.quote_currency, company=company, on=row.date
    )
    if converted is None:
        return None, None
    price = float(converted)
    if price <= 0:
        return None, None
    return price, row.date.isoformat()


def _iso_date(value: str | None) -> date | None:
    try:
        return date.fromisoformat((value or "")[:10])
    except ValueError:
        return None


def _fundamentals(db, company_id: int, *, cutoff: date | None = None) -> dict[str, float]:
    """Latest usable fundamental per economic quantity, aliases resolved.

    One query per alias, then first-wins per canonical name. A company that
    stores both ``book_value`` and ``total_equity`` gets whichever the alias
    order prefers, and only that one, so a multiple is never built from a
    mixture of two definitions of the same number.
    """
    resolved: dict[str, float] = {}
    for canonical, aliases in FUNDAMENTAL_ALIASES.items():
        if canonical in resolved:
            continue
        for alias in aliases:
            found = latest_facts(db, company_id, [alias], cutoff=cutoff).get(alias)
            if found is not None:
                resolved[canonical] = found.value
                break
    return resolved


def _provider_multiple_metrics(tickers: list[str]) -> list[str]:
    return [
        PROVIDER_MULTIPLE_TEMPLATE.format(kind=kind, ticker=ticker)
        for ticker in tickers
        for kind in MULTIPLE_KINDS
    ]


def _peer_set(context: ValuationContext) -> tuple[list[Company], dict]:
    """Peers + the provenance of how they were chosen.

    ``PeerComparisonService`` is the existing, scored, traceable selector
    (manual ``PeerRelationship`` overrides first, then a multifactor score on
    industry / business model / tags / size with its own ``selection_trace``).
    Reusing it is deliberate: inventing a second selector here would be a
    second, unauditable definition of "the peers". If it raises, the engine
    refuses instead of falling back to "every company in the database", which
    is not a peer set.
    """
    from app.services.peer_comparison_service import PeerComparisonService

    comparison = PeerComparisonService().compare(
        context.db, context.company, limit=PEER_LIMIT, refresh=False
    )
    ids = {
        row["ticker"]: None
        for row in comparison.get("companies", [])
        if not row.get("is_target")
    }
    if not ids:
        return [], {"basis": comparison.get("basis"), "trace": comparison.get("selection_trace", {})}
    rows = list(
        context.db.scalars(select(Company).where(Company.ticker.in_(list(ids)))).all()
    )
    rows.sort(key=lambda company: company.ticker)
    return rows, {
        "basis": comparison.get("basis"),
        "method": (comparison.get("selection_trace") or {}).get("method"),
        "trace": comparison.get("selection_trace", {}),
        "limit": PEER_LIMIT,
    }


class RelativeMultiplesEngine(ValuationEngine):
    """Peer-multiple screen across P/E, EV/EBITDA, EV/Sales, P/B, P/FCF, EV/FCF.

    bear/base/bull are the peer 25th / median / 75th percentile of the
    *headline* multiple applied to the subject's own fundamentals. Every other
    multiple is published as a diagnostic with its own percentile, caveats and
    implied price, and the gap against the standard DCF is reported rather than
    resolved.
    """

    key = "relative"

    def value(self, context: ValuationContext) -> dict:
        company = context.company
        model_type = company.valuation_model or "relative_multiples"
        snapshot = context.snapshot

        if is_adr_without_ratio(company):
            return _insufficient(
                context,
                missing=["adr_ratio"],
                reason=(
                    f"{company.ticker} is quoted as an ADR but the "
                    "ordinary-shares-per-ADR ratio is unknown, so a peer "
                    "multiple on the listed share and on the filing's ordinary "
                    "share are not on the same basis."
                ),
                extra_trace={"model_type": model_type, "engine": self.key},
            )

        own_fundamentals = _fundamentals(context.db, company.id, cutoff=context_split_cutoff(context))
        shares = own_fundamentals.get("shares_diluted")
        if shares is None or shares <= 0:
            return _insufficient(
                context,
                missing=["shares_diluted"],
                reason=(
                    "A relative multiple needs diluted shares: without them the "
                    "enterprise-value side and the per-share value are both "
                    "unavailable, and a P/E is the only reading left, which is "
                    "not enough to run a screen."
                ),
                extra_trace={"own_fundamentals_available": sorted(own_fundamentals)},
            )
        if context.current_price is None or context.current_price <= 0:
            return _insufficient(
                context,
                missing=["current_price"],
                reason=(
                    "The subject's own multiple is price / fundamental. Without "
                    "a real stored price there is no own multiple, only peer "
                    "implied values with nothing to compare them to."
                ),
            )

        peers, peer_provenance = _peer_set(context)
        if not peers:
            return _insufficient(
                context,
                missing=["peer_multiples"],
                reason=(
                    "No peer set. A relative multiple is a statement about the "
                    "peers, so without them there is no statement: a peer "
                    "multiple is never estimated or filled in."
                ),
                extra_trace={
                    "peer_set": peer_provenance,
                    "peer_input_contract": {
                        "selection": "PeerComparisonService (manual overrides, then PEER_SELECTION_V2)",
                        "provider_multiple": PROVIDER_MULTIPLE_TEMPLATE.format(
                            kind="<kind>", ticker="<peer ticker>"
                        ),
                        "otherwise": "derived from the peer's own price and facts",
                    },
                },
            )

        bundles = self._peer_bundles(context, peers)
        screens: dict[str, dict] = {}
        peer_blocks: list[dict] = []
        small_samples: list[str] = []
        undeclared: list[str] = []
        for kind in MULTIPLE_PREFERENCE:
            own_reading = self._own_reading(kind, context, own_fundamentals)
            usable, rejected = self._peer_multiples(kind, bundles)
            stats = describe_peer_sample(usable)
            if not usable:
                screens[kind] = {
                    "multiple": kind,
                    "status": "no_peer_multiple",
                    "own": own_reading.as_trace(),
                    "peer_stats": stats,
                    "implied_value_per_share": {"p25": None, "median": None, "p75": None},
                    "rejected_peers": rejected,
                    "caveats": [
                        "No peer has a usable multiple of this kind: the screen "
                        "is not run rather than run on one name."
                    ],
                }
                continue
            implied, implied_notes = self._implied(
                kind, usable[0].value, stats, context, own_fundamentals
            )
            diagnostics = relative_diagnostics(
                kind=kind,
                own=own_reading,
                peers=usable,
                peer_stats=stats,
                implied_prices=implied,
            )
            diagnostics["implied_price_notes"] = implied_notes
            peer_blocks.append(
                {
                    "multiple": kind,
                    "peer_set_size": stats["peer_set_size"],
                    "median": stats["median"],
                    "p25": stats["p25"],
                    "p75": stats["p75"],
                    "peers": stats["peers"],
                    "rejected_peers": rejected,
                    "sample_note": stats["sample_note"],
                }
            )
            screens[kind] = {
                "multiple": kind,
                "status": "ok",
                "own": own_reading.as_trace(),
                "peer_stats": stats,
                **diagnostics,
                "rejected_peers": rejected,
            }
            if stats["is_small_sample"]:
                small_samples.append(kind)
            undeclared.extend(peer.ticker for peer in usable if peer.source == UNDECLARED_SOURCE)

        headline = self._headline(screens)
        if headline is None:
            return _insufficient(
                context,
                missing=["peer_multiples"],
                reason=(
                    "Peers exist but none of the six multiples can be applied: "
                    "either no peer has the fundamentals it needs or the "
                    "subject's own denominator is unusable. A screen with an "
                    "empty result set is not a cheap stock."
                ),
                extra_trace={
                    "peer_set": peer_provenance,
                    "peer_multiples": peer_blocks,
                    "screens": screens,
                },
            )

        kind = headline["multiple"]
        implied = headline["implied_value_per_share"]
        bear_value = implied["p25"]
        base_value = implied["median"]
        bull_value = implied["p75"]
        ratio = adr_ratio(company)
        comparable_price = context.current_price / ratio if (ratio and context.current_price) else context.current_price

        blockers: list[str] = []
        if len(headline["peer_stats"]["peers"]) < MIN_PEER_SET_SIZE:
            blockers.append("peer_set_below_five")
        if undeclared:
            blockers.append("peer_multiple_source_undeclared")
        divergence = self._divergence(context, base_value)
        if divergence.get("warning"):
            blockers.append("dcf_relative_divergence")

        own = headline["own"]
        directional = 0.0
        if own.get("value") and headline["peer_stats"]["median"]:
            directional = max(
                -1.0,
                min(1.0, (headline["peer_stats"]["median"] / own["value"] - 1.0) * 2),
            )
        probabilities = evidence_weighted_probabilities(
            evidence_confidence=self._evidence_confidence(context, own_fundamentals),
            directional_signal=directional,
            downside_risk=0.0 if own.get("status") == "ok" else 0.5,
        )
        weighted = probability_weighted_value(
            [
                Scenario("bear", probabilities["bear"], bear_value),
                Scenario("base", probabilities["base"], base_value),
                Scenario("bull", probabilities["bull"], bull_value),
            ]
        )
        expected = weighted["expected_value"]

        sensitivity = {
            "rows": [
                {
                    "scenario": label,
                    "multiple": kind,
                    "applied_multiple": multiple,
                    "peer_basis": basis,
                    "implied_value_per_share": value,
                    "value_per_share": value,
                }
                for label, basis, multiple, value in (
                    ("peer_p25", "p25", headline["peer_stats"]["p25"], bear_value),
                    ("peer_median", "median", headline["peer_stats"]["median"], base_value),
                    ("peer_p75", "p75", headline["peer_stats"]["p75"], bull_value),
                )
            ],
            "trace": {"method": "relative_multiple_percentile_sensitivity", "multiple": kind},
        }

        return apply_publication_blockers(
            {
                "ticker": company.ticker,
                "model_type": model_type,
                "status": "ok",
                "publishable": True,
                "current_price": context.current_price,
                "bear_value": bear_value,
                "base_value": base_value,
                "bull_value": bull_value,
                "expected_value": expected,
                "margin_of_safety": margin_of_safety(expected, comparable_price),
                "missing_inputs": [],
                "publication_blockers": blockers,
                "adr_ratio": ratio,
                "value_per_share_basis": "ordinary_share",
                "listed_share_values": (
                    {
                        "bear": bear_value * ratio,
                        "base": base_value * ratio,
                        "bull": bull_value * ratio,
                        "expected": expected * ratio,
                    }
                    if ratio
                    else None
                ),
                "comparable_price_basis": "ordinary_share" if ratio else "listed_share",
                "reverse_dcf": {},
                "sensitivity": sensitivity,
                "relative": {
                    "headline_multiple": kind,
                    "own_multiple": own,
                    "peer_median": headline["peer_stats"]["median"],
                    "peer_p25": headline["peer_stats"]["p25"],
                    "peer_p75": headline["peer_stats"]["p75"],
                    "peer_set_size": headline["peer_stats"]["peer_set_size"],
                    "implied_value_per_share": implied,
                    "dcf_vs_relative_divergence": divergence,
                },
                "moat": empty_moat_framework(
                    company.company_type, company.factor_tags or [], company.special_risks or []
                ),
                "trace": {
                    "method": model_type,
                    "engine": self.key,
                    "input_source": "peer_multiples_and_financial_facts",
                    "publishable": True,
                    "status": "ok",
                    "model_version": MODEL_VERSION,
                    "scenario_style": "relative_peer_percentiles",
                    "multiple_kinds": sorted(MULTIPLE_KINDS),
                    "headline_multiple": kind,
                    "headline_rule": (
                        "First multiple in MULTIPLE_PREFERENCE with a usable own "
                        "reading and at least one peer multiple."
                    ),
                    "peer_set": peer_provenance,
                    "peer_set_size": headline["peer_stats"]["peer_set_size"],
                    "peer_set_minimum": MIN_PEER_SET_SIZE,
                    "small_peer_sets": small_samples,
                    "peer_multiples": peer_blocks,
                    "peers_without_declared_source": sorted(set(undeclared)),
                    "own_fundamentals": own_fundamentals,
                    "own_shares_period": snapshot.shares_period,
                    "dcf_vs_relative_divergence": divergence,
                    "divergence_threshold": DIVERGENCE_THRESHOLD,
                    "sensitivity": sensitivity,
                    "probabilities": probabilities,
                    "probability_method": "source_confidence_plus_multiple_gap",
                    "evidence_confidence": self._evidence_confidence(
                        context, own_fundamentals
                    ),
                    "publication_blockers": blockers,
                    "fact_ids": snapshot.fact_ids(),
                    "periods": snapshot.periods(),
                    "snapshot": {
                        "as_of": snapshot.as_of_period,
                        "income_statement": snapshot.income_statement,
                        "balance_sheet": snapshot.balance_sheet,
                        "shares": snapshot.shares_period,
                        "warnings": snapshot.warnings,
                    },
                    "screens": screens,
                    "weighted": weighted["trace"],
                    "formulas": {
                        kind_name: _formula_declaration(spec)
                        for kind_name, spec in MULTIPLE_KINDS.items()
                    },
                },
            }
        )

    # ------------------------------------------------------------------
    # Peer plumbing
    # ------------------------------------------------------------------

    def _peer_bundles(self, context: ValuationContext, peers: list[Company]) -> dict[str, _PeerBundle]:
        """Price + fundamentals + provider multiples for every peer, 3 queries."""
        tickers = [peer.ticker for peer in peers]
        prices: dict[int, tuple[float | None, str | None]] = {
            peer.id: _latest_price(context.db, peer) for peer in peers
        }
        fundamentals: dict[int, dict[str, float]] = {
            # Cada par en la base de SU ultimo cierre (splits posteriores fuera).
            peer.id: _fundamentals(context.db, peer.id, cutoff=_iso_date(prices[peer.id][1]))
            for peer in peers
        }
        # The metric name embeds the ticker, so the lookup is keyed by the
        # generated name rather than by parsing it back: a peer ticker with an
        # underscore in it would silently lose its prefix here.
        provider_rows = {
            row.metric: row
            for row in context.db.scalars(
                select(FinancialFact).where(
                    FinancialFact.metric.in_(_provider_multiple_metrics(tickers))
                )
            ).all()
        }
        bundles: dict[str, _PeerBundle] = {}
        for peer in peers:
            price, price_as_of = prices.get(peer.id, (None, None))
            # Un par ADR se mide igual que la propia: precio por ordinaria. Un
            # par marcado ADR sin ratio no tiene precio comparable (rechazado).
            if is_adr_without_ratio(peer):
                price = None
            else:
                price, _peer_ratio = adr_comparable_price(peer, price)
            stored: dict[str, SourcedFact] = {}
            for kind in MULTIPLE_KINDS:
                row = provider_rows.get(
                    PROVIDER_MULTIPLE_TEMPLATE.format(kind=kind, ticker=peer.ticker)
                )
                sourced = _as_sourced(row) if row is not None else None
                if sourced is not None:
                    stored[kind] = sourced
            bundles[peer.ticker] = _PeerBundle(
                ticker=peer.ticker,
                price=price,
                price_as_of=price_as_of,
                fundamentals=fundamentals.get(peer.id, {}),
                provider_multiples=stored,
            )
        return bundles

    def _peer_multiples(
        self, kind: str, bundles: dict[str, _PeerBundle]
    ) -> tuple[list[PeerMultiple], list[dict]]:
        """Peer multiples of one kind, with the rejected peers named.

        A rejected peer is not dropped silently: "this company had no price
        stored" is different from "this company is loss-making so its P/E is
        meaningless", and the difference belongs in the trace.
        """
        usable: list[PeerMultiple] = []
        rejected: list[dict] = []
        for ticker, bundle in sorted(bundles.items()):
            stored = bundle.provider_multiples.get(kind)
            if stored is not None:
                if stored.value <= 0:
                    rejected.append(
                        {
                            "ticker": ticker,
                            "multiple": kind,
                            "reason": "stored provider multiple is not positive",
                            "stored_value": stored.value,
                        }
                    )
                    continue
                usable.append(
                    PeerMultiple(
                        ticker=ticker,
                        kind=kind,
                        value=stored.value,
                        source=stored.source_type or UNDECLARED_SOURCE,
                        as_of=stored.period,
                        method="provider_reported",
                    )
                )
                continue
            price = bundle.price
            if price is None or bundle.fundamentals.get("shares_diluted") in (None, 0):
                rejected.append(
                    {
                        "ticker": ticker,
                        "multiple": kind,
                        "reason": "no stored market price or no diluted shares",
                    }
                )
                continue
            reading = derive_multiple(
                kind,
                price=price,
                shares=bundle.fundamentals["shares_diluted"],
                fundamentals=bundle.fundamentals,
                total_debt=bundle.fundamentals.get("total_debt"),
                cash=bundle.fundamentals.get("cash_and_equivalents"),
            )
            if reading.value is None:
                rejected.append(
                    {"ticker": ticker, "multiple": kind, "reason": reading.reason, "status": reading.status}
                )
                continue
            usable.append(
                PeerMultiple(
                    ticker=ticker,
                    kind=kind,
                    value=reading.value,
                    source="financial_facts",
                    as_of=bundle.price_as_of or "N/D",
                    method="derived_from_facts",
                )
            )
        return usable, rejected

    @staticmethod
    def _comparable_price(context: ValuationContext) -> float | None:
        """Precio por accion ORDINARIA (ADR: precio / ratio), la base de los hechos.

        El multiplo propio (PER, EV/...) se calcula con EPS y acciones por
        ordinaria: con el precio del ADR salia N veces caro frente a los pares
        y el percentil del multiplo propio quedaba falseado (BABA 8:1).
        """
        comparable, _ratio = adr_comparable_price(context.company, context.current_price)
        return comparable

    def _own_reading(
        self, kind: str, context: ValuationContext, fundamentals: dict[str, float]
    ) -> MultipleReading:
        # nosemgrep: gerarai-money-none-to-zero -- derive_multiple devuelve lectura no disponible con price <= 0; un precio desconocido no produce multiplo
        price = float(self._comparable_price(context) or 0.0)
        return derive_multiple(
            kind,
            price=price,
            shares=fundamentals["shares_diluted"],
            fundamentals=fundamentals,
            total_debt=fundamentals.get("total_debt"),
            cash=fundamentals.get("cash_and_equivalents"),
        )

    def _implied(
        self,
        kind: str,
        peer_multiple: float,
        stats: dict,
        context: ValuationContext,
        fundamentals: dict[str, float],
    ) -> tuple[dict[str, float | None], list[str]]:
        """Implied price at p25/median/p75, plus why a cell is empty.

        An empty cell is not a zero: it is either a missing own denominator or
        a non-positive earnings denominator, and the two are recorded
        separately so the screen can say "N/D because it is loss-making"
        instead of silently dropping the multiple.
        """
        out: dict[str, float | None] = {}
        notes: list[str] = []
        for label in ("p25", "median", "p75"):
            multiple = stats.get(label)
            if multiple is None:
                out[label] = None
                continue
            try:
                out[label] = implied_value(
                    kind=kind,
                    peer_multiple=multiple,
                    fundamentals=fundamentals,
                    # nosemgrep: gerarai-money-none-to-zero -- derive_multiple devuelve lectura no disponible con price <= 0; un precio desconocido no produce multiplo
                    price=float(self._comparable_price(context) or 0.0),
                    shares=fundamentals["shares_diluted"],
                    total_debt=fundamentals.get("total_debt"),
                    cash=fundamentals.get("cash_and_equivalents"),
                )
            except RelativeMultipleError as err:
                out[label] = None
                note = f"{kind} implied price unavailable: {err.reason}"
                if note not in notes:
                    notes.append(note)
        return out, notes

    def _headline(self, screens: dict[str, dict]) -> dict | None:
        for kind in MULTIPLE_PREFERENCE:
            screen = screens.get(kind)
            if screen is None or screen.get("status") != "ok":
                continue
            implied = screen.get("implied_value_per_share") or {}
            if implied.get("median") is None or implied.get("p25") is None or implied.get("p75") is None:
                continue
            if not screen.get("peer_stats", {}).get("peers"):
                continue
            return screen
        return None

    def _divergence(self, context: ValuationContext, relative_value: float) -> dict:
        """Run the standard DCF on the same context and publish the gap.

        A relative engine that never disagrees with a DCF is either right or
        one of them is being ignored. Running ``StandardDCFEngine`` on the same
        ``ValuationContext`` costs one extra valuation and is the only way the
        product can point at its own contradiction instead of choosing a
        winner.
        """
        if not context.snapshot.coherent:
            return divergence_report(
                intrinsic_value=None,
                relative_value=relative_value,
                current_price=context.current_price,
            )
        try:
            intrinsic = StandardDCFEngine().value(context)
        except Exception:  # noqa: BLE001 - a sanity check must never break a valuation
            return divergence_report(
                intrinsic_value=None,
                relative_value=relative_value,
                current_price=context.current_price,
            )
        intrinsic_value = intrinsic.get("expected_value")
        if intrinsic_value is None:
            report = divergence_report(
                intrinsic_value=None,
                relative_value=relative_value,
                current_price=context.current_price,
            )
            report["reason"] = (
                f"The FCFF DCF on this same snapshot returned "
                f"status={intrinsic.get('status')} with no expected value."
            )
            return report
        report = divergence_report(
            intrinsic_value=float(intrinsic_value),
            relative_value=relative_value,
            current_price=context.current_price,
            threshold=DIVERGENCE_THRESHOLD,
        )
        report["dcf_status"] = intrinsic.get("status")
        report["dcf_traceable_wacc"] = intrinsic.get("publication_blockers", [])
        return report

    def _evidence_confidence(
        self, context: ValuationContext, fundamentals: dict[str, float]
    ) -> float:
        rows = latest_facts(
            context.db,
            context.company.id,
            sorted({alias for group in FUNDAMENTAL_ALIASES.values() for alias in group}),
        )
        if not rows:
            return 0.0
        return sum(fact.confidence for fact in rows.values()) / len(rows)
