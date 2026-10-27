"""Snapshot por lote del indice de research: equivalencia con build() y queries acotadas.

El indice pedia un snapshot por empresa (~5 round trips x N). build_many
agrega con window functions + GROUP BY: las queries no crecen con N y el
resultado es IDENTICO al de build() empresa a empresa.
"""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

from app.models.entities import (
    Base,
    CalculatedMetric,
    Claim,
    Company,
    Document,
    FinancialFact,
    FundamentalModelVersion,
    ThesisChange,
    ThesisVersion,
    ValuationModel,
)
from app.services.company_snapshot_service import CompanySnapshotService


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _company(db: Session, ticker: str) -> Company:
    company = Company(
        ticker=ticker, name=f"{ticker} Co", exchange="NASDAQ", currency="USD",
        sector="Tech", industry="Tech", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def _fill(db: Session, company: Company, *, thesis_versions: int, changes: int) -> None:
    db.add(Document(company_id=company.id, title="10-K", source_type="sec"))
    db.add(FinancialFact(company_id=company.id, metric="revenue", value=Decimal("100"), period="FY2025"))
    db.add(Claim(company_id=company.id, statement="crece", status="verified"))
    db.add(CalculatedMetric(company_id=company.id, metric="growth", value=Decimal("0.1"), period="FY2025", formula="x"))
    for version in range(1, thesis_versions + 1):
        db.add(ThesisVersion(
            company_id=company.id, version=version, status="published",
            thesis_markdown="# T", executive_summary=f"resumen v{version}",
        ))
        db.add(FundamentalModelVersion(
            company_id=company.id, version=version, engine_version="e1", algorithm_version="a1",
            framework_key="growth", horizon_years=5, status="ok",
            input_fingerprint=f"f{company.id}-{version}", forecast_fingerprint=f"ff{company.id}-{version}",
            market_snapshot_fingerprint=f"mf{company.id}-{version}", valuation_snapshot_fingerprint=f"vf{company.id}-{version}",
        ))
        db.add(ValuationModel(company_id=company.id, model_type="dcf", version=version, status="ok"))
    for index in range(changes):
        db.add(ThesisChange(company_id=company.id, summary=f"cambio {index}"))
    db.commit()


def _dump(snapshot) -> dict:
    return snapshot.model_dump(mode="json")


def test_documents_count_collapses_archive_reingestas(db: Session):
    """F304: el contador DOCUMENTOS cuenta lo visible, no filas crudas.

    La misma pieza SEC se re-ingiere a diario con deriva de bytes: dos filas
    con la MISMA URL de archivo son un solo documento visible (la lista las
    colapsa). URLs vivas y filas sin URL no se colapsan nunca.
    """
    company = _company(db, "KO")
    archive = "https://www.sec.gov/Archives/edgar/data/21344/000002134426000001/ko-10k.htm"
    db.add(Document(
        company_id=company.id, title="10-K 2024", source_type="sec",
        source_url=archive, published_at=date(2024, 2, 20),
    ))
    db.add(Document(
        company_id=company.id, title="10-K 2024 re-ingesta", source_type="sec",
        source_url=archive, published_at=date(2024, 2, 21),
    ))
    db.add(Document(
        company_id=company.id, title="Página viva", source_type="url",
        source_url="https://example.com/ir",
    ))
    db.add(Document(company_id=company.id, title="Sin URL", source_type="upload"))
    db.commit()

    counts = CompanySnapshotService._counts_many(db, [company.id])[company.id]
    assert counts["documents"] == 3
    single = CompanySnapshotService._counts(db, company.id)
    assert single["documents"] == 3


def test_documents_count_scoped_to_current_tenant(db: Session):
    """Los agregados no heredan el filtro de carga por tenant: el contador
    filtra tenant explicitamente. Una empresa compartida (Company es global)
    puede tener documentos en varios tenants; cada uno cuenta solo los suyos.
    """
    company = _company(db, "KO")
    db.add(Document(company_id=company.id, title="10-K", source_type="sec",
                    source_url="https://www.sec.gov/Archives/edgar/data/21344/000002134426000001/ko-10k.htm"))
    db.add(Document(company_id=company.id, title="8-K", source_type="sec"))
    db.commit()

    db.info["tenant_id"] = 999
    for index in range(3):
        db.add(Document(company_id=company.id, title=f"Doc otro tenant {index}", source_type="upload"))
    db.commit()
    db.info["tenant_id"] = "tenant-test"

    counts = CompanySnapshotService._counts_many(db, [company.id])[company.id]
    assert counts["documents"] == 2
    assert CompanySnapshotService._counts(db, company.id)["documents"] == 2

    db.info["tenant_id"] = 999
    counts = CompanySnapshotService._counts_many(db, [company.id])[company.id]
    assert counts["documents"] == 3
    assert CompanySnapshotService._counts(db, company.id)["documents"] == 3


def test_documents_count_without_tenant_counts_everything(db: Session):
    """Escenario sin tenant en la sesion: sin filtro, se cuenta todo lo
    visible (comportamiento previo a F304 para los agregados)."""
    company = _company(db, "KO")
    db.add(Document(company_id=company.id, title="10-K", source_type="sec"))
    db.commit()
    db.info["tenant_id"] = 999
    db.add(Document(company_id=company.id, title="Doc otro tenant", source_type="upload"))
    db.commit()
    db.info.pop("tenant_id", None)

    counts = CompanySnapshotService._counts_many(db, [company.id])[company.id]
    assert counts["documents"] == 2
    assert CompanySnapshotService._counts(db, company.id)["documents"] == 2


def test_build_many_matches_build_company_by_company(db: Session):
    first = _company(db, "AAA")
    second = _company(db, "BBB")
    _fill(db, first, thesis_versions=3, changes=12)
    _fill(db, second, thesis_versions=1, changes=2)

    service = CompanySnapshotService()
    batch = service.build_many(db, [first, second])
    assert set(batch) == {first.id, second.id}
    for company in (first, second):
        assert _dump(batch[company.id]) == _dump(service.build(db, company))
    # La tesis elegida es la ultima version y los cambios quedan capados a 10.
    assert batch[first.id].latest_thesis.version == 3
    assert len(batch[first.id].recent_changes) == 10
    assert len(batch[second.id].recent_changes) == 2


def test_build_many_tie_created_at_matches_single_build(db: Session):
    """Empate total de created_at: el desempate por id hace determinista el
    orden y build_many coincide con build() empresa a empresa (sin el, el
    orden de los empates era libre del plan y podia divergir entre caminos)."""
    company = _company(db, "TIE")
    same = datetime(2026, 10, 1, tzinfo=UTC)
    for index in range(12):
        db.add(ThesisChange(company_id=company.id, summary=f"cambio {index}", created_at=same))
    db.commit()

    service = CompanySnapshotService()
    batch = service.build_many(db, [company])
    single = service.build(db, company)

    batch_summaries = [c.summary for c in batch[company.id].recent_changes]
    single_summaries = [c.summary for c in single.recent_changes]
    assert batch_summaries == single_summaries
    # Determinista: id DESC dentro del empate (el mas reciente primero).
    assert batch_summaries == [f"cambio {i}" for i in range(11, 1, -1)]


def test_build_many_queries_do_not_grow_with_n(db: Session):
    companies = [_company(db, f"T{i}") for i in range(5)]
    for company in companies:
        _fill(db, company, thesis_versions=1, changes=1)

    engine = db.get_bind()
    statements: list[str] = []

    @event.listens_for(engine, "before_cursor_execute")
    def count_statements(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    service = CompanySnapshotService()
    statements.clear()
    service.build_many(db, companies)
    batch_statements = len(statements)

    statements.clear()
    for company in companies:
        service.build(db, company)
    loop_statements = len(statements)

    # El lote agrega: ~13 queries para las 5 empresas, no 5 x N.
    assert batch_statements <= 15
    assert batch_statements < loop_statements


def test_build_many_empty_and_missing_layers(db: Session):
    assert CompanySnapshotService().build_many(db, []) == {}
    empty = _company(db, "EMPTY")
    batch = CompanySnapshotService().build_many(db, [empty])
    snapshot = batch[empty.id]
    assert snapshot.research_health.status == "empty"
    assert snapshot.counts.facts == 0
    assert snapshot.latest_thesis is None


def test_recent_changes_many_returns_deterministic_order(db: Session):
    """Sin ORDER BY externo la subquery con window devolvia orden arbitrario."""
    from datetime import datetime, timedelta

    company = _company(db, "ORD")
    base = datetime(2026, 1, 1, 12, 0, 0)
    for index in range(5):
        db.add(ThesisChange(
            company_id=company.id,
            summary=f"c{index}",
            created_at=base + timedelta(minutes=index),
        ))
    db.commit()

    # El ORDER BY va en la consulta EXTERNA: sin el, la window numera cada
    # particion pero las filas salen en orden arbitrario (Postgres no
    # garantiza el orden de la subquery).
    from sqlalchemy import event

    engine = db.get_bind()
    statements: list[str] = []

    @event.listens_for(engine, "before_cursor_execute")
    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    service = CompanySnapshotService()
    batch = service.build_many(db, [company])
    changes_queries = [
        s for s in statements
        if "FROM thesis_changes" in s and "row_number()" in s
    ]
    assert len(changes_queries) == 1
    assert changes_queries[0].rstrip().endswith(
        "ORDER BY anon_1.company_id, anon_1.created_at DESC, anon_1.id DESC"
    )

    ordered = [change.summary for change in batch[company.id].recent_changes]
    assert ordered == ["c4", "c3", "c2", "c1", "c0"]  # created_at DESC
    assert ordered == [
        change.summary for change in service.build(db, company).recent_changes
    ]


def test_all_counts_scoped_to_current_tenant(db: Session):
    """F315: los 8 conteos filtran tenant explícitamente, no solo documents.
    Una empresa compartida (Company es global) con filas en dos tenants
    cuenta solo las del tenant de la sesión, en _counts y en _counts_many.
    """
    from app.models.entities import ResearchAlert, ResearchReview

    company = _company(db, "KO")
    alert_seq = 0

    def fill_tenant():
        nonlocal alert_seq
        alert_seq += 1
        # Las unicidades son POR TENANT: dos altas del mismo tenant necesitan
        # metric/version/fingerprints distintos (alert_seq las desempata).
        db.add(FinancialFact(company_id=company.id, metric="revenue", value=Decimal("100"), period="FY2025"))
        db.add(CalculatedMetric(company_id=company.id, metric=f"growth-{alert_seq}", value=Decimal("0.1"), period="FY2025", formula="x"))
        db.add(Claim(company_id=company.id, statement="crece", status="verified"))
        db.add(ThesisVersion(company_id=company.id, version=alert_seq, status="published",
                             thesis_markdown="# T", executive_summary="resumen"))
        db.add(FundamentalModelVersion(
            company_id=company.id, version=alert_seq, engine_version="e1", algorithm_version="a1",
            framework_key="growth", horizon_years=5, status="ok",
            input_fingerprint=f"f-{db.info.get('tenant_id')}-{alert_seq}", forecast_fingerprint=f"ff-{db.info.get('tenant_id')}-{alert_seq}",
            market_snapshot_fingerprint=f"mf-{db.info.get('tenant_id')}-{alert_seq}", valuation_snapshot_fingerprint=f"vf-{db.info.get('tenant_id')}-{alert_seq}",
        ))
        db.add(ResearchReview(company_id=company.id, status="open", review_type="expectation", title="r"))
        db.add(ResearchAlert(
            company_id=company.id, status="open", alert_type="drift", title="a",
            # message y fingerprint son NOT NULL sin default, y fingerprint es
            # unico por tenant: cada alta lleva uno distinto.
            message="alerta de prueba",
            fingerprint=f"fp-{db.info.get('tenant_id')}-{alert_seq}",
        ))
        db.commit()

    db.info["tenant_id"] = "tenant-test"
    fill_tenant()
    db.info["tenant_id"] = 999
    fill_tenant()
    fill_tenant()

    db.info["tenant_id"] = "tenant-test"
    expected = {
        "facts": 1, "calculated_metrics": 1, "documents": 0, "claims": 1,
        "thesis_versions": 1, "model_versions": 1, "open_reviews": 1, "open_alerts": 1,
    }
    assert CompanySnapshotService._counts(db, company.id) == expected
    assert CompanySnapshotService._counts_many(db, [company.id])[company.id] == expected

    db.info["tenant_id"] = 999
    expected_otro = {key: value * 2 for key, value in expected.items()}
    assert CompanySnapshotService._counts(db, company.id) == expected_otro
    assert CompanySnapshotService._counts_many(db, [company.id])[company.id] == expected_otro


@pytest.mark.parametrize("convention,expected", [(None, None), ("future_formula", None), ("discount_to_value_v1", Decimal("0.3"))])
def test_snapshot_margin_requires_provenance_preserving_archived_number(db, convention, expected):
    company = _company(db, "MARGIN")
    _fill(db, company, thesis_versions=1, changes=0)
    thesis = db.scalar(select(ThesisVersion).where(ThesisVersion.company_id == company.id))
    thesis.margin_of_safety = Decimal("0.3")
    thesis.valuation_basis = {"margin_of_safety_convention": convention}
    db.commit()
    result = CompanySnapshotService().build(db, company)
    for summary in (result.latest_thesis, result.valuation_summary):
        assert summary.margin_of_safety == expected
        assert summary.archived_margin_of_safety == Decimal("0.3")
        assert summary.margin_of_safety_convention == convention
        assert summary.margin_of_safety_status == ("verified" if expected else "unknown_convention")
    assert thesis.margin_of_safety == Decimal("0.3")
