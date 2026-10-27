"""0030: upgrade/downgrade con datos preexistentes, sin perdidas.

Siembra model_aliases + decision_journal_entries (+ su company) sobre el
esquema 0029, sube a 0031 y vuelve a bajar: las filas deben sobrevivir
intactas en ambas direcciones porque 0030 solo crea indices. El downgrade
revierte exactamente los indices que creo el upgrade. El round trip se
queda en <=0031: 0032 es forward-only (se prueba aparte que su downgrade
levanta en limpio, sin DDL parcial).
"""

import os
import shutil
import subprocess
import sys
import tempfile
from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

DATA_ENGINE_DIR = Path(__file__).resolve().parents[1]
REVISION_0029 = "0029_manager_holding_filing_date"
REVISION_0031 = "0031_propick_runs"
REVISION_0032 = "0032_tenant_uniques_fk_actions"

INDEXES_0030 = [
    ("ix_news_events_company_id", "news_events"),
    ("ix_news_events_company_date", "news_events"),
    ("ix_risk_events_company_id", "risk_events"),
    ("ix_risk_events_company_status", "risk_events"),
    ("ix_claims_thesis_version_id", "claims"),
    ("ix_claim_evidence_document_id", "claim_evidence"),
    ("ix_claim_evidence_document_chunk_id", "claim_evidence"),
    ("ix_thesis_diffs_from_version_id", "thesis_diffs"),
    ("ix_thesis_diffs_to_version_id", "thesis_diffs"),
    ("ix_thesis_changes_from_version_id", "thesis_changes"),
    ("ix_thesis_changes_to_version_id", "thesis_changes"),
    ("ix_research_reviews_thesis_change_id", "research_reviews"),
    ("ix_research_reviews_claim_id", "research_reviews"),
    ("ix_research_reviews_news_event_id", "research_reviews"),
    ("ix_evidence_suggestions_document_id", "evidence_suggestions"),
    ("ix_evidence_suggestions_suggested_claim_id", "evidence_suggestions"),
    ("ix_call_claims_linked_result_id", "call_claims"),
    ("ix_research_alerts_review_id", "research_alerts"),
    ("ix_earnings_runs_thesis_change_id", "earnings_runs"),
]


def _alembic(database_url: str, *args: str) -> None:
    env = {**os.environ, "DATABASE_URL": database_url}
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=DATA_ENGINE_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, result.stderr


def _alembic_result(database_url: str, *args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "DATABASE_URL": database_url}
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=DATA_ENGINE_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )


def _index_names(database_url: str, table: str) -> set[str]:
    engine = create_engine(database_url)
    try:
        return {index["name"] for index in inspect(engine).get_indexes(table)}
    finally:
        engine.dispose()


def _seed_preexisting_rows(database_url: str) -> tuple[int, int]:
    """Siembra via ORM (0030 no anade columnas: el ORM vale sobre 0029)."""
    from sqlalchemy.orm import sessionmaker

    from app.models.entities import ModelAlias, Tenant

    engine = create_engine(database_url)
    session = sessionmaker(bind=engine)()
    try:
        tenant = Tenant(external_id="ext-seed-0030", name="Seed Tenant")
        db_tenant = tenant
        session.add(db_tenant)
        session.flush()
        session.add(
            ModelAlias(
                internal_alias="seed-alias-0030",
                provider="seed-provider",
                provider_model_id="seed-model-1",
                enabled=True,
                context_window=128000,
                input_cost=Decimal("0.5"),
                output_cost=Decimal("1.5"),
                supported_capabilities=["text"],
            )
        )
        # SQL explicito, no ORM: migraciones posteriores (p.ej. 0043) anaden
        # columnas a companies y el INSERT del ORM las incluiria sobre el
        # esquema 0029, que aun no las tiene.
        session.execute(
            text(
                "INSERT INTO companies (ticker, name, exchange, currency, sector, industry,"
                " company_type, valuation_model, special_sources, special_risks, factor_tags,"
                " created_at, updated_at)"
                " VALUES ('SEED30', 'Seed Preexisting Co', 'NASDAQ', 'USD', 'Unknown',"
                " 'Unknown', 'operating', 'dcf', '[]', '[]', '[]',"
                " '2024-05-01 00:00:00', '2024-05-01 00:00:00')"
            )
        )
        session.flush()
        company_id = session.scalar(text("SELECT id FROM companies WHERE ticker='SEED30'"))
        # Igual que companies: #2348 anade transaction_id a decision_journal_entries
        # y el INSERT del ORM la incluiria sobre el esquema 0029.
        session.execute(
            text(
                "INSERT INTO decision_journal_entries (tenant_id, company_id, decision_date, decision,"
                " rationale, what_must_be_true, price, status, metadata, created_at, updated_at)"
                " VALUES (:tenant, :company, '2024-05-01', 'buy', 'seeded before 0030',"
                " '[\"revenue grows\"]', 100.5, 'open', '{}', '2024-05-01 00:00:00', '2024-05-01 00:00:00')"
            ),
            {"tenant": db_tenant.id, "company": company_id},
        )
        session.commit()
        alias_id = session.scalar(text("SELECT id FROM model_aliases WHERE internal_alias='seed-alias-0030'")) or 0
        journal_id = session.scalar(
            text("SELECT id FROM decision_journal_entries WHERE rationale='seeded before 0030'")
        ) or 0
        return int(alias_id), int(journal_id)
    finally:
        session.close()
        engine.dispose()


