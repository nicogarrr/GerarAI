"""Sesiones de investigación y carteras: textos en blanco.

``min_length`` cuenta espacios: una sesión con título «   » y pregunta «   »
se guardaba (200) y quedaba en la lista sin texto. Ahora es 422, como las
notas, afirmaciones y diario de decisiones.
"""

import pytest
from pydantic import ValidationError

from app.api.routes.portfolio import CreatePortfolioInput
from app.schemas.api import ResearchSessionCreate


@pytest.mark.parametrize(
    ("title", "question"),
    [("   ", "¿Por qué baja?"), ("Margen", "   "), ("\t\n", "\u00a0\u00a0\u00a0"), ("Margen", " ¿ ")],
)
def test_sesion_con_titulo_o_pregunta_en_blanco_se_rechaza(title, question):
    with pytest.raises(ValidationError):
        ResearchSessionCreate(title=title, question=question)


def test_sesion_normal_sigue_valiendo_sin_recortar():
    session = ResearchSessionCreate(title=" Margen ", question="¿Por qué?")
    assert session.title == " Margen "
    assert session.question == "¿Por qué?"


@pytest.mark.parametrize("name", ["   ", "\t", "\u00a0"])
def test_cartera_con_nombre_en_blanco_se_rechaza(name):
    # Se guardaba (201) una cartera con nombre «» tras recortar los espacios.
    with pytest.raises(ValidationError):
        CreatePortfolioInput(name=name)


def test_cartera_con_nombre_normal_sigue_valiendo():
    assert CreatePortfolioInput(name=" Principal ").name == " Principal "
