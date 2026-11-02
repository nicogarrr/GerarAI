"""El export anual lista el diario de decisiones por fecha, como las operaciones.

Las operaciones y las aportaciones salen ordenadas por fecha, pero los asientos
del diario salían en el orden en que la base de datos los devolviera: uno
apuntado tarde (decidido en enero, registrado en marzo) aparecía después de los
de febrero, y en Postgres el orden podía cambiar entre dos exports del mismo año.
"""

from __future__ import annotations

import csv
import io
from datetime import UTC, date, datetime

from app.api.routes.export import export_year
from app.models.entities import DecisionJournalEntry
from tests.test_export_year_journal_dec31 import _entry, _payload, db  # noqa: F401


def _csv_rows(response) -> list[list[str]]:
    import asyncio

    async def _collect():
        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk if isinstance(chunk, bytes) else chunk.encode())
        return b"".join(chunks)

    return list(csv.reader(io.StringIO(asyncio.run(_collect()).decode("utf-8-sig"))))


def _seed(db):  # noqa: F811
    late = _entry(db, datetime(2026, 3, 10, 9, tzinfo=UTC))

    def _add(created: datetime, decided: date, decision: str) -> DecisionJournalEntry:
        entry = DecisionJournalEntry(
            company_id=late.company_id,
            decision=decision,
            rationale="test",
            created_at=created,
            decision_date=decided,
        )
        db.add(entry)
        db.commit()
        return entry

    first = _add(datetime(2026, 3, 11, 9, tzinfo=UTC), date(2026, 1, 15), "buy")
    same_day = _add(datetime(2026, 3, 12, 9, tzinfo=UTC), date(2026, 3, 10), "sell")
    return [first.id, late.id, same_day.id]


def test_json_journal_entries_are_sorted_by_decision_date(db):  # noqa: F811
    expected = _seed(db)
    payload = _payload(export_year(2026, format="json", db=db))
    assert [row["id"] for row in payload["journal_entries"]] == expected


def test_csv_journal_rows_are_sorted_by_decision_date(db):  # noqa: F811
    expected = _seed(db)
    rows = [row for row in _csv_rows(export_year(2026, format="csv", db=db)) if row[0] == "journal"]
    assert [int(row[7]) for row in rows] == expected
    assert [row[1] for row in rows] == ["2026-01-15", "2026-03-10", "2026-03-10"]
