"""Pure relative-multiples primitives: derive, rank, and apply peer multiples.

No DB. The engine resolves the peer set and the peer fundamentals; everything
here is arithmetic on numbers the caller already has, so a test can check a
median and a percentile against values computed by hand.

The three multipliers that decide a screening
--------------------------------------------

A relative multiple is a statement of the form *"this company should trade
where its peers trade, on the same fundamental"*. Three things have to be true
for that statement to mean anything, and each one is a way the method lies:

1. **The peer set was not chosen backwards.** Any peer set can be made to
   "justify" a price: pick the peers that agree and the multiple becomes proof.
   So the peer set's provenance travels with the answer
   (``peer_set_source``) and its size is published (``peer_set_size``) rather
   than presented as "the sector".
2. **The multiple means something.** ``P/E`` on a loss-making company is a
   negative ratio, not a cheap share: a −20x P/E is not a bargain, it is the
   absence of the denominator. Those multiples are returned as ``None`` with a
   reason, never as a number.
3. **The median of five points is not a statistic.** With ``n < 5`` the median
   is one observation's luck. It is still reported — the alternative is
   refusing every small-cap screen there is — but it is labelled, and the
   label travels into ``publication_blockers``.

Formulas, and why they are the ones already in the codebase
------------------------------------------------------------

``pe = price / eps`` and ``ev_to_x = (price * shares + debt - cash) / x`` are
the formulas ``HistoricalValuationService`` already uses per year
(``app/services/historical_valuation_service.py``: ``"pe": self._multiple(price, eps)``,
``"ev_to_fcf": self._multiple(enterprise_value, fcf)``, N/D when either side is <= 0). They are re-declared here
as pure functions rather than imported so the module stays DB-free, and
``tests/test_relative_multiples_engine.py`` asserts that the two agree on the
same inputs, so this is a *shared* primitive and not a second opinion.
``ev_to_ebitda`` follows the same shape with ``ebitda`` in the denominator, and
``p_to_fcf = price / fcf_per_share`` is the equity-side of ``ev_to_fcf``
(``equity_value = EV - net_debt``, so they differ by exactly the leverage).

Percentiles
-----------

Linear interpolation between order statistics, identical to
``HistoricalValuationService._percentile`` (``quantile * (n-1)`` with linear
weighting) so a percentile read here and a percentile read from the historical
chart are the same number.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

# Below this many peers the median is one company's luck, not a sector's.
MIN_PEER_SET_SIZE = 5
# Below this, even the 25th/75th percentile is a rounding artifact of one name.
MIN_MEANINGFUL_PEER_SET_SIZE = 3

#: The multiple kinds this engine knows how to derive, with the fundamentals
#: each one needs. ``side`` marks the numerator side (price x shares or
#: price) versus the ``enterprise`` side (EV), so a derived multiple can never
#: silently mix a price with an enterprise value. ``denominator_basis`` marks
#: whether the denominator is already a per-share figure (EPS) or an aggregate
#: one (book value, cash flow, EBITDA, revenue), which is what decides whether
#: ``shares`` enters the division. Getting it wrong is a factor-of-shares
#: error, so it is declared per kind rather than guessed.
MULTIPLE_KINDS: dict[str, dict] = {
    "pe": {
        "side": "equity",
        "denominator": "eps",
        "denominator_basis": "per_share",
        "requires_debt": False,
    },
    "pb": {
        "side": "equity",
        "denominator": "book_value",
        "denominator_basis": "aggregate",
        "requires_debt": False,
    },
    "p_to_fcf": {
        "side": "equity",
        "denominator": "free_cash_flow",
        "denominator_basis": "aggregate",
        "requires_debt": False,
    },
    "ev_to_ebitda": {
        "side": "enterprise",
        "denominator": "ebitda",
        "denominator_basis": "aggregate",
        "requires_debt": True,
    },
    "ev_to_sales": {
        "side": "enterprise",
        "denominator": "revenue",
        "denominator_basis": "aggregate",
        "requires_debt": True,
    },
    "ev_to_fcf": {
        "side": "enterprise",
        "denominator": "free_cash_flow",
        "denominator_basis": "aggregate",
        "requires_debt": True,
    },
}

#: Multiples whose denominator is an earnings/profit figure: a negative
#: denominator makes the ratio meaningless (not "cheap"), while a negative
#: *numerator* is impossible for these three.
_EARNINGS_DENOMINATORS = frozenset({"eps", "ebitda", "free_cash_flow"})


class RelativeMultipleError(ValueError):
    """A relative-multiple input that makes the comparison meaningless."""

    def __init__(self, missing_input: str, reason: str) -> None:
        super().__init__(reason)
        self.missing_input = missing_input
        self.reason = reason


@dataclass(frozen=True)
class PeerMultiple:
    """One peer's multiple with the provenance a screening has to publish."""

    ticker: str
    kind: str
    value: float
    source: str
    as_of: str
    method: str

    def as_trace(self) -> dict:
        return {
            "ticker": self.ticker,
            "multiple": self.kind,
            "value": self.value,
            "source": self.source,
            "as_of": self.as_of,
            "method": self.method,
        }


