"""SEC repite filed por concepto: parsear cada literal una vez por payload."""
from datetime import date
from unittest.mock import Mock

from app.services import financial_ingestion_service as ingestion


def test_repeated_filing_dates_parsed_once(monkeypatch):
    parse = Mock(side_effect=date.fromisoformat)
    monkeypatch.setattr(ingestion, "date", type("CountedDate", (), {"fromisoformat": staticmethod(parse)}))
    entries = [{"filed": "2025-02-01"}, {"filed": "2024-02-01"},
               {"filed": "invalid"}, {}, {"filed": "2025-02-01T12:00:00Z"}] * 2000
    payload = {"Revenue": {"units": {"USD": entries}}, "Assets": {"units": {"USD": entries}}}
    assert ingestion._latest_filed_date(payload) == date(2025, 2, 1)
    assert parse.call_count == 4  # 20.000 filas, cuatro literales truncados distintos
    assert {c.args[0] for c in parse.call_args_list} == {"2025-02-01", "2024-02-01", "invalid", ""}


def test_no_global_filing_cache_or_invalid_date_shortcut():
    def payload(values):
        return {"X": {"units": {"USD": [{"filed": x} for x in values]}}}
    assert ingestion._latest_filed_date(payload(["9999-99-99", "2024-02-29", "2025-02-30"])) == date(2024, 2, 29)
    assert ingestion._latest_filed_date(payload(["2023-01-01"])) == date(2023, 1, 1)
    assert ingestion._latest_filed_date(payload([None, "", "nonsense"])) is None
