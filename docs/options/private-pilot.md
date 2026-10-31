# Private educational options pilot

Phase 1 is offline mathematics only. No route, scheduler, market-data call,
recommendation, order, portfolio write, or display to another user is enabled.

## Implemented

- European Black-Scholes-Merton reference price with explicit continuous dividend
  yield, annual continuously compounded rates and ACT/365 time.
- Delta, gamma, vega per 1 percentage point, theta per calendar day and rho per
  1 percentage point. Values are per share, not per contract. Delta is not the
  probability that a trade will win.
- European implied volatility via Brent, with arbitrage bounds and a configured
  search ceiling. Missing, boundary or nonidentifiable IV stays `None`.
- Expiry payoff and long-option P&L with an explicit contract multiplier, fees
  and whole positive contract count. Maximum premium risk does not include
  exercise/assignment exposure; the pilot will never exercise or place orders.

## Not implemented or safe to infer

US equity options are generally American. This European model is not an American
quote, valuation or IV. Discrete dividends, early exercise, adjusted deliverables,
spreads, stock borrow, liquidity and settlement require separate verified inputs
and a separate tested model before contract-level recommendations. Continuous
q is only an approximation and must be labelled as such. No default q, rate,
multiplier, quote or volatility may silently replace missing data. Historical
volatility is not implied volatility and a model price is not a premium quote.

Without a verified quote, the product can show an educational strategy and
hypothetical scenarios, not a fabricated tradable premium or contract selection.
DCA/momentum/fair-value/news evidence must retain its own timestamp, limitations
and provenance. A 4X DCA level is never an options-buy instruction.

## Account and access boundary

The MarketData signup currently starts a no-card $0 Starter Trial, then the signup
states automatic Free Forever transition without a paid subscription. Build to
Free Forever limits, not the temporary trial quota: 100 API credits/day, 24h
options delay, one year history. Per-contract credits make a full chain expensive.
No token is committed, logged, sent to the client or shared between tenants.
Before any integration, implement an owner-only server-side gate and quota ledger.
This is for the account owner's internal use, not public redistribution. A
hidden navigation item is not access control. Other tenants must be denied before
any upstream fetch or cached response, and cached data must be owner-scoped.
No multiuser launch is approved. No payment method, paid plan or order is allowed.

## Sources checked 2026-11-01

- BSM continuous dividend assumptions, formula, Greeks and limitations:
  https://www.glynholton.com/notes/merton_1973/
- CRR reference for the later American-model phase, not yet implemented:
  https://www.macroption.com/cox-ross-rubinstein-formulas/
- Free Forever limits:
  https://www.marketdata.app/docs/account/plans/free-forever
- License, credit accounting and IP restrictions:
  https://www.marketdata.app/docs/account/plan-limits/
- Signup/trial transition and no-card terms:
  https://dashboard.marketdata.app/marketdata/signup

## Next gates

Independent model review; American/discrete-dividend design and tests; securely
captured server-side token; owner-only integration tests; verified delayed quotes
for 1-3 symbols; mobile 390px mockup reviewed before building the large UI.
