import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.orm import Session

from app.models.entities import Base, Form144Notice
from tests.test_0137_form144_migration import _create_table, _load


def _notice(**overrides) -> Form144Notice:
    data = {
        "accession_number": "0000849869-26-000005",
        "form": "144",
        "is_amendment": False,
        "issuer_cik": "0000849869",
        "issuer_ticker": "SLGN",
        "issuer_name": "SILGAN HOLDINGS INC",
        "seller_cik": "0001164469",
        "seller_name": "LEWIS ROBERT B",
        "relationships": ["Director"],
        "broker_name": "FSC Securities Corporation",
        "securities_class_title": "Common Stock",
        "shares_to_sell": 88861.0,
        "aggregate_market_value": 3687731.50,
        "shares_outstanding": 105682020.0,
        "approx_sale_date": "11/16/2026",
        "exchange": "NYSE",
        "securities": [],
        "acquisitions": [],
        "sales_past_3m": [],
        "nothing_to_report_past_3m": True,
        "notice_date": "11/13/2026",
        "plan_adoption_dates": [],
        "remarks": None,
        "filing_date": "2026-11-13",
        "source_url": "https://www.sec.gov/Archives/edgar/data/849869/000084986926000005/primary_doc.xml",
        "index_url": "https://www.sec.gov/Archives/edgar/data/849869/000084986926000005/",
        "raw_sha256": None,
        "parser_version": "1.0",
        "status": "parsed",
        "error": None,
    }
    data.update(overrides)
    return Form144Notice(**data)


def test_adoption_rejects_foreign_key_to_wrong_tenant_column(monkeypatch):
    module=_load()
    engine=sa.create_engine('sqlite:///:memory:')
    with engine.begin() as conn:
        conn.exec_driver_sql('CREATE TABLE tenants (id INTEGER PRIMARY KEY, other INTEGER UNIQUE)')
        _create_table(conn)
        ops=Operations(MigrationContext.configure(conn))
        with ops.batch_alter_table('form144_notices') as batch:
            batch.create_unique_constraint('uq_existing',['tenant_id','accession_number'])
            batch.create_foreign_key('fk_wrong','tenants',['tenant_id'],['other'])
        monkeypatch.setattr(module,'op',ops)
        with pytest.raises(RuntimeError): module.upgrade()


def test_adopted_existing_data_survives_upgrade_downgrade(monkeypatch):
    module=_load()
    engine=sa.create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(_notice())
        db.commit()
    with engine.begin() as conn:
        monkeypatch.setattr(module,'op',Operations(MigrationContext.configure(conn)))
        module.upgrade()
        assert conn.scalar(sa.text('SELECT count(*) FROM form144_notices'))==1
        module.downgrade()
        assert sa.inspect(conn).has_table('form144_notices'),'downgrade deletes the adopted pre-existing table and its data'