@dataclass(frozen=True)
class MultipleReading:
    """A multiple for the subject company, or the reason there is not one."""

    kind: str
    value: float | None
    status: str
    reason: str | None = None
    source: str = "derived_from_facts"
    as_of: str | None = None

    def as_trace(self) -> dict:
        return {
            "multiple": self.kind,
            "value": self.value,
            "status": self.status,
            "reason": self.reason,
            "source": self.source,
            "as_of": self.as_of,
        }


def enterprise_value(
    *, price: float, shares: float, total_debt: float, cash: float
) -> float:
    """``EV = market cap + total debt - cash``.

    Same expression as ``HistoricalValuationService`` (which computes
    ``market_cap + debt - cash``). Debt and cash are **required**: a missing
    debt fact is not zero debt, and defaulting it to 0.0 would produce an
    enterprise value equal to the market cap and then a multiple that looks
    cheap purely because the debt was ignored.
    """
    if shares <= 0:
        raise RelativeMultipleError(
            "positive_shares_diluted",
            f"shares_diluted is {shares}: no market capitalisation is computable.",
        )
    if price <= 0:
        raise RelativeMultipleError(
            "positive_market_price",
            f"price is {price}: a relative multiple on a non-positive price is not a multiple.",
        )
    return price * shares + total_debt - cash


def derive_multiple(
    kind: str,
    *,
    price: float,
    shares: float,
    fundamentals: dict[str, float],
    total_debt: float | None = None,
    cash: float | None = None,
) -> MultipleReading:
    """Derive one multiple for one company from its price and fundamentals.

    Returns a ``MultipleReading`` rather than ``float | None`` because "no
    multiple" has two very different reasons — a missing fact and a
    meaningless ratio — and the second is the one a reader must be told about
    explicitly instead of being handed as a zero.
    """
    spec = MULTIPLE_KINDS.get(kind)
    if spec is None:
        raise RelativeMultipleError(
            "known_multiple_kind",
            f"{kind!r} is not a multiple this engine derives; known kinds are "
            f"{sorted(MULTIPLE_KINDS)}.",
        )
    denominator_metric = spec["denominator"]
    denominator = fundamentals.get(denominator_metric)
    if denominator is None:
        return MultipleReading(
            kind=kind,
            value=None,
            status="missing_denominator",
            reason=f"No {denominator_metric} fact: the multiple cannot be derived.",
        )
    if denominator_metric in _EARNINGS_DENOMINATORS and denominator <= 0:
        return MultipleReading(
            kind=kind,
            value=None,
            status="not_meaningful",
            reason=(
                f"{denominator_metric} is {denominator:.4f}: the ratio is "
                "N/D, not a number. A negative denominator makes the multiple "
                "negative, which screens as 'cheap' and means nothing."
            ),
        )
    if denominator_metric not in _EARNINGS_DENOMINATORS and denominator <= 0:
        return MultipleReading(
            kind=kind,
            value=None,
            status="not_meaningful",
            reason=f"{denominator_metric} is {denominator:.4f}: not a usable denominator.",
        )
    if spec["requires_debt"] and (total_debt is None or cash is None):
        return MultipleReading(
            kind=kind,
            value=None,
            status="missing_denominator",
            reason=(
                "An enterprise-value multiple needs total_debt AND "
                "cash_and_equivalents: a missing debt fact is unknown "
                "leverage, not zero leverage."
            ),
        )
    if spec["side"] == "equity":
        if price <= 0:
            return MultipleReading(
                kind=kind,
                value=None,
                status="missing_denominator",
                reason="No positive market price to divide by.",
            )
        numerator = price if spec["denominator_basis"] == "per_share" else price * shares
        value = numerator / denominator
    else:
        assert total_debt is not None and cash is not None
        value = enterprise_value(
            price=price, shares=shares, total_debt=total_debt, cash=cash
        ) / denominator
    if not math.isfinite(value):
        return MultipleReading(
            kind=kind,
            value=None,
            status="not_meaningful",
            reason="Derived multiple is not finite.",
        )
    return MultipleReading(kind=kind, value=value, status="ok")


def percentile(values: list[float], quantile: float) -> float:
    """Linear-interpolated percentile of an already sorted-or-not list.

    ``quantile * (n - 1)`` with linear weighting, the same expression as
    ``HistoricalValuationService._percentile`` (which is written on ``Decimal``
    there and on ``float`` here; the two agree because both are exact linear
    interpolation between the same order statistics).
    """
    if not values:
        raise RelativeMultipleError("non_empty_sample", "A percentile needs at least one value.")
    if not 0.0 <= quantile <= 1.0:
        raise RelativeMultipleError("quantile_in_zero_one", f"quantile {quantile} is outside [0, 1].")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = quantile * (len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def median(values: list[float]) -> float:
    """Median by the usual midpoint rule (no interpolation for even ``n``).

    Matches ``PeerComparisonService._median``, which averages the two central
    order statistics for even ``n`` and takes the middle one for odd ``n``.
    """
    if not values:
        raise RelativeMultipleError("non_empty_sample", "A median needs at least one value.")
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) / 2


def describe_peer_sample(peers: list[PeerMultiple]) -> dict:
    """Median/quartiles of a peer set plus the small-sample verdict.

    The verdict is the important field. ``n = 3`` produces a median, a 25th and
    a 75th percentile, and all three are one company's luck wearing a
    statistic's clothes.
    """
    values = [peer.value for peer in peers]
    size = len(values)
    stats = {
        "peer_set_size": size,
        "minimum_peers": MIN_PEER_SET_SIZE,
        "is_small_sample": size < MIN_PEER_SET_SIZE,
        "is_statistically_meaningful": size >= MIN_MEANINGFUL_PEER_SET_SIZE,
        "peers": [peer.as_trace() for peer in peers],
    }
    if size == 0:
        return {
            **stats,
            "median": None,
            "p25": None,
            "p75": None,
            "minimum": None,
            "maximum": None,
            "sample_note": "No peer with a usable multiple: the peer set is empty, not zero-valued.",
        }
    stats.update(
        {
            "median": median(values),
            "p25": percentile(values, 0.25),
            "p75": percentile(values, 0.75),
            "minimum": min(values),
            "maximum": max(values),
        }
    )
    if size < MIN_MEANINGFUL_PEER_SET_SIZE:
        note = (
            f"Only {size} peer(s) with a usable multiple: every statistic below "
            "is one company's reading, not a distribution."
        )
    elif size < MIN_PEER_SET_SIZE:
        note = (
            f"{size} peers is below the {MIN_PEER_SET_SIZE} needed for the median "
            "to carry information about the distribution; the peer set is a "
            "sample of convenience, not a sector."
        )
    else:
        note = f"{size} peers: the median is a usable central estimate."
    stats["sample_note"] = note
    return stats


