"""Fórmulas del screener con espacios en los bordes.

``ast.parse(" pe_ratio", mode="eval")`` lanza IndentationError: una fórmula de
ranking o de métrica personalizada pegada con un espacio delante daba
«Sintaxis de fórmula no válida» (crear, editar o ejecutar un screen ad hoc),
aunque create ya guardaba la fórmula recortada. Y editar un screen guardaba la
fórmula sin recortar, y "" en vez de None.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.routes.screeners import Criterion, ScreenCreate, update_screen
from app.models.entities import Base, SavedScreen
from app.services.screener_service import CustomMetricService, SafeFormula, ScreenerService


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


@pytest.mark.parametrize("formula", [" pe_ratio", "pe_ratio ", "\tpe_ratio * 2\n", "  -roe + 1  "])
def test_safe_formula_ignores_edge_whitespace(formula):
    parsed = SafeFormula(formula)
    assert parsed.names <= {"pe_ratio", "roe"}
    assert parsed.names


@pytest.mark.parametrize("formula", ["", "   ", "\n"])
def test_blank_formula_is_still_invalid(formula):
    with pytest.raises(ValueError):
        SafeFormula(formula)


def _screen(db: Session, ranking: str | None = "pe_ratio") -> SavedScreen:
    return ScreenerService().create_screen(
        db,
        name="Baratas",
        description="",
        criteria=[{"left": "pe_ratio", "operator": "<", "right": "15"}],
        ranking_formula=ranking,
        ranking_direction="asc",
        alerts_enabled=False,
    )


def test_create_screen_accepts_ranking_with_leading_space(db):
    screen = _screen(db, " pe_ratio ")
    assert screen.ranking_formula == "pe_ratio"


def _payload(ranking: str | None) -> ScreenCreate:
    return ScreenCreate(
        name="Baratas",
        criteria=[Criterion(left="pe_ratio", operator="<", right="15")],
        ranking_formula=ranking,
        ranking_direction="asc",
        alerts_enabled=False,
    )


def test_update_screen_stores_trimmed_ranking_like_create(db):
    screen = _screen(db)

    out = update_screen(screen.id, _payload("  roe * 2 "), db)

    assert out["ranking_formula"] == "roe * 2"
    assert db.get(SavedScreen, screen.id).ranking_formula == "roe * 2"  # type: ignore[union-attr]


def test_update_screen_empty_ranking_is_none_like_create(db):
    screen = _screen(db)

    out = update_screen(screen.id, _payload(""), db)

    assert out["ranking_formula"] is None


def test_custom_metric_formula_with_edge_spaces(db):
    metric = CustomMetricService().create(
        db, metric_key="pe_doble", name="PER doble", formula=" pe_ratio * 2 ",
        unit="decimal", description="",
    )
    assert metric.formula == "pe_ratio * 2"
