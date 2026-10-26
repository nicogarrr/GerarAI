"""CSV control-prefix escaping, including actual exported contribution notes."""

import csv
import io
from datetime import date
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.routes import export as route
from app.core.database import Base, get_db


@pytest.mark.parametrize("text", [
    "\t=1+1", "\r=1+1", "\n=1+1", "  =1+1", "\tplain", "\rplain", "\nplain",
    "＝1+1", "＋1+1", "－1+1", "＠SUM(1)", ' \t=1+1,"quoted"',
])
def test_csv_untrusted_control_prefixes_are_escaped(text):
    assert route._csv_cell(text) == "'" + text


@pytest.mark.parametrize("value", [None, 12.5, -12.5, 0, "AAPL", "nota normal", "  nota normal"])
def test_csv_ordinary_values_and_real_numbers_are_unchanged(value):
    assert route._csv_cell(value) == value


def test_streamed_csv_escapes_note_without_splitting_cells(monkeypatch):
    note = '\t=1+1,"quoted"\nnext line'
    monkeypatch.setattr(route.InvestmentPlanService, "list_contributions", lambda *a: [
        SimpleNamespace(date=date(2026, 1, 2), amount=-12.5, currency="EUR", note=note),
    ])
    monkeypatch.setattr(route.PortfolioFXService, "portfolio", lambda *a: None)
    monkeypatch.setattr(route.TaxReportService, "compute_report", lambda *a: {})
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    app = FastAPI()
    app.include_router(route.router, prefix="/api/export")

    def isolated_db():
        with Session(engine) as db:
            db.info["tenant_id"] = 1
            yield db

    app.dependency_overrides[get_db] = isolated_db
    response = TestClient(app).get("/api/export/2026?format=csv")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    text = response.content.decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(text, newline="")))
    assert len(rows) == 2 and len(rows[1]) == 8
    assert rows[1][5] == "'" + note
    assert rows[1][3] == "-12.5"
    engine.dispose()
