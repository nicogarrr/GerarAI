"""Manual worker cannot evaluate without CAS claim and renewed owned lease."""
from datetime import UTC, datetime
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import DcaEvaluationRun
from app.models.entities import Base
from app.services import dca_manual, dca_manual_job, dca_signal_service


def test_lost_compare_and_swap_does_not_renew_evaluate_or_release(monkeypatch):
    row = DcaEvaluationRun(id=7, tenant_id=1, trigger="manual", status="queued",
        started_at=datetime.now(UTC), detail={"requested_symbols": ["LOCAL"]})
    db = Mock(spec=Session)
    db.info = {"tenant_id": 1}
    db.scalar.return_value = row
    db.execute.return_value.rowcount = 0
    client = Mock()
    client.get.return_value = b"owned-token"
    evaluate = Mock(side_effect=AssertionError("CAS loser cannot evaluate"))
    release = Mock(side_effect=AssertionError("CAS loser cannot release another worker"))
    monkeypatch.setattr(dca_manual_job, "redis_client", lambda: client)
    monkeypatch.setattr(dca_signal_service, "evaluate_watchlist", evaluate)
    monkeypatch.setattr(dca_manual, "release_manual_gate", release)
    assert dca_manual_job.run_manual_job(db, 7, "owned-token") == {"status": "ignored"}
    db.commit.assert_called_once()
    client.eval.assert_not_called()
    evaluate.assert_not_called()
    release.assert_not_called()
    client.close.assert_called_once()


def test_failed_lease_renewal_persists_error_without_evaluation_or_release(monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    client = Mock()
    client.get.return_value = b"owned-token"
    client.eval.return_value = 0
    evaluate = Mock(side_effect=AssertionError("unrenewed lease cannot evaluate"))
    release = Mock(side_effect=AssertionError("unowned lease cannot be released"))
    monkeypatch.setattr(dca_manual_job, "redis_client", lambda: client)
    monkeypatch.setattr(dca_signal_service, "evaluate_watchlist", evaluate)
    monkeypatch.setattr(dca_manual, "release_manual_gate", release)
    with Session(engine, expire_on_commit=False) as db:
        db.info["tenant_id"] = 1
        row = DcaEvaluationRun(tenant_id=1, trigger="manual", status="queued",
            started_at=datetime.now(UTC), detail={"requested_symbols": ["LOCAL"], "pending_remaining": 2})
        db.add(row)
        db.commit()
        with pytest.raises(RuntimeError, match="renovar"):
            dca_manual_job.run_manual_job(db, row.id, "owned-token")
        assert row.status == "error"
        assert row.detail["requested_symbols"] == ["LOCAL"]
        assert row.detail["pending_remaining"] == 2
        assert "summary" not in row.detail
    engine.dispose()
    evaluate.assert_not_called()
    release.assert_not_called()
    client.close.assert_called_once()
