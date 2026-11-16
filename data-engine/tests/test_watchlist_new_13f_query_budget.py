"""Measure the current linear read budget, not a claim of batching or latency."""
from datetime import date

import pytest
from sqlalchemy import event

from app.api.routes.watchlist import watchlist_new_13f
from app.models import Company, Tenant, WatchItem
from app.services import institutional_holders as ih
from app.services.connectors import form13f_dataset as ds
from tests.test_institutional_holders import APPLE, _db
from tests.test_institutional_new_positions import parsed_pair


@pytest.mark.parametrize("count", [0, 1, 5, 12])
def test_stored_snapshot_read_budget_is_one_plus_four_per_ticker(count):
    with _db() as db:
        tenant = Tenant(external_id="budget", name="Budget tenant")
        other = Tenant(external_id="other", name="Other tenant")
        db.add_all([tenant, other])
        db.flush()
        tenant_id = tenant.id
        db.add(WatchItem(tenant_id=other.id, symbol="OTHER"))
        db.commit()
        db.info["tenant_id"] = tenant_id
        periods, _ = ds.resolve_periods(parsed_pair())
        summary = ih.summarize(periods, APPLE, date(2026, 6, 30), date(2026, 3, 31))
        for i in range(count):
            company = Company(ticker=f"T{i}", name=f"Fixture {i}", exchange="NASDAQ",
                              company_type="mature", valuation_model="dcf", isin="US0378331005")
            db.add(company)
            db.flush()
            ih.persist(db, company, summary, cusip=APPLE, dataset_url="https://www.sec.gov/current.zip",
                       prior_url="https://www.sec.gov/prior.zip", checksum=f"budget{i}")
            db.add(WatchItem(tenant_id=tenant.id, symbol=company.ticker))
        db.commit()
        db.expunge_all()
        statements = []

        def record(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)

        event.listen(db.bind, "before_cursor_execute", record)
        try:
            output = watchlist_new_13f(db=db)
        finally:
            event.remove(db.bind, "before_cursor_execute", record)
        assert len(output["items"]) == count
        assert all(row["new_positions"]["count"] == 14 for row in output["items"])
        assert len(statements) == 1 + 4 * count
        assert all(statement.lstrip().upper().startswith("SELECT") for statement in statements)
