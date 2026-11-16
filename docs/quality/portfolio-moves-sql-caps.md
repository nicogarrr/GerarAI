# Portfolio moves: SQL caps before materialization

Base f2ed2be loads9price rows and40GDELT rows per company in a bounded date
window, then keeps2/5 in Python. New row_number partition by company ranks
the same SQL-filtered sets and selects rank<=2/5 before ORM materialization.
Output ordering stays company/date descending; no new tie-breaker or filters.
Connector/url/date filters precede rank. Existing tenant loader criteria also
apply inside the ranked query: newer foreign articles cannot consume its cap.

Cold SQLite sessions, N=1/20/60,9daily rows+40news rows per company. Same final
test against original source and fixed source; fixed portfolio/trading dates.
Before ORM prices9/180/540, news40/800/2400. After prices2/40/120, news5/100/300.
Statement count stays7 in all cases: the gain is bounded materialization, not
fewer queries. Payload checks include prior/current adjusted close, latest5
news/order and available status; existing digest tests cover missing bars,
RSS-before-limit, tenant isolation, gap sessions and idempotence.

11 tests pass; entire touched service68/71lines95.77%,23/26branches88.46%.
Ruff clean. Reproduce with scripts/test-portfolio-moves-budget.sh, which checks
the line and branch gates separately. SyntheticSQLite not production latency.