def test_0030_upgrade_downgrade_preserves_preexisting_data():
    temp_dir = Path(tempfile.mkdtemp(prefix="cavaai_0030_"))
    database_url = f"sqlite:///{(temp_dir / 'preexisting.db').as_posix()}"
    try:
        _alembic(database_url, "upgrade", REVISION_0029)
        alias_id, journal_id = _seed_preexisting_rows(database_url)

        _alembic(database_url, "upgrade", REVISION_0031)
        engine = create_engine(database_url)
        try:
            with engine.connect() as conn:
                alias = conn.execute(
                    text("SELECT provider, context_window FROM model_aliases WHERE id=:id"),
                    {"id": alias_id},
                ).one()
                assert alias.provider == "seed-provider"
                assert alias.context_window == 128000
                journal = conn.execute(
                    text("SELECT decision, price FROM decision_journal_entries WHERE id=:id"),
                    {"id": journal_id},
                ).one()
                assert journal.decision == "buy"
                assert float(journal.price) == 100.5
        finally:
            engine.dispose()
        for name, table in INDEXES_0030:
            assert name in _index_names(database_url, table), f"{name} missing after upgrade"

        _alembic(database_url, "downgrade", REVISION_0029)
        engine = create_engine(database_url)
        try:
            with engine.connect() as conn:
                # 2 filas: la historica 'opencode-go' (0017, destructiva
                # documentada aparte) + la sembrada antes de 0030.
                assert (
                    conn.execute(text("SELECT COUNT(*) FROM model_aliases")).scalar() == 2
                )
                assert sorted(
                    row.internal_alias
                    for row in conn.execute(text("SELECT internal_alias FROM model_aliases"))
                ) == ["deepseek-v4-flash", "seed-alias-0030"]
                assert (
                    conn.execute(text("SELECT COUNT(*) FROM decision_journal_entries")).scalar()
                    == 1
                )
                assert (
                    conn.execute(
                        text("SELECT COUNT(*) FROM companies WHERE ticker='SEED30'")
                    ).scalar()
                    == 1
                )
        finally:
            engine.dispose()
        for name, table in INDEXES_0030:
            assert name not in _index_names(database_url, table), f"{name} survived downgrade"
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_0032_rejects_downgrade_without_partial_ddl():
    temp_dir = Path(tempfile.mkdtemp(prefix="cavaai_0032_"))
    database_url = f"sqlite:///{(temp_dir / 'forward_only.db').as_posix()}"
    try:
        _alembic(database_url, "upgrade", "head")
        result = _alembic_result(database_url, "downgrade", REVISION_0031)
        assert result.returncode != 0
        assert "forward-only" in result.stderr
        # Sin DDL parcial: sigue en 0032 y la constraint tenant-scoped existe.
        current = _alembic_result(database_url, "current")
        assert REVISION_0032 in current.stdout
        engine = create_engine(database_url)
        try:
            uniques = {
                constraint["name"]
                for constraint in inspect(engine).get_unique_constraints("fund_managers")
            }
            assert "uq_fund_manager_tenant_cik" in uniques
        finally:
            engine.dispose()
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
