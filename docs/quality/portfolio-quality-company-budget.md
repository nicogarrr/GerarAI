# Quality diagnostics company query budget

IBKR cost reconciliation reads each candidate Position.company ticker. Quality
loads positions without company eager loading, causing N company SELECTs in
cold sessions even when no matching raw evidence or trades exists. joinedload
folds company reads into the same portfolio-filtered positions SELECT.

N=0/1/20/60 IBKR positions, other portfolio holding excluded, cache not involved,
same fixed portfolio lookup and cold session both sides. Before3/6/25/65SELECT;
after3/5/5/5. Position and Company ORM loads exactlyN each. No writes, changes
to diagnostic reasons, cost masking, dates, raw evidence or snapshot projection.
Tradeoff: manual-only positions also have company eagerly loaded now; one
joined row per position rather than an extra SELECT or a larger row count.

Full source55/56lines98.21%,27/28branches96.43%; quality route/data/snapshot
projection tests and new query counter tests pass. Synthetic SQLite, not
production latency. No external calls, deployments or paid services.