def peer_percentile_of(own: float, peers: list[PeerMultiple]) -> float:
    """Share of the peer set trading **below** the subject's own multiple.

    ``0.0`` = cheapest of the set, ``1.0`` = most expensive. Uses the strict
    share rather than an interpolated quantile because a percentile of a
    handful of points invites false precision; the count behind it is returned
    by the caller and published as ``peers_below``.
    """
    values = [peer.value for peer in peers]
    if not values:
        raise RelativeMultipleError("non_empty_sample", "No peers to rank against.")
    return sum(1 for value in values if value < own) / len(values)


def implied_value(
    *,
    kind: str,
    peer_multiple: float,
    fundamentals: dict[str, float],
    price: float,
    shares: float,
    total_debt: float | None = None,
    cash: float | None = None,
) -> float:
    """Value per share obtained by applying a peer multiple to own fundamentals.

    The inverse of ``derive_multiple``, solved for price:

    * equity-side ``P/E``:    ``price = multiple * eps``
    * equity-side ``P/B``:    ``price = multiple * book_value / shares``
    * equity-side ``P/FCF``:  ``price = multiple * free_cash_flow / shares``
    * enterprise-side:        ``price = (multiple * denominator - debt + cash) / shares``

    Two failure modes are refusals, not numbers:

    * an enterprise multiple with no debt/cash term: the multiple prices the
      *enterprise* and the equity is what is left after the debt, so applying a
      peer EV/EBITDA straight to a more levered company and calling the result a
      share price is a straight valuation error;
    * a non-positive earnings denominator: applying a peer P/E to a
      loss-making company returns a *negative price*, which reads as a deep
      discount instead of as the absence of the denominator.
    """
    spec = MULTIPLE_KINDS.get(kind)
    if spec is None:
        raise RelativeMultipleError(
            "known_multiple_kind",
            f"{kind!r} is not a known multiple kind.",
        )
    if peer_multiple is None or not math.isfinite(peer_multiple) or peer_multiple < 0:
        raise RelativeMultipleError(
            "non_negative_peer_multiple",
            f"peer multiple is {peer_multiple}: it cannot be applied.",
        )
    if shares <= 0:
        raise RelativeMultipleError(
            "positive_shares_diluted",
            f"shares_diluted is {shares}: there is no per-share value.",
        )
    denominator_metric = spec["denominator"]
    denominator = fundamentals.get(denominator_metric)
    if denominator is None:
        raise RelativeMultipleError(
            f"own_{denominator_metric}",
            f"Applying a peer {kind} needs the company's own {denominator_metric}.",
        )
    if denominator_metric in _EARNINGS_DENOMINATORS and denominator <= 0:
        raise RelativeMultipleError(
            f"own_{denominator_metric}_positive",
            f"own {denominator_metric} is {denominator:.4f}: applying a peer {kind} "
            "to it returns a negative price, which reads as a deep discount "
            "instead of as the absence of the denominator. This multiple is N/D "
            "for the subject.",
        )
    if spec["side"] == "equity":
        if spec["denominator_basis"] == "per_share":
            return peer_multiple * denominator
        return peer_multiple * denominator / shares
    if total_debt is None or cash is None:
        raise RelativeMultipleError(
            "net_debt",
            f"An implied {kind} needs total_debt AND cash_and_equivalents to "
            "convert an enterprise value into an equity value.",
        )
    return (peer_multiple * denominator - total_debt + cash) / shares


