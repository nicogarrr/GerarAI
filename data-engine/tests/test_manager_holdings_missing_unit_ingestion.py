"""Absent 13F units must survive ingestion without the SH default."""
from sqlalchemy import select

from app.models.entities import ManagerHolding
from app.services.manager_holding_ingestion_service import ManagerHoldingIngestionService
from tests.test_manager_holdings import CIK, _sec_client, db  # noqa: F401


def test_missing_unit_is_persisted_unknown_and_exposed_null(db, monkeypatch):
    from app.services.connectors import form13f

    original = form13f.fetch_information_table

    def missing_unit(*args, **kwargs):
        rows = original(*args, **kwargs)
        for row in rows:
            row['ssh_prnamt_type'] = None
        return rows

    monkeypatch.setattr(form13f, 'fetch_information_table', missing_unit)
    service = ManagerHoldingIngestionService(client=_sec_client())
    service.sync_manager(db, cik=CIK)
    rows = db.scalars(select(ManagerHolding)).all()
    assert rows and all(row.share_type == 'UNKNOWN' for row in rows)
    result = service.latest_holdings(db, cik=CIK)
    assert result['holdings']
    assert all(row['share_type'] is None for row in result['holdings'])
