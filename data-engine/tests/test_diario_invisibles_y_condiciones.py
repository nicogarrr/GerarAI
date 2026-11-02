"""Diario de decisiones: textos que se ven vacíos y condiciones sin tope.

- Un motivo hecho solo de espacios de anchura cero (U+200B…) se veía vacío en
  pantalla pero pasaba ``not_blank`` porque ``str.strip()`` no los quita.
- Cada item de «qué tiene que ser verdad» no tenía tope: se guardaban 100k
  caracteres en una sola condición. Ahora 1000 por item (30 items como antes).
"""

from __future__ import annotations

from app.core.database import SessionLocal
from app.models import Company
from tests.test_memory_claims_validation import env  # noqa: F401  (fixture)

INVISIBLE = "\u200b\u200c\u200d\u2060\ufeff" * 3


def _path(company_id: int) -> str:
    with SessionLocal() as db:
        return f"/api/companies/{db.get(Company, company_id).ticker}/decision-journal"


def test_motivo_de_solo_invisibles_es_422(env) -> None:  # noqa: F811
    call, ids = env
    path = _path(ids["a"])
    for rationale in (INVISIBLE, " \u200b \u200b\t\u00a0\ufeff "):
        res = call("POST", path, {"decision": "buy", "rationale": rationale})
        assert res.status_code == 422, (repr(rationale), res.text)
    # Un motivo real con un invisible pegado se guarda tal cual.
    ok = call("POST", path, {"decision": "buy", "rationale": "\u200bMargen estable"})
    assert ok.status_code == 201, ok.text
    assert ok.json()["rationale"] == "\u200bMargen estable"


def test_condicion_demasiado_larga_es_422(env) -> None:  # noqa: F811
    call, ids = env
    path = _path(ids["a"])
    largo = call(
        "POST", path, {"decision": "buy", "rationale": "Margen estable", "what_must_be_true": ["x" * 1001]}
    )
    assert largo.status_code == 422, largo.text
    ok = call(
        "POST",
        path,
        {"decision": "buy", "rationale": "Margen estable", "what_must_be_true": ["y" * 1000, "Crece"]},
    )
    assert ok.status_code == 201, ok.text
    assert ok.json()["what_must_be_true"] == ["y" * 1000, "Crece"]
