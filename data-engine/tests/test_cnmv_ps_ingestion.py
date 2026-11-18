"""Ingesta CNMV PS: filas PS-ES en schedule_13dg_filings, N/D y no mezcla US."""

from datetime import date

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models.entities import Base, Company, Schedule13DGFiling, Tenant
from app.services import cnmv_ps_ingestion, schedule13dg_service
from app.services.connectors.cnmv_ps import PSHolder, PSIssuerReport


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Tenant(id=1, external_id="a"))
        session.add(
            Company(
                id=1,
                ticker="ACX",
                name="ACERINOX",
                exchange="BME",
                company_type="cyclical",
                valuation_model="dcf",
                isin="ES0132105018",
            )
        )
        session.commit()
        session.info["tenant_id"] = 1
        yield session
    engine.dispose()


def _report() -> PSIssuerReport:
    return PSIssuerReport(
        nif="A-28250777",
        issuer_name="ACERINOX, S.A.",
        total_voting_rights=249335371,
        loyalty_voting_rights=0,
        page_url="https://www.cnmv.es/Portal/consultas/DerechosVoto/Notificaciones-Participaciones?qS={x}",
        holders=[
            PSHolder(
                holder_name="CORPORACION FINANCIERA ALBA, S.A.",
                pct_shares_total=18.958,
                pct_direct=18.958,
                pct_indirect=0.0,
                pct_instruments=0.0,
                pct_total=18.958,
                registry_date=date(2017, 3, 7),
                document_url="https://www.cnmv.es/webservices/verdocumento/ver?e=AAA",
            ),
            PSHolder(
                holder_name="THE GOLDMAN SACHS GROUP, INC.",
                pct_shares_total=2.202,
                pct_direct=0.0,
                pct_indirect=2.202,
                pct_instruments=2.074,
                pct_total=4.276,
                registry_date=date(2026, 11, 17),
                document_url="https://www.cnmv.es/webservices/verdocumento/ver?e=BBB",
            ),
        ],
    )


def _unknown_report() -> PSIssuerReport:
    return PSIssuerReport(
        nif="A02850956",  # no esta en la tabla revisada
        issuer_name="EDREAMS ODIGEO, S.A.",
        holders=[
            PSHolder(
                holder_name="Dana Philip Dunne",
                pct_shares_total=5.0,
                pct_direct=5.0,
                pct_indirect=0.0,
                pct_instruments=0.0,
                pct_total=5.0,
                registry_date=date(2026, 11, 10),
                document_url=None,
            )
        ],
    )


def test_saves_known_issuers_with_declared_percentages_only(db):
    result = cnmv_ps_ingestion.ingest_cnmv_ps(
        db, 1, date(2026, 11, 10), date(2026, 11, 18),
        reports=[_report(), _unknown_report()], issuers_seen=2,
    )
    assert result["saved"] == 2
    assert result["skipped_unknown_nif"] == 1
    rows = db.scalars(select(Schedule13DGFiling).order_by(Schedule13DGFiling.id)).all()
    assert all(row.form == "PS-ES" for row in rows)
    alba = next(row for row in rows if row.holder_name == "CORPORACION FINANCIERA ALBA, S.A.")
    assert alba.issuer_ticker == "ACX"
    assert alba.issuer_cik == "A-28250777"
    assert alba.percent_of_class == 18.958
    assert alba.filing_date == "2017-03-07"
    # La tabla no declara acciones ni sole/shared: N/D, nunca derivados.
    assert alba.aggregate_shares is None
    assert alba.sole_voting_power is None
    assert alba.shared_voting_power is None
    detail = alba.holders[0]
    assert detail["pct_indirect"] == 0.0
    assert detail["total_voting_rights"] == 249335371
    goldman = next(row for row in rows if "GOLDMAN" in row.holder_name)
    assert goldman.holders[0]["pct_instruments"] == 2.074


def test_reingestion_never_duplicates(db):
    first = cnmv_ps_ingestion.ingest_cnmv_ps(
        db, 1, date(2026, 11, 10), date(2026, 11, 18), reports=[_report()], issuers_seen=1
    )
    second = cnmv_ps_ingestion.ingest_cnmv_ps(
        db, 1, date(2026, 11, 10), date(2026, 11, 18), reports=[_report()], issuers_seen=1
    )
    assert first["saved"] == 2
    assert second["saved"] == 0
    assert second["skipped_known"] == 2
    assert len(db.scalars(select(Schedule13DGFiling)).all()) == 2


def test_ps_es_rows_never_appear_in_us_13dg_screen(db):
    cnmv_ps_ingestion.ingest_cnmv_ps(
        db, 1, date(2026, 11, 10), date(2026, 11, 18), reports=[_report()], issuers_seen=1
    )
    db.add(
        Schedule13DGFiling(
            tenant_id=1,
            accession_number="0001234567-26-000001",
            form="SC 13G",
            issuer_cik="12345",
            issuer_ticker="ACX",
            holder_name="US FUND",
            percent_of_class=6.5,
            holders=[],
            filing_date="2026-11-01",
            parser_version="t",
            status="parsed",
        )
    )
    db.commit()
    out = schedule13dg_service.filings_for_ticker(db, "ACX")
    assert out["count"] == 1
    assert [f["form"] for f in out["filings"]] == ["SC 13G"]
    assert out["source"] == "SEC EDGAR · SC 13D/13G"


def test_schedule13dg_nd_helpers_never_invent_values():
    # Un campo no parseado se muestra N/D, nunca 0 ni vacio.
    assert schedule13dg_service._nd_number(None) == "N/D"
    assert schedule13dg_service._nd_number(1234567) == "1.234.567"
    assert schedule13dg_service._nd_percent(None) == "N/D"
    assert schedule13dg_service._nd_percent(3.04) == "3,0 %"
    assert schedule13dg_service._nd_text("") == "N/D"
