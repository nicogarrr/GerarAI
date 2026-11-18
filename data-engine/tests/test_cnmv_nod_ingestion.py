"""Ingesta CNMV NOD: solo emisores conocidos por NIF, importes N/D, idempotencia."""

from datetime import date

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models.entities import Base, Company, InsiderFiling, InsiderTransaction, Tenant
from app.services import cnmv_nod_ingestion
from app.services.connectors import cnmv_nod
from app.services.connectors.cnmv_nod import CNMVNODEntry


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Tenant(id=1, external_id="a"))
        session.add(
            Company(
                id=1,
                ticker="EBRO",
                name="EBRO FOODS",
                exchange="BME",
                company_type="compounders",
                valuation_model="dcf",
                isin="ES0112501012",
            )
        )
        session.commit()
        session.info["tenant_id"] = 1
        yield session
    engine.dispose()


def _entries() -> list[CNMVNODEntry]:
    return [
        CNMVNODEntry(
            filing_date=date(2026, 11, 17),
            issuer_name="EBRO FOODS, S.A.",
            nif="A47412333",
            declarant="EMPRESAS COMERCIALES E INDUSTRIALES VALENCIANAS, S.L.",
            motive="Persona Estrechamente Vinculada",
            registry_number="2026145125",
            document_url="https://www.cnmv.es/webservices/verdocumento/ver?e=AAA",
        ),
        CNMVNODEntry(
            filing_date=date(2026, 11, 17),
            issuer_name="EDREAMS ODIGEO, S.A.",
            nif="A02850956",  # no esta en la tabla revisada de cnmv_mapping
            declarant="Dana Philip Dunne",
            motive="Persona con Responsabilidad de Dirección",
            registry_number="2026145426",
            document_url="https://www.cnmv.es/webservices/verdocumento/ver?e=BBB",
        ),
    ]


def test_only_known_issuers_are_saved_and_amounts_stay_nd(db):
    result = cnmv_nod_ingestion.ingest_cnmv_nod(
        db, 1, date(2026, 11, 17), date(2026, 11, 18), entries=_entries()
    )
    assert result == {
        "received": 2,
        "skipped_known": 0,
        "skipped_unknown_nif": 1,
        "skipped_unknown_company": 0,
        "saved": 1,
        "truncated": 0,
    }
    filing = db.scalar(select(InsiderFiling))
    assert filing.form == "PDMR-ES"
    registro_esperado = "cnmv-nod-2026145125"
    assert filing.accession_number == registro_esperado
    assert filing.issuer_ticker == "EBRO"
    assert filing.issuer_cik == "A47412333"
    assert filing.filing_date == "2026-11-17"
    assert filing.report_date is None  # la fecha de operacion vive en el documento (fase 2)
    tx = db.scalar(select(InsiderTransaction))
    assert tx.insider == "EMPRESAS COMERCIALES E INDUSTRIALES VALENCIANAS, S.L."
    assert tx.officer_title == "Persona Estrechamente Vinculada"
    # La cabecera no declara sentido, importe ni moneda: N/D, nunca inventado.
    assert tx.code is None
    assert tx.shares is None
    assert tx.price is None
    assert tx.value is None
    assert tx.data_quality["header_only"] is True
    assert tx.data_quality["currency"] is None
    assert tx.data_quality["value_unknown"] is True
    assert "CNMV" in tx.data_quality["licence"]


def test_reingestion_never_duplicates(db):
    first = cnmv_nod_ingestion.ingest_cnmv_nod(
        db, 1, date(2026, 11, 17), date(2026, 11, 18), entries=_entries()
    )
    second = cnmv_nod_ingestion.ingest_cnmv_nod(
        db, 1, date(2026, 11, 17), date(2026, 11, 18), entries=_entries()
    )
    assert first["saved"] == 1
    assert second["saved"] == 0
    assert second["skipped_known"] == 1
    assert len(db.scalars(select(InsiderTransaction)).all()) == 1


def test_known_issuer_without_company_row_is_skipped(db):
    db.query(Company).delete()
    db.commit()
    result = cnmv_nod_ingestion.ingest_cnmv_nod(
        db, 1, date(2026, 11, 17), date(2026, 11, 18), entries=_entries()
    )
    assert result["saved"] == 0
    assert result["skipped_unknown_company"] == 1


def test_fingerprint_is_stable():
    assert cnmv_nod_ingestion.fingerprint("2026145125") == cnmv_nod_ingestion.fingerprint(
        "2026145125"
    )
    assert cnmv_nod_ingestion.fingerprint("2026145125") != cnmv_nod_ingestion.fingerprint(
        "2026145426"
    )
    assert cnmv_nod.PARSER_VERSION
