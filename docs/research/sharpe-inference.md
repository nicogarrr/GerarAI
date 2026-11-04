# Sharpe inference diagnostics

2026-11-04. Read-only research diagnostics, not a trading signal or evidence of skill.

## Contract and limits

`sharpe_inference` accepts a consecutive, equally spaced, finite return series,
its frequency, observations/year, constant **per-observation simple rf**, and
optional horizon dates. Never substitute an annual rf or closed-trade P&Ls.
Missing/invalid observations invalidate the series; they are not dropped.
The estimator is per-period mean excess return divided by population standard
deviation (ddof=0). Existing performance metrics and monetary calculations are
unchanged. There is no sqrt(frequency) annualization under serial dependence.

Outputs include n, horizon, rf convention, lag-1 return correlation, HAC lag count,
method version, SE, Wald t-type statistic for H0: SR=0, two-sided asymptotic-normal
p value and confidence interval. This is **not** an exact Student-t statistic.
HAC uses the full influence series, capturing dependence in returns and squared
returns, not just a lag-1 correction.

Below 60 observations, t/SE/p/CI are withheld. Sixty is a conservative product
floor, not a theorem or assurance of adequate power. Even long samples may be
unreliable under structural breaks, long memory, illiquid marks or heavy tails.
Stationarity, weak dependence and finite fourth moments are needed. All outputs
retain `validation_claim=false`; there is no `significant` badge.

Unknown trials are not silently treated as one trial: selection adjustment is
`unknown_trials`, adjusted p is null, and the nominal interval is descriptive.
When an explicit positive trial count is supplied, the interval and adjusted p
use Bonferroni. This union-bound adjustment does not require independent trials,
but does require valid marginal tests and the **full** search count, including
parameter tuning, horizons, tickers and discarded specifications. It is not DSR,
does not estimate an effective number of independent trials, and cannot repair
survivorship bias, look-ahead, missing costs or adaptive search. A frozen holdout
and a complete trial ledger remain necessary.

## Estimator and choice

For excess returns x, mu=mean(x), sigma²=mean((x-mu)²), SR=mu/sigma:

    IF_t = (x_t-mu)/sigma - mu*((x_t-mu)^2-sigma^2)/(2*sigma^3)
    gamma_k = sum(IF_t * IF_(t-k))/n
    LRV = gamma_0 + 2*sum((1-k/(L+1))*gamma_k, k=1..L)
    SE = sqrt(LRV/n); t = SR/SE
    CI = SR +/- NormalQuantile(1-alpha/(2*m))*SE

The influence function is centered before covariance estimation. L defaults to
floor(4*(n/100)^(2/9)); a caller may specify it, and the chosen value is returned.
No finite-sample degrees-of-freedom correction is claimed. Bartlett weights give
a nonnegative long-run variance up to roundoff; zero/degenerate cases return N/D.
This deterministic HAC implementation needs no new dependency. Studentized block
bootstrap is a possible later sensitivity analysis, not implemented or claimed.
Ledoit/Wolf warn that HAC normal intervals can undercover in small/moderate samples;
this motivates the sample floor and lack of conclusive badges, not a claim that
60 observations cures undercoverage. The IID shortcut SR*sqrt(n) was rejected.

## DCA v2 integration

The existing single-ticker backtest stores contribution/TIR summaries, not a
cash-inclusive, flow-adjusted net NAV path. Thus strategy Sharpe is explicitly
unavailable (`missing_flow_adjusted_nav_series`). TIR samples and overlapping
hit-rate windows are not fed into the estimator. Plain and levels buy the same
asset with different contributions; underlying return Sharpe cannot validate
extra contributions or establish outperformance. Fixed budget also needs its
cash trajectory, not just final cash.

An additive `underlying_reference` reports month-end **price** returns in the
buy/valuation window only, excluding unfinished months. Calendar gaps invalidate
the series rather than turn multi-month moves into one-month observations. The
actual source dates, params_version and explicit zero-rf assumption are recorded.
It is not a strategy total return and does not assert that dividends, costs or
corporate actions are fully represented. Existing invested/final/TIR/drawdown
fields are untouched. No pooled cross-ticker independence is assumed.

## Paper integration and remaining work

The scoreboard has entry, last mark and exit records, but no periodic portfolio
NAV, consistent capital base or cash history. Closed trades overlap, have variable
horizons/currencies, and exclude still-open losses. Therefore Sharpe, t and CI are
N/D (`missing_periodic_net_nav_series`), with n_periodic_observations=0, rather than
an invented sample count based on trades. Trades, costs and execution are unchanged.
To validate strategy/paper later, first produce a source-traceable, currency-
consistent periodic net NAV series with contributions/withdrawals reconciled,
closed/open positions and cash included, fixed period boundaries, actual rf
provenance, holdout boundaries, and an exhaustive trial ledger. That is not done
by this patch. No live backtest or actual paper result is certified here.

## Sources inspected

- Lo (2002), CFA Institute, primary paper abstract: serial dependence changes
  uncertainty and invalidates routine sqrt(12) annualization.
  https://rpc.cfainstitute.org/research/financial-analysts-journal/2002/the-statistics-of-sharpe-ratios
- Newey/West (1986 working paper, 1987 journal method), NBER, primary: positive
  semidefinite HAC covariance and consistency conditions.
  https://www.nber.org/papers/t0055
- Ledoit/Wolf (2008), University of Zurich primary paper: robust moment/delta HAC
  inference, liberal finite-sample behavior, and studentized time-series bootstrap.
  https://www.econ.uzh.ch/apps/workingpapers/wp/iewwp320.pdf
- RPESE (R Journal, 2022), technical methods article: influence functions, serial
  dependence, HAC and block bootstrap for performance uncertainty.
  https://journal.r-project.org/articles/RJ-2021-106/
- statsmodels API documentation, reference implementation convention: equal-spaced
  series, Bartlett default and floor(4*(T/100)^(2/9)) bandwidth.
  https://www.statsmodels.org/stable/generated/statsmodels.stats.sandwich_covariance.cov_hac.html
- Bailey/Lopez de Prado (2014), authors' primary paper: selection bias, non-normality
  and full search/trial provenance; explains why nominal CI alone cannot validate
  a tuned backtest. DSR itself is not implemented here.
  https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf
