"""Ingesta de evidencia (filings SEC e IR): las queries no crecen por candidato.

Antes, ``_ingest_filings`` y ``_ingest_ir`` comprobaban SI YA EXISTE el
documento con una query POR CADA URL candidata (hasta 8 filings / 10 releases
IR por empresa y pasada). Ahora las URLs existentes salen de una sola query
con IN y el bucle solo inserta. Este test fija el coste plano en estado
estacionario (todo existe), la creación solo de los nuevos y el criterio de
duplicados dentro del propio lote (la segunda vez que aparece una URL en la
misma pasada no inserta, igual que hacía el autoflush del chequeo anterior).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.models import Company, Tenant
from app.models.entities import Base, Document
from app.services.thesis_evidence_service import ThesisEvidenceService


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    tenant = Tenant(external_id=f"te-{uuid.uuid4().hex[:8]}", name="T", status="active")
    db.add(tenant)
    db.flush()
    db.info["tenant_id"] = tenant.id
    ticker = f"TE{uuid.uuid4().hex[:4].upper()}"
    company = Company(
        ticker=ticker, name=f"Empresa {ticker}", exchange="NASDAQ", currency="USD",
        sector="T", industry="T", company_type="standard", valuation_model="standard_dcf",
        ir_url="https://ir.example.test",
    )
    db.add(company)
    db.commit()
    return engine, db, tenant, company


def _filings(ticker: str, n: int) -> list[dict]:
    return [
        {
            "form": "10-K" if i == 0 else "10-Q",
            "document_url": f"https://sec.test/{ticker}/{i}",
            "filing_date": f"2026-0{i + 1}-15",
            "accession_number": f"acc-{i}",
        }
        for i in range(n)
    ]


def _service(filings):
    service = ThesisEvidenceService()
    service._fetch_filings = lambda cik: filings
    service._annual_report_text = lambda *a, **k: {"status": "ok"}
    return service


def _counter(engine) -> list[str]:
    statements: list[str] = []
    event.listen(engine, "before_cursor_execute", lambda *a: statements.append(a[2]))
    return statements


def _existing_docs(db, company, tenant, urls):
    for url in urls:
        db.add(
            Document(
                company_id=company.id, tenant_id=tenant.id, title="x", source_type="SEC",
                source_url=url, published_at=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )
    db.commit()


def _count_steady_filings(n: int) -> tuple[int, dict]:
    engine, db, tenant, company = _session()
    filings = _filings(company.ticker, n)
    _existing_docs(db, company, tenant, [f["document_url"] for f in filings])
    db.expire_all()
    statements = _counter(engine)
    result = _service(filings)._ingest_filings(db, company, "0001")
    db.close()
    return len(statements), result


def test_ingest_filings_estado_estacionario_no_escala_por_filing():
    pocas, r3 = _count_steady_filings(3)
    muchas, r8 = _count_steady_filings(8)
    assert muchas == pocas, (pocas, muchas)
    assert pocas <= 2
    assert r3["documents_created"] == r8["documents_created"] == 0
    assert len(r8["items"]) == 8


def test_ingest_filings_crea_solo_nuevos_y_respeta_duplicados_del_lote():
    engine, db, tenant, company = _session()
    filings = _filings(company.ticker, 3)
    duplicado = dict(filings[1])
    lote = [filings[0], filings[1], duplicado, filings[2]]
    result = _service(lote)._ingest_filings(db, company, "0001")
    # La URL repetida dentro de la misma pasada no inserta dos veces.
    assert result["documents_created"] == 3
    assert len(result["items"]) == 4
    # Segunda pasada: nada nuevo (idempotente).
    again = _service(lote)._ingest_filings(db, company, "0001")
    assert again["documents_created"] == 0
    db.close()


def _count_steady_ir(n: int) -> tuple[int, dict]:
    engine, db, tenant, company = _session()
    items = [
        SimpleNamespace(title=f"Release {i}", url=f"https://ir.example.test/{company.ticker}/{i}")
        for i in range(n)
    ]
    _existing_docs(db, company, tenant, [item.url for item in items])
    db.expire_all()
    service = ThesisEvidenceService()
    service._fetch_ir = lambda url, ticker: SimpleNamespace(items=items, errors=[])
    statements = _counter(engine)
    result = service._ingest_ir(db, company)
    db.close()
    return len(statements), result


def test_ingest_ir_estado_estacionario_no_escala_por_release():
    pocas, r3 = _count_steady_ir(3)
    muchas, r10 = _count_steady_ir(10)
    assert muchas == pocas, (pocas, muchas)
    assert pocas <= 2
    assert r3["documents_created"] == r10["documents_created"] == 0
    assert len(r10["items"]) == 10
