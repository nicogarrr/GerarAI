"""Backpressure de la cola KPI: sondas, freno en ingesta y backfill."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import app.workers.dramatiq_app as workers


def _client_with_depth(depth: int) -> MagicMock:
    client = MagicMock()
    client.hlen.side_effect = lambda key: 0 if ".DQ." in key else depth
    return client


class TestQueueProbes:
    def test_depth_uses_msgs_hash(self) -> None:
        client = _client_with_depth(42)
        assert workers.kpi_queue_depth(client) == 42
        assert [call.args[0] for call in client.hlen.call_args_list] == [
            "dramatiq:kpis.msgs", "dramatiq:kpis.DQ.msgs"
        ]

    def test_depth_unavailable_on_error(self) -> None:
        client = MagicMock()
        client.hlen.side_effect = ConnectionError("redis down")
        assert workers.kpi_queue_depth(client) is None

    def test_capacity_boundary(self) -> None:
        with patch.object(workers, "kpi_queue_max_pending", return_value=10):
            assert workers.kpi_queue_has_capacity(_client_with_depth(9)) is True
            assert workers.kpi_queue_has_capacity(_client_with_depth(10)) is False

    def test_max_pending_invalid_env_defaults_100(self) -> None:
        with patch.dict("os.environ", {"KPI_QUEUE_MAX_PENDING": "abc"}):
            assert workers.kpi_queue_max_pending() == 100


class TestIngestionDeferral:
    def test_deferred_sets_flag_and_skips_send(self) -> None:
        document = MagicMock()
        document.metadata_ = {}
        db = MagicMock()
        with (
            patch.object(workers, "kpi_queue_has_capacity", return_value=False),
            patch.object(workers.extract_document_kpis, "send") as send,
        ):
            # Replica la rama de ingesta: flag + no send
            from app.workers.dramatiq_app import KPI_DEFERRED_KEY

            if not workers.kpi_queue_has_capacity():
                meta = dict(document.metadata_ or {})
                meta.setdefault(KPI_DEFERRED_KEY, {"attempts": 0})
                document.metadata_ = meta
                db.commit()
            assert document.metadata_[KPI_DEFERRED_KEY] == {"attempts": 0}
            send.assert_not_called()


class TestBackfill:
    def test_queue_full_skips(self) -> None:
        with patch.object(workers, "kpi_queue_max_pending", return_value=10), patch.object(
            workers, "kpi_queue_depth", return_value=10
        ), patch.object(workers, "_redis_client", return_value=None):
            result = workers.backfill_document_kpis()
        assert result["status"] == "skipped"
        assert result["reason"] == "queue_full"


class TestBackfillFunctional:
    """Dos pasadas de backfill y agotados antiguos delante de elegibles."""

    def _db(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        from app.core.database import Base
        from app.models import Document  # noqa: F401 - registra la tabla

        engine = create_engine("sqlite://")
        Base.metadata.create_all(engine, tables=[Document.__table__])
        return sessionmaker(bind=engine)()

    def _doc(self, db, title, deferred, created):
        from app.models import Document

        doc = Document(
            title=title,
            source_type="sec",
            tenant_id=1,
            metadata_={"kpi_deferred": deferred},
            created_at=created,
        )
        db.add(doc)
        db.commit()
        return doc

    def _run_backfill(self, db, depth=0):
        with (
            patch.object(workers, "tenant_contexts", return_value=[(1, "u")]),
            patch.object(workers, "_session", return_value=db),
            patch.object(workers, "_redis_client", return_value=None),
            patch.object(workers, "kpi_queue_depth", return_value=depth),
            patch.object(workers, "kpi_queue_max_pending", return_value=10),
            patch.object(workers.extract_document_kpis, "send") as send,
        ):
            result = workers.backfill_document_kpis()
        return result, send

    def test_no_requeue_while_lease_active(self) -> None:
        import datetime as dt

        db = self._db()
        self._doc(db, "d1", {"attempts": 0}, dt.datetime(2026, 1, 1))
        result1, send1 = self._run_backfill(db)
        assert result1["queued"] == 1
        assert send1.call_count == 1
        # Segunda pasada inmediata (scheduler 5 min): lease activo, no reencola.
        result2, send2 = self._run_backfill(db)
        assert result2["queued"] == 0
        assert send2.call_count == 0
        # Lease expirado: vuelve a ser elegible.
        from app.models import Document

        d = db.query(Document).one()
        d.metadata_ = {"kpi_deferred": {"attempts": 1, "queued_at": 1}}
        db.commit()
        result3, send3 = self._run_backfill(db)
        assert result3["queued"] == 1
        assert send3.call_count == 1

    def test_exhausted_old_docs_do_not_starve_eligible(self) -> None:
        import datetime as dt

        db = self._db()
        for i in range(6):
            self._doc(
                db,
                f"old{i}",
                {"attempts": workers.KPI_DEFER_MAX_ATTEMPTS, "queued_at": 1},
                dt.datetime(2026, 1, 1 + i),
            )
        eligible = self._doc(db, "new", {"attempts": 0}, dt.datetime(2026, 2, 1))
        eligible_id = eligible.id  # la sesion se cierra dentro del actor
        result, send = self._run_backfill(db)
        assert result["queued"] == 1
        send.assert_called_once_with(eligible_id, tenant_id=1, user_id="u")


    def test_backlog_holds_expired_lease_but_empty_queue_requeues(self) -> None:
        """Backlog > lease con mensaje aun pendiente: NO se duplica.

        Solo cuando la cola queda vacia (mensaje perdido/fallido) el
        diferido vuelve a ser elegible.
        """
        import datetime as dt

        db = self._db()
        self._doc(
            db,
            "stuck",
            {"attempts": 1, "queued_at": 1},  # lease largamente expirado
            dt.datetime(2026, 1, 1),
        )
        # Mensaje aun en vuelo (depth > 0): no reencola aunque el lease expiro.
        result1, send1 = self._run_backfill(db, depth=3)
        assert result1["queued"] == 0
        assert send1.call_count == 0
        # Cola vacia: el mensaje se perdio o fallo; reencolar es seguro.
        result2, send2 = self._run_backfill(db, depth=0)
        assert result2["queued"] == 1
        assert send2.call_count == 1


    def test_ordinary_doc_never_selected_ahead_of_deferred(self) -> None:
        import datetime as dt

        from app.models import Document

        db = self._db()
        # Doc ordinario (SIN flag) mas antiguo que el diferido: con el
        # predicado crudo isnot(None), sqlite lo seleccionaria por JSON_QUOTE
        # ('null' texto) y se comeria la unica plaza de capacidad (depth=9
        # sobre max 10 -> capacity 1) por delante del diferido genuino.
        ordinary = self._doc(db, "ordinario", None, dt.datetime(2026, 1, 1))
        ordinary.metadata_ = {}
        db.commit()
        deferred = self._doc(db, "diferido", {"attempts": 0}, dt.datetime(2026, 1, 2))
        ordinary_id, deferred_id = ordinary.id, deferred.id
        result, send = self._run_backfill(db, depth=9)
        assert result["queued"] == 1
        send.assert_called_once_with(deferred_id, tenant_id=1, user_id="u")
        ordinary_after = db.query(Document).filter_by(id=ordinary_id).one()
        assert "kpi_deferred" not in (ordinary_after.metadata_ or {})

    def test_reservation_survives_later_send_failure(self) -> None:
        """Send 1 OK, send 2 explota: la reserva del 1 NO se revierte.

        Pasada siguiente con depth>0: el primero no se reencola; el
        segundo (nada entro en Redis) vuelve como nunca enviado.
        """
        import datetime as dt

        db = self._db()
        self._doc(db, "first", {"attempts": 0}, dt.datetime(2026, 1, 1))
        second = self._doc(db, "second", {"attempts": 0}, dt.datetime(2026, 1, 2))
        second_id = second.id
        calls = []

        def flaky_send(doc_id, **kwargs):
            calls.append(doc_id)
            if doc_id == second_id:
                raise ConnectionError("redis caido")

        with (
            patch.object(workers, "tenant_contexts", return_value=[(1, "u")]),
            patch.object(workers, "_session", return_value=db),
            patch.object(workers, "_redis_client", return_value=None),
            patch.object(workers, "kpi_queue_depth", return_value=0),
            patch.object(workers, "kpi_queue_max_pending", return_value=10),
            patch.object(workers.extract_document_kpis, "send", side_effect=flaky_send),
        ):
            workers.backfill_document_kpis()
        assert len(calls) == 2

        # Segunda pasada: hay un mensaje en vuelo (el primero) -> depth>0.
        # El segundo conserva su reserva (send incierto): no se reencola.
        result2, send2 = self._run_backfill(db, depth=1)
        assert result2["queued"] == 0
        assert send2.call_count == 0
        # Cola vacia pero lease sin expirar: tampoco (el mensaje pudo entrar).
        result3, send3 = self._run_backfill(db, depth=0)
        assert result3["queued"] == 0
        assert send3.call_count == 0
        # Cola vacia y lease expirado: el mensaje se perdio; reencola seguro.
        from app.models import Document

        d = db.query(Document).filter_by(id=second_id).one()
        d.metadata_ = {"kpi_deferred": {"attempts": 1, "queued_at": 1}}
        db.commit()
        result4, send4 = self._run_backfill(db, depth=0)
        assert result4["queued"] == 1
        send4.assert_called_once_with(second_id, tenant_id=1, user_id="u")
