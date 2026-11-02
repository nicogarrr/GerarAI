"""Textos obligatorios que solo tienen espacios.

``min_length`` cuenta los espacios: «       » pasaba y se guardaba una nota de
memoria, una afirmación, una prueba, un cambio de tesis, una sección de tesis,
una entrada del diario de decisiones o una noticia manual sin texto (y una
métrica personalizada con nombre vacío). Ahora es 422; el texto válido se
guarda igual que antes (sin recortar).
"""

from __future__ import annotations

import pytest

from app.core.database import SessionLocal
from app.models import Company
from app.models.entities import ThesisVersion
from tests.test_memory_claims_validation import env  # noqa: F401  (fixture)

BLANKS = ["       ", " \t\n   \u00a0 "]


def _ticker(company_id: int) -> str:
    with SessionLocal() as db:
        return db.get(Company, company_id).ticker


@pytest.mark.parametrize("blank", BLANKS)
def test_textos_en_blanco_son_422(env, blank) -> None:  # noqa: F811
    call, ids = env
    ticker = _ticker(ids["a"])
    claim = call("POST", "/api/memory/claims", {"company_id": ids["a"], "statement": "Margen estable"})
    assert claim.status_code == 200, claim.text
    probes = [
        ("/api/memory/memory-items", {"content": blank}),
        ("/api/memory/claims", {"company_id": ids["a"], "statement": blank}),
        (f"/api/memory/claims/{claim.json()['id']}/evidence", {"summary": blank}),
        ("/api/memory/thesis/changes", {"summary": blank}),
        (f"/api/companies/{ticker}/decision-journal", {"decision": "buy", "rationale": blank}),
        ("/api/news/manual", {"text": blank * 3}),
        ("/api/screeners/custom-metrics", {"metric_key": "zz_blank", "name": blank, "formula": "1"}),
    ]
    for path, body in probes:
        res = call("POST", path, body)
        assert res.status_code == 422, (path, res.status_code, res.text)


def test_seccion_de_tesis_en_blanco_es_422(env) -> None:  # noqa: F811
    call, ids = env
    with SessionLocal() as db:
        ticker = db.get(Company, ids["b"]).ticker
        version = db.get(ThesisVersion, ids["thesis_b"]).id
    path = f"/api/memory/thesis/{ticker}/versions/{version}/sections"
    for body in ({"section_key": "   ", "title": "Riesgos"}, {"section_key": "riesgos", "title": "  \t "}):
        res = call("POST", path, body)
        assert res.status_code == 422, (body, res.status_code, res.text)
    ok = call("POST", path, {"section_key": "riesgos", "title": " Riesgos "})
    assert ok.status_code == 200, ok.text
    assert ok.json()["title"] == " Riesgos "


def test_texto_valido_se_guarda_igual(env) -> None:  # noqa: F811
    call, ids = env
    res = call("POST", "/api/memory/memory-items", {"content": "  nota real  "})
    assert res.status_code == 200, res.text
    assert res.json()["content"] == "  nota real  "
    res = call("POST", "/api/memory/claims", {"company_id": ids["a"], "statement": " Margen sube "})
    assert res.status_code == 200, res.text
