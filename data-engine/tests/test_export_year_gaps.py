"""Ramas residuales de export.py: ano fuera de rango (400) y error del
calculo fiscal propagado en el payload (nunca None silencioso)."""

from __future__ import annotations

import asyncio
import json

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.routes import export as routes
from app.api.routes.export import export_year
from app.models.entities import Base


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as session:
        session.info["tenant_id"] = 1
        yield session


def _payload(response) -> dict:
    async def _collect():
        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk if isinstance(chunk, bytes) else chunk.encode())
        return b"".join(chunks)

    return json.loads(asyncio.run(_collect()))


def test_year_fuera_de_rango_400(db):
    for year in (1999, 2201):
        with pytest.raises(HTTPException) as excinfo:
            export_year(year=year, format="json", db=db)
        assert excinfo.value.status_code == 400


def test_error_fiscal_se_propaga_en_el_payload(db, monkeypatch):
    def _explota(self, db, year):
        raise RuntimeError("sin datos fiscales")

    monkeypatch.setattr(routes.TaxReportService, "compute_report", _explota)
    payload = _payload(export_year(year=2026, format="json", db=db))
    assert payload["tax"]["status"] == "unavailable"
    assert payload["tax"]["error"].startswith("RuntimeError")