def relative_diagnostics(
    *,
    kind: str,
    own: MultipleReading,
    peers: list[PeerMultiple],
    peer_stats: dict,
    implied_prices: dict[str, float | None],
) -> dict:
    """Percentile of the own multiple, implied prices and the honest caveats.

    Returned per multiple so a screen with six multipliers publishes six
    independent verdicts; a single blended "the stock is 12% cheap" hides the
    fact that only two of the six denominators exist.
    """
    rank: dict | None = None
    if own.value is not None and peers:
        size = len(peers)
        below = round(peer_percentile_of(own.value, peers) * size)
        values = [peer.value for peer in peers]
        rank = {
            "percentile_of_peer_set": below / size,
            "peers_below": below,
            "peer_set_size": size,
            "cheapest_of_set": own.value <= min(values),
            "most_expensive_of_set": own.value >= max(values),
            "percentile_note": (
                f"{size} peers ranked by a strict count of those trading below "
                "the subject; the resolution of this percentile is "
                f"{1 / size:.0%}, so treat it as a bucket, not a measurement."
            ),
        }
    caveats: list[str] = []
    if own.status == "not_meaningful":
        caveats.append(f"own {kind} is N/D: {own.reason}")
    if own.status == "missing_denominator":
        caveats.append(f"own {kind} not derived: {own.reason}")
    if peer_stats.get("is_small_sample"):
        caveats.append(peer_stats.get("sample_note") or "small peer sample")
    unsourced = [peer.ticker for peer in peers if peer.source in (None, "", "N/D")]
    if unsourced:
        caveats.append(
            "peers without a declared source of the multiple: " + ", ".join(sorted(unsourced))
        )
    return {
        "multiple": kind,
        "own": own.as_trace(),
        "rank": rank,
        "implied_value_per_share": implied_prices,
        "caveats": caveats,
    }


def divergence_report(
    *,
    intrinsic_value: float | None,
    relative_value: float | None,
    current_price: float | None = None,
    threshold: float = 0.40,
    intrinsic_label: str = "dcf",
    relative_label: str = "relative",
) -> dict:
    """Compare a DCF/intrinsic value against the peer-implied value.

    A relative multiple is the easiest valuation method to lie with, because
    the peer set can be chosen until the answer agrees with the price. The
    honest response is not to pick one, it is to publish the contradiction:
    when the two methods disagree by more than ``threshold`` the trace says so
    in words, and the direction of the gap says which one the reader should be
    more suspicious of (a huge DCF and a low peer multiple usually means the
    forecast is the outlier; a tiny DCF and a rich peer set usually means the
    peers are).
    """
    if intrinsic_value is None or relative_value is None:
        return {
            "status": "unavailable",
            "gap": None,
            "gap_pct": None,
            "warning": None,
            "reason": (
                f"No {intrinsic_label} value available on the same context, so "
                f"the {relative_label} screen has nothing to disagree with."
            ),
        }
    if intrinsic_value == 0:
        return {
            "status": "unavailable",
            "gap": None,
            "gap_pct": None,
            "warning": None,
            "reason": "Intrinsic value is zero: a percentage gap is undefined.",
        }
    gap = relative_value - intrinsic_value
    gap_pct = gap / abs(intrinsic_value)
    warned = abs(gap_pct) > threshold
    if not warned:
        text = (
            f"{relative_label} and {intrinsic_label} agree within "
            f"{abs(gap_pct):.0%} (threshold {threshold:.0%})."
        )
    elif gap_pct > 0:
        text = (
            f"{relative_label} is {gap_pct:.0%} ABOVE {intrinsic_label}. Either the "
            "peers are more expensive than the cash flows justify, or the "
            f"{intrinsic_label} forecast is too low. Both readings are published "
            "because the peer set is the part that was chosen and the forecast "
            "is the part that was not."
        )
    else:
        text = (
            f"{relative_label} is {abs(gap_pct):.0%} BELOW {intrinsic_label}. Either the "
            "peers are cheaper than the cash flows justify, or the "
            f"{intrinsic_label} forecast is too high. The two cannot both be right."
        )
    return {
        "status": "ok",
        "intrinsic_label": intrinsic_label,
        "relative_label": relative_label,
        "intrinsic_value": intrinsic_value,
        "relative_value": relative_value,
        "gap": gap,
        "gap_pct": gap_pct,
        "threshold": threshold,
        "warning": warned,
        "text": text,
        "current_price": current_price,
        "price_sided": (
            "above_relative" if (current_price is not None and current_price > relative_value)
            else "below_relative"
            if (current_price is not None and current_price > 0)
            else None
        ),
    }


@dataclass(frozen=True)
class RelativeScreen:
    """The whole screen for one multiple kind, ready to be published."""

    kind: str
    own: MultipleReading
    peer_stats: dict
    implied: dict[str, float | None]
    diagnostics: dict
    sensitivity_rows: list[dict] = field(default_factory=list)
