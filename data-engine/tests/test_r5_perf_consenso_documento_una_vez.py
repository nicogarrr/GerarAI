"""/own-consensus: el documento fuente se decodifica una vez, no una por hecho (perf r5, 11-nov-2026).

``own_consensus._facts`` cargaba la fuente con ``joinedload``: el JOIN repetía
el documento entero en cada fila de hecho, y su ``metadata`` JSON (72 KB en
el documento SEC de QCOM, compartido por todos sus hechos) se decodificaba
una vez por fila. Medido en local: 61 % del tiempo de
``GET /api/companies/{t}/own-consensus``; p50 82 -> 33 ms en 10 tickers.

Con ``selectinload`` el documento llega en una consulta aparte (IN de los
documentos distintos): mismas URLs, sin N+1 y una decodificación por
documento. Conteos deterministas (deserializador contado), nunca reloj.
"""

from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.models import Company, Document, FinancialFact, Tenant
from app.models.entities import Base
from app.services.own_consensus import _facts

N_FACTS = 30


@pytest.fixture
def setup():
    decoded = {"n": 0}

    def _counting_loads(text: str):
        decoded["n"] += 1
        return json.loads(text)

    engine = create_engine("sqlite:///:memory:", json_deserializer=_counting_loads)
    Base.metadata.create_all(engine)
    session = Session(engine)
    session.add(Tenant(id=1, external_id="t1", name="one"))
    session.add(Company(id=1, ticker="BIG", name="Big Doc Co", exchange="NASDAQ", currency="USD", cik="0000804328",
                        company_type="asset_light", valuation_model="dcf_standard"))
    session.flush()
    doc = Document(id=7, company_id=1, tenant_id=1, title="SEC companyfacts", source_type="SEC",
                   source_url="https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0000804328",
                   metadata_={"payload": ["x" * 100] * 500})
    other = Document(id=8, company_id=1, tenant_id=1, title="Otro", source_type="SEC",
                     source_url="https://example.org/annual-report.pdf", metadata_={"k": 1})
    session.add_all([doc, other])
    session.flush()
    for i in range(N_FACTS):
        year = 1996 + i
        session.add(FinancialFact(company_id=1, tenant_id=1, metric="revenue", value=1000 + i, unit="USD",
                                  period=f"{year}-09-30:FY", fiscal_year=year, source_type="SEC",
                                  is_reported=True, source_id=8 if i == 0 else 7,
                                  accession_number=f"0000804328-{year % 100:02d}-000001",
                                  filed=date(year, 11, 5)))
    session.add(FinancialFact(company_id=1, tenant_id=1, metric="revenue", value=5, unit="USD",
                              period="2026-09-30:FY", fiscal_year=2026, source_type="SEC",
                              is_reported=True, source_id=None, filed=date(2026, 11, 5)))
    session.commit()
    session.expunge_all()
    decoded["n"] = 0
    yield session, decoded
    session.close()


def _company():
    return SimpleNamespace(id=1, cik="0000804328", ticker="BIG")


def test_shared_document_json_is_decoded_once_per_document(setup):
    session, decoded = setup
    rows = _facts(session, _company(), "revenue")
    assert len(rows) == N_FACTS + 1
    # Dos documentos distintos -> dos decodificaciones (antes: una por hecho, 30).
    assert decoded["n"] <= 2


def test_documents_come_in_one_separate_select(setup):
    session, _ = setup
    seen: list[str] = []

    def _listener(conn, cursor, statement, parameters, context, executemany):
        seen.append(" ".join(statement.split()).lower())

    event.listen(session.get_bind(), "before_cursor_execute", _listener)
    try:
        _facts(session, _company(), "revenue")
    finally:
        event.remove(session.get_bind(), "before_cursor_execute", _listener)
    assert len(seen) == 2  # hechos + documentos, sin N+1
    assert "join documents" not in seen[0]
    assert seen[1].startswith("select documents.")


def test_rows_keep_period_value_filed_and_exact_urls(setup):
    session, _ = setup
    rows = _facts(session, _company(), "revenue")
    by_period = {r[0]: r for r in rows}
    first = by_period["1996-09-30:FY"]
    assert first[1:3] == (1000.0, date(1996, 11, 5))
    assert first[3] == "https://example.org/annual-report.pdf"
    second = by_period["1997-09-30:FY"]
    # El listado genérico de EDGAR pasa al filing exacto del hecho.
    assert second[3] is not None and "browse-edgar" not in second[3]
    assert "000080432897000001" in second[3].replace("-", "")
    assert by_period["2026-09-30:FY"][3] is None  # hecho sin fuente: se conserva, sin URL
    assert all(r[4] == int(r[0][:4]) for r in rows)
