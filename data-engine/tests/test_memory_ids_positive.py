"""Ids imposibles (0 o negativos) en /api/memory.

Las rutas comprobaban la existencia con ``if payload.x_id:``, así que un 0 se
saltaba la comprobación y se guardaba como referencia colgante (en Postgres,
violación de clave foránea → 500). Un id negativo nunca existe. Ahora 422 que
nombra el campo; los ids válidos siguen funcionando.
"""

from __future__ import annotations

import pytest

from tests.test_memory_claims_validation import env  # noqa: F401  (fixture)


@pytest.mark.parametrize("bad", [0, -1])
def test_nota_de_memoria_con_ids_imposibles_es_422(env, bad) -> None:  # noqa: F811
    call, ids = env
    for field in ("research_session_id", "source_id", "company_id"):
        res = call("POST", "/api/memory/memory-items",
                   {"content": "nota de prueba", field: bad})
        assert res.status_code == 422, (field, res.status_code, res.text)
        assert field in res.text
    ok = call("POST", "/api/memory/memory-items",
              {"content": "nota de prueba", "company_id": ids["a"], "source_id": 7})
    assert ok.status_code == 200, ok.text
    assert ok.json()["research_session_id"] is None


@pytest.mark.parametrize("bad", [0, -2])
def test_afirmacion_prueba_y_cambio_con_ids_imposibles_es_422(env, bad) -> None:  # noqa: F811
    call, ids = env
    res = call("POST", "/api/memory/claims",
               {"company_id": ids["a"], "statement": "Margen sube", "thesis_version_id": bad})
    assert res.status_code == 422, res.text
    claim = call("POST", "/api/memory/claims", {"company_id": ids["a"], "statement": "Margen sube"})
    assert claim.status_code == 200, claim.text
    claim_id = claim.json()["id"]
    for field in ("document_id", "document_chunk_id"):
        res = call("POST", f"/api/memory/claims/{claim_id}/evidence",
                   {"summary": "Lo dice el 10-K", field: bad})
        assert res.status_code == 422, (field, res.status_code, res.text)
    for field in ("from_version_id", "to_version_id", "company_id"):
        res = call("POST", "/api/memory/thesis/changes",
                   {"summary": "Cambio de tesis", field: bad})
        assert res.status_code == 422, (field, res.status_code, res.text)
    res = call("POST", "/api/memory/thesis/changes",
               {"summary": "Cambio de tesis", "company_id": ids["a"], "affected_claim_ids": [bad]})
    assert res.status_code == 422, res.text
