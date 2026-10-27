"""El red team automático no dispara avisos (prueba real realqa-16).

Añadir 12 empresas a la watchlist lanzaba 12 tesis automáticas. Cada una
pasaba por el red team, que abría una revisión y, con ella, un aviso entregado
en la app: «La valoración no se puede publicar todavía: faltan Deuda neta,
margen FCF…». El usuario veía 12 disparos en /alerts sin haber creado ninguna
alerta. Ahora la revisión sigue en la bandeja de revisión, pero los avisos
son solo los de las reglas del usuario.
"""

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.models.entities import AlertDelivery, Base, Company, ResearchAlert, ResearchReview
from app.services.red_team_service import RedTeamService
from app.services.review_alert_service import ReviewAlertService

TICKERS = ["CGEO.L", "CPT", "KKR", "POOL", "CB", "UNH", "HIMS", "RXRX", "NAUT", "ABCL", "IBRX", "AAPL"]


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = 1
        yield session


def _company(db: Session, ticker: str) -> Company:
    company = Company(
        ticker=ticker, name=ticker, exchange="NYSE", currency="USD",
        sector="S", industry="I", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def _count(db: Session, model) -> int:
    return db.scalar(select(func.count()).select_from(model)) or 0


def test_doce_empresas_nuevas_no_disparan_doce_avisos(db):
    for ticker in TICKERS:
        run = RedTeamService().run(db, _company(db, ticker))
        # Sin datos, la valoración no es publicable: el hallazgo sigue ahí.
        assert any(f["type"] == "valuation_not_publishable" for f in run.findings)
    assert _count(db, ResearchAlert) == 0
    assert _count(db, AlertDelivery) == 0
    # La revisión interna se conserva, una por empresa.
    reviews = db.scalars(select(ResearchReview).where(ResearchReview.review_type == "red_team")).all()
    assert len(reviews) == len(TICKERS)


def test_volver_a_pasar_el_red_team_tampoco_avisa(db):
    company = _company(db, "POOL")
    RedTeamService().run(db, company)
    RedTeamService().run(db, company)
    assert _count(db, ResearchAlert) == 0


def test_las_demas_revisiones_siguen_avisando(db):
    company = _company(db, "KKR")
    ReviewAlertService().create_review(
        db, review_type="claim_contradicted", title="Afirmación contradicha", summary="s",
        company_id=company.id, materiality_score=8, impact_direction="negative", claim_id=1,
    )
    db.commit()
    assert _count(db, ResearchAlert) == 1
    assert _count(db, AlertDelivery) == 1


def test_emit_false_solo_deja_la_revision(db):
    company = _company(db, "CB")
    review = ReviewAlertService().create_review(
        db, review_type="red_team", title="t", summary="s", company_id=company.id, emit=False,
    )
    db.commit()
    assert review.id is not None
    assert _count(db, ResearchAlert) == 0
