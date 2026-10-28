"""No broker, no capital, no LLM calls. Only observed, forward quotes fill trades."""
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.paper_trading import PaperTrade
from app.schemas.paper_trading import PaperProposal
from app.services.paper_cost_service import (
    LABEL as COST_LABEL,
)
from app.services.paper_cost_service import (
    PaperCostAssumptions,
    current_assumptions,
    execution_fee,
)
from app.services.paper_thesis_anchor import current_thesis


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class UnknownProposalCurrency(ValueError):
    """Legacy proposal has no trustworthy immutable currency input."""


def _same_proposal(existing: PaperTrade, proposal: PaperProposal) -> PaperTrade:
    if not existing.proposal_currency_known:
        raise UnknownProposalCurrency("No se conoce la moneda original de esta propuesta histórica; no se puede verificar el reintento.")
    values = proposal.model_dump(exclude={"currency"})
    values["ticker"] = proposal.ticker.upper()
    if existing.proposal_currency != proposal.currency or any(getattr(existing, key) != value for key, value in values.items()):
        raise ValueError("La clave ya pertenece a otra propuesta")
    return existing


_LOOKUP_THESIS = object()


def create_proposal(db: Session, proposal: PaperProposal, *, thesis_version_id=_LOOKUP_THESIS) -> PaperTrade:
    """Guarda la propuesta anclada a una tesis del servidor, nunca a una del cliente.

    El generador LLM pasa la versión que vio el modelo (o None si no había);
    sin argumento se ancla a la tesis vigente al guardar. Un reintento idéntico
    conserva el ancla original.
    """
    existing = db.scalar(select(PaperTrade).where(PaperTrade.proposal_key == proposal.proposal_key))
    if existing:
        return _same_proposal(existing, proposal)
    if thesis_version_id is _LOOKUP_THESIS:
        thesis = current_thesis(db, proposal.ticker)
        thesis_version_id = thesis.id if thesis is not None else None
    row = PaperTrade(
        **{**proposal.model_dump(), "ticker": proposal.ticker.upper()},
        proposal_currency=proposal.currency, proposal_currency_known=True,
        thesis_version_id=thesis_version_id,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        # Un reintento idéntico concurrente ganó la carrera por (tenant, proposal_key):
        # es el mismo envío, no un conflicto. Una clave con otro cuerpo sigue fallando.
        db.rollback()
        winner = db.scalar(select(PaperTrade).where(PaperTrade.proposal_key == proposal.proposal_key))
        if winner is None:
            raise
        return _same_proposal(winner, proposal)
    db.refresh(row)
    return row


def pnl(row: PaperTrade, price: Decimal | None) -> Decimal | None:
    if row.entry_price is None or price is None:
        return None
    sign = Decimal(1) if row.direction == "long" else Decimal(-1)
    return (price - row.entry_price) * row.quantity * sign


def deadline(row: PaperTrade) -> datetime | None:
    if row.entry_at is None:
        return None
    start = utc(row.entry_at)
    if row.horizon == "short":
        return start + timedelta(days=30)
    try:
        return start.replace(year=start.year + 5)
    except ValueError:  # February 29 -> February 28, five years later
        return start.replace(year=start.year + 5, day=28)


def close_position(
    row: PaperTrade,
    price: Decimal,
    at: datetime,
    reason: str,
    costs: PaperCostAssumptions | None,
) -> None:
    """Cierra al precio OBSERVADO y persiste la comision de salida del supuesto.

    El supuesto de coste se aplica solo si el trade ya nacio con el (entry_fee
    no NULL) o si se pasa `costs` explicitamente: un trade legado nunca gana
    costes a medias. Cierres inmutables: no se reabre ni se recalcula.
    """
    row.exit_price, row.exit_at, row.close_reason, row.status = price, at, reason, "closed"
    if row.entry_fee is not None and costs is not None:
        row.exit_fee = execution_fee(price, row.quantity, costs)


def apply_quote(row: PaperTrade, quote: dict, now: datetime, *, costs: PaperCostAssumptions | None = None) -> bool:
    """Skip missing/stale/backdated quotes. Stops fill at observed spot, not ideal levels."""
    if row.status not in {"pending", "open"}:
        return False
    try:
        price = Decimal(str(quote.get("live_c")))
        timestamp = quote.get("live_t")
        if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)):
            return False
        at = datetime.fromtimestamp(timestamp, UTC)
    except (InvalidOperation, ValueError, TypeError, OverflowError, OSError):
        return False
    currency = quote.get("currency")
    if not price.is_finite() or price <= 0 or not isinstance(currency, str) or not currency.isalpha() or len(currency) > 8:
        return False
    if not timedelta(0) <= utc(now) - at <= timedelta(hours=24):
        return False
    if at <= utc(row.created_at) or (row.mark_at is not None and at <= utc(row.mark_at)):
        return False
    if row.currency is not None and currency != row.currency:
        return False
    if costs is None and row.entry_fee is not None:
        costs = current_assumptions()
    if row.status == "pending":
        # Proposed entry is a limit. No instant backfill from before the proposal.
        reached = price <= row.proposed_entry if row.direction == "long" else price >= row.proposed_entry
        if not reached:
            return False
        # A gap through the stop/target invalidates this entry; do not mint a fake win.
        valid = row.stop < price < row.target if row.direction == "long" else row.target < price < row.stop
        if not valid:
            return False
        row.entry_price, row.entry_at, row.status = price, at, "open"
        if costs is not None:
            row.entry_fee = execution_fee(price, row.quantity, costs)
            row.cost_assumption_version = costs.version
    row.mark_price, row.mark_at = price, at
    row.currency, row.price_source = currency, "yahoo_finance_spot"
    stop = price <= row.stop if row.direction == "long" else price >= row.stop
    target = price >= row.target if row.direction == "long" else price <= row.target
    due = deadline(row)
    reason = "stop" if stop else "target" if target else "horizon" if due and at >= due else None
    if reason:
        close_position(row, price, at, reason, costs)
    return True


def trade_out(row: PaperTrade, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    fresh = row.mark_at is not None and timedelta(0) <= utc(now) - utc(row.mark_at) <= timedelta(hours=24)
    data = {column.name: getattr(row, column.name) for column in row.__table__.columns if column.name != "tenant_id"}
    from app.services.paper_cost_service import pnl_net

    data.update({
        "market_label": "dato",
        "quantity_label": "supuesto",
        "cost_label": COST_LABEL if row.cost_assumption_version else None,
        "mark_price": row.mark_price if fresh or row.status == "closed" else None,
        "unrealized_pnl": pnl(row, row.mark_price) if fresh and row.status == "open" else None,
        "unrealized_pnl_net": pnl_net(row, row.mark_price) if fresh and row.status == "open" else None,
        "realized_pnl": pnl(row, row.exit_price) if row.status == "closed" else None,
        "realized_pnl_net": pnl_net(row, row.exit_price) if row.status == "closed" else None,
        "quote_status": "available" if fresh else "sin_datos",
    })
    return data


def scoreboard(rows: list[PaperTrade], now: datetime | None = None) -> dict:
    groups: dict[tuple[str, str], list[PaperTrade]] = defaultdict(list)
    for row in rows:
        groups[(row.horizon, row.currency or "sin_datos")].append(row)
    cells = []
    for (horizon, currency), trades in sorted(groups.items()):
        distorted = [r for r in trades if r.status == "closed" and r.corporate_action_warning]
        closed = [r for r in trades if r.status == "closed" and not r.corporate_action_warning]
        results = [pnl(r, r.exit_price) for r in closed]
        realized = [r for r in results if r is not None]
        wins = sum(r > 0 for r in realized)
        losses = sum(r < 0 for r in realized)
        from app.services.paper_cost_service import pnl_net
        nets = [pnl_net(r, r.exit_price) for r in closed]
        realized_net = [n for n in nets if n is not None]
        wins_net = sum(n > 0 for n in realized_net)
        open_results = [trade_out(r, now)["unrealized_pnl"] for r in trades if r.status == "open"]
        marks = [r for r in open_results if r is not None]
        cells.append({
            "horizon": horizon, "currency": currency, "proposals": len(trades),
            "closed": len(realized), "open": sum(r.status == "open" for r in trades),
            "wins": wins, "losses": losses, "flat": len(realized) - wins - losses,
            "hit_rate": wins / len(realized) if realized else None,
            "realized_pnl": sum(realized, Decimal(0)) if realized else None,
            # Neto del supuesto persistido por trade; los legados no tienen neto.
            "closed_distorted": len(distorted),
            "closed_net": len(realized_net),
            "hit_rate_net": wins_net / len(realized_net) if realized_net else None,
            "realized_pnl_net": sum(realized_net, Decimal(0)) if realized_net else None,
            "unrealized_pnl": sum(marks, Decimal(0)) if marks else None,
            "missing_marks": len(open_results) - len(marks),
        })
    # Native currencies are NEVER summed together. An early stop is not a 5y verdict.
    bins = []
    for low, high in ((0, 0.5), (0.5, 0.75), (0.75, 1.01)):
        sample = [r for r in rows if r.status == "closed" and low <= float(r.conviction) < high and pnl(r, r.exit_price) is not None]
        bins.append({"conviction_min": low, "conviction_max": min(high, 1), "closed": len(sample),
                     "hit_rate": sum((pnl(r, r.exit_price) or Decimal(0)) > 0 for r in sample) / len(sample) if sample else None})
    return {"groups": cells, "conviction_bins": bins, "hit_rate": "positive_gross_return_on_closed_positions",
            "basis": "spot_gross_no_fees_dividends_fx_or_corporate_actions", "mode": "paper"}


def refresh_trades(db: Session, fetch_quote=None, *, only_id: int | None = None) -> dict:
    from app.api.routes.market import market_quote

    fetch_quote = fetch_quote or market_quote
    costs = current_assumptions()
    statement = select(PaperTrade).where(PaperTrade.status.in_(["pending", "open"]))
    if only_id is not None:
        statement = statement.where(PaperTrade.id == only_id)
    # Discovery copies scalar IDs/tickers only. Release the transaction before
    # ANY provider call: no pooled connection or row lock spans network I/O.
    candidates = list(db.execute(
        statement.with_only_columns(PaperTrade.id, PaperTrade.ticker)
        .order_by(PaperTrade.updated_at, PaperTrade.id)
    ).all())
    db.commit()
    selected: list[tuple[int, str]] = []
    quotes: dict[str, dict] = {}
    for proposal_id, ticker in candidates:
        if ticker not in quotes:
            if len(quotes) >= 50:
                continue
            quotes[ticker] = {}
        selected.append((proposal_id, ticker))
    for ticker in quotes:
        try:
            quotes[ticker] = fetch_quote(ticker)
        except Exception:  # noqa: BLE001 - upstream absence never fabricates a mark
            quotes[ticker] = {}
    changed = 0
    unavailable = 0
    for proposal_id, ticker in selected:
        # One short application transaction per row. Reload, don't trust ORM
        # identity-map state from discovery or a concurrent refresh/close.
        row = db.scalar(select(PaperTrade).where(PaperTrade.id == proposal_id)
                        .with_for_update().execution_options(populate_existing=True))
        try:
            if row is None or row.status not in {"pending", "open"}:
                unavailable += 1
            else:
                from app.services.paper_corporate_actions_service import (
                    PENDING_SPLIT_WARNING,
                    sync_corporate_actions,
                    sync_dividends,
                )
                now = datetime.now(UTC)
                row.updated_at = now
                sync_corporate_actions(db, row)  # niveles ajustados ANTES del fill
                blocked = row.status == "pending" and row.corporate_action_warning == PENDING_SPLIT_WARNING
                if not blocked and apply_quote(row, quotes[ticker], now, costs=costs):
                    changed += 1
                else:
                    unavailable += 1
                sync_dividends(db, row)
            db.commit()
        except Exception:
            db.rollback()
            raise
    return {"updated": changed, "unchanged": unavailable, "symbols_checked": len(quotes)}
