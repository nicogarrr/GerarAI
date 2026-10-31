"""ProPicks gems: undervalued, lightly followed quality companies.

Starts from companies that pass the quality funnel and adds value, balance
sheet and insider evidence. Every datum carries its source and date; anything
missing is left out of the score and the reason list, never imputed.
13F smart money joins manager_holdings to companies only through the CUSIP
map in instrument_references; a CUSIP without a ticker row is skipped, never
guessed. 13F is quarterly, long-only and up to 45 days late.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.tenancy import tenant_filters
from app.models import (
    Company,
    FinancialFact,
    InsiderTransaction,
    MarketPrice,
)
from app.models.entities import InstrumentReference, ManagerHolding
from app.services.display_es import fecha_es
from app.services.financial_ingestion_service import _annual_fiscal_year
from app.services.propicks_funnel_service import FunnelResult

MIN_MARKET_CAP = 3e8        # below this liquidity/quality of data is poor
MAX_MARKET_CAP = 1e10       # above this, coverage by analysts is broad
MIN_FCF_YIELD = 0.05
FCF_YIELD_FULL = 0.12
SPREAD_FULL = 0.15
INSIDER_FULL_USD = 500_000.0
INSIDER_WINDOW_DAYS = 180
SMART_MONEY_FULL = 3  # managers entering/adding in the latest quarter for full score
GEM_WEIGHTS = {
    "fcf_yield": 0.35,
    "roic_spread": 0.25,
    "balance_sheet": 0.10,
    "insiders": 0.15,
    "smart_money": 0.15,
}


@dataclass
class GemInputs:
    ticker: str
    name: str
    market_cap: float | None
    fcf_yield: float | None
    roic_spread: float | None
    leverage: float | None
    insider_net_usd: float | None
    managers_adding: int | None = None  # 13F managers new or increased vs prior quarter
    thirteenf_report: date | None = None
    price_date: date | None = None
    fcf_period: str | None = None


@dataclass
class Gem:
    ticker: str
    name: str
    score: float
    market_cap: float
    reasons: list[dict] = field(default_factory=list)
    price: float | None = None
    price_date: date | None = None


def _clip(x: float) -> float:
    return max(0.0, min(1.0, x))


def _periodo_es(period: str | None) -> str:
    # Periodo SEC legible: «2025-12-31:FY» -> «FY2025». Cualquier otra forma
    # («FY2025», trimestres, vacio) se muestra tal cual: nunca se reinterpreta.
    if not period:
        return "FY"
    if ":" in period:
        end, _, fp = period.partition(":")
        if end[:4].isdigit() and fp:
            year = end[:4]
            if fp == "FY":
                # Ejercicios 52/53 semanas que cierran el 1-7 de enero: el FY es el anterior.
                try:
                    year = str(_annual_fiscal_year(end, None))
                except ValueError:
                    pass
            return f"{fp}{year}"
    return period


def score_gem(g: GemInputs) -> Gem | None:
    """Return a Gem or None when the company does not qualify."""
    if g.market_cap is None or not (MIN_MARKET_CAP <= g.market_cap <= MAX_MARKET_CAP):
        return None
    if g.fcf_yield is None or g.fcf_yield < MIN_FCF_YIELD:
        return None
    parts: dict[str, float] = {"fcf_yield": _clip(g.fcf_yield / FCF_YIELD_FULL)}
    reasons = [
        {
            "key": "fcf_yield",
            "value": g.fcf_yield,
            "source": f"SEC {_periodo_es(g.fcf_period)} + precio {fecha_es(g.price_date) if g.price_date else 'sin fecha'}",
        }
    ]
    if g.roic_spread is not None:
        parts["roic_spread"] = _clip(g.roic_spread / SPREAD_FULL)
        reasons.append({"key": "roic_spread", "value": g.roic_spread, "source": "Métricas calculadas"})
    if g.leverage is not None:
        parts["balance_sheet"] = 1.0 - _clip(g.leverage / 3.0)
        reasons.append({"key": "net_debt_to_ebitda", "value": g.leverage, "source": "Métricas calculadas"})
    if g.insider_net_usd is not None:
        parts["insiders"] = _clip(g.insider_net_usd / INSIDER_FULL_USD)
        if g.insider_net_usd > 0:
            reasons.append(
                {"key": "insider_net_buy_usd", "value": g.insider_net_usd, "source": f"SEC Form 4, {INSIDER_WINDOW_DAYS} días"}
            )
    if g.managers_adding is not None:
        parts["smart_money"] = _clip(g.managers_adding / SMART_MONEY_FULL)
        if g.managers_adding > 0:
            reasons.append(
                {
                    "key": "managers_adding_13f",
                    "value": g.managers_adding,
                    "source": f"SEC 13F, trimestre a {fecha_es(g.thirteenf_report) if g.thirteenf_report else 'sin fecha'} (retraso hasta 45 días; solo largos)",
                }
            )
    total_w = sum(GEM_WEIGHTS[k] for k in parts)
    score = 100.0 * sum(GEM_WEIGHTS[k] * v for k, v in parts.items()) / total_w
    return Gem(g.ticker, g.name, round(score, 2), g.market_cap, reasons)


def _latest_fcf_and_shares(db: Session, min_fiscal_year: int) -> dict[int, tuple[float, float, str]]:
    rows = db.execute(
        select(
            FinancialFact.company_id, FinancialFact.metric, FinancialFact.fiscal_year,
            FinancialFact.value, FinancialFact.period,
        )
        .where(FinancialFact.metric.in_(["free_cash_flow", "shares_diluted"]))
        .where(FinancialFact.fiscal_quarter.in_(["FY", ""]))
        .where(FinancialFact.fiscal_year.isnot(None))
        # Un FY de hace más de 2 años no es un dato actual: VOYA entraba en
        # joyas con FCF de FY2016 contra precio de hoy. Sin FY reciente la
        # empresa se queda sin fcf_yield y no entra (fail-closed, N/D).
        .where(FinancialFact.fiscal_year >= min_fiscal_year)
        .where(*tenant_filters(db, FinancialFact))
        .order_by(FinancialFact.fiscal_year.desc(), FinancialFact.created_at.desc())
    ).all()
    fcf: dict[int, tuple[int, float, str]] = {}
    sh: dict[int, tuple[int, float]] = {}
    for cid, metric, fy, value, period in rows:
        if metric == "free_cash_flow":
            fcf.setdefault(cid, (fy, float(value), period))
        else:
            sh.setdefault(cid, (fy, float(value)))
    # Mismo ejercicio para FCF y acciones (doctrina del P/B: ejercicios
    # distintos no se mezclan): una recompra o dilucion entre FYs haria el
    # fcf_yield no verificable. Sin par del mismo FY: N/D (fail-closed).
    return {
        cid: (f[1], sh[cid][1], f[2])
        for cid, f in fcf.items()
        if cid in sh and sh[cid][1] > 0 and sh[cid][0] == f[0]
    }


def _smart_money(
    db: Session, tickers: set[str]
) -> tuple[dict[str, int], date | None]:
    """Managers that opened or increased a position in the latest 13F quarter.

    The ticker comes only from instrument_references (verified CUSIP map);
    a CUSIP without a unique ticker row is skipped, never guessed.
    """
    dates = sorted(
        {
            d
            for d in db.scalars(
                select(ManagerHolding.report_date)
                .where(
                    ManagerHolding.report_date.isnot(None),
                    *tenant_filters(db, ManagerHolding),
                )
                .distinct()
            ).all()
        },
        reverse=True,
    )
    if len(dates) < 2:
        return {}, None
    latest, prior = dates[0], dates[1]
    cusip_ticker: dict[str, str] = {}
    for ref in db.scalars(
        select(InstrumentReference).where(InstrumentReference.ticker_normalized.in_(tickers))
    ).all():
        if ref.cusip:
            cusip_ticker[ref.cusip[:9]] = ref.ticker_normalized
    if not cusip_ticker:
        return {}, latest
    shares: dict[tuple[date | None, str, int], float] = {}
    for h in db.scalars(
        select(ManagerHolding)
        .where(ManagerHolding.report_date.in_([latest, prior]))
        .where(ManagerHolding.cusip.in_(list(cusip_ticker)))
        .where(ManagerHolding.put_call == "")
        .where(*tenant_filters(db, ManagerHolding))
    ).all():
        key = (h.report_date, h.cusip, h.manager_id)
        # nosemgrep: gerarai-money-none-to-zero -- agregado informativo de filings/flujos (ranking/listado): una fila sin cifra no suma; no es un importe del usuario
        shares[key] = shares.get(key, 0.0) + float(h.shares or 0)
    adding: dict[str, int] = dict.fromkeys(cusip_ticker.values(), 0)
    for (d, cusip, mid), sh in shares.items():
        if d != latest or sh <= 0:
            continue
        if sh > shares.get((prior, cusip, mid), 0.0):
            adding[cusip_ticker[cusip]] += 1
    return adding, latest


def find_gems(
    db: Session, results: list[FunnelResult], *, today: date | None = None, limit: int = 20
) -> list[Gem]:
    today = today or date.today()
    passed = {r.company_id: r for r in results if r.passed}
    if not passed:
        return []
    companies = {
        c.id: c
        for c in db.scalars(select(Company).where(Company.id.in_(list(passed)))).all()
        if (c.currency or "").upper() == "USD"  # facts and prices share currency
    }
    base = _latest_fcf_and_shares(db, today.year - 2)
    prices: dict[int, MarketPrice] = {}
    for p in db.scalars(
        select(MarketPrice)
        .where(MarketPrice.company_id.in_(list(companies)))
        .where(MarketPrice.close.isnot(None))
        .order_by(MarketPrice.date.desc())
    ).all():
        prices.setdefault(p.company_id, p)
    since = (today - timedelta(days=INSIDER_WINDOW_DAYS)).isoformat()
    tickers = {c.ticker for c in companies.values()}
    insider: dict[str, float] = {}
    for t in db.scalars(
        select(InsiderTransaction)
        .where(InsiderTransaction.issuer_ticker.in_(tickers))
        .where(InsiderTransaction.tx_date >= since)
        .where(InsiderTransaction.is_derivative.is_(False))
        .where(InsiderTransaction.code.in_(["P", "S"]))
        .where(*tenant_filters(db, InsiderTransaction))
    ).all():
        if t.value is None or t.issuer_ticker is None:
            continue
        insider[t.issuer_ticker] = insider.get(t.issuer_ticker, 0.0) + (
            float(t.value) if t.code == "P" else -float(t.value)
        )
    adding, report = _smart_money(db, tickers)
    gems: list[Gem] = []
    for cid, company in companies.items():
        price, b = prices.get(cid), base.get(cid)
        if price is None or b is None or (today - price.date).days > 7:
            continue  # stale or missing price: N/D, never shown as current
        fcf_val, shares, period = b
        cap = float(price.close) * shares
        m = passed[cid].metrics
        roic, wacc = m.get("roic"), m.get("wacc")
        gem = score_gem(
            GemInputs(
                ticker=company.ticker,
                name=company.name,
                market_cap=cap,
                fcf_yield=fcf_val / cap if cap > 0 else None,
                roic_spread=(roic - wacc) if roic is not None and wacc is not None else None,
                leverage=m.get("net_debt_to_ebitda"),
                insider_net_usd=insider.get(company.ticker),
                managers_adding=adding.get(company.ticker),
                thirteenf_report=report,
                price_date=price.date,
                fcf_period=period,
            )
        )
        if gem:
            gem.price = float(price.close)
            gem.price_date = price.date
            gems.append(gem)
    gems.sort(key=lambda g: (-g.score, g.ticker))
    return gems[:limit]
