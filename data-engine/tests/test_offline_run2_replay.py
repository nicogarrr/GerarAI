"""Replay offline de las respuestas reales del ensayo run2 (final 48d0127).

Opcional: requiere THESIS_RUN2_REPLAY_JSON (captura cruda de respuestas,
lista de dicts con flow/text) y THESIS_RUN2_PACK_JSON (pack offline exacto
del ensayo, con deep_facts/news_request). Capturas privadas: nunca forman
parte del repo. Sin ambas variables, cada test se salta.

El deep se replaya COMPLETO contra el pack real adjunto (28 hechos fA..fAB):
toda cifra de la prosa debe anclar a ese pack, nunca a hechos reconstruidos
desde la propia respuesta.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from app.services.thesis_deep_narrative import _validate_sections
from app.services.thesis_news_narrative import validate_output

pytestmark = pytest.mark.skipif(
    not (os.environ.get("THESIS_RUN2_REPLAY_JSON") and os.environ.get("THESIS_RUN2_PACK_JSON")),
    reason="replay offline run2: define THESIS_RUN2_REPLAY_JSON y THESIS_RUN2_PACK_JSON",
)


@pytest.fixture()
def run2() -> dict:
    responses = json.loads(Path(os.environ["THESIS_RUN2_REPLAY_JSON"]).read_text())
    pack = json.loads(Path(os.environ["THESIS_RUN2_PACK_JSON"]).read_text())
    texts = {item["flow"]: json.loads(item["text"]) for item in responses}
    assert set(texts) == {"news", "deep"}
    return {"texts": texts, "pack": pack}


def test_deep_run2_replay_completo_contra_pack_real(run2) -> None:
    """La narrativa deep del run2, rechazada en vivo por «642.62,», valida
    completa contra el pack real del ensayo tras el fix estrecho."""
    sections, rule = _validate_sections(run2["texts"]["deep"], run2["pack"]["deep_facts"])
    assert rule is None


def test_news_run2_ordinales_siguen_rechazados(run2) -> None:
    """La respuesta news del run2 (con «Un segundo riesgo») sigue rechazada:
    la prohibición ordinal es regla de diseño, no falso positivo."""
    raw = run2["texts"]["news"]
    user_msg = next(m["content"] for m in run2["pack"]["news_request"] if m["role"] == "user")
    headlines = json.loads(user_msg)["noticias"]
    ids_pack = {h["id"] for h in headlines}
    for sec in raw.values():
        assert set(sec["evidence_ids"]) <= ids_pack
    with pytest.raises(ValueError, match="cantidad_en_prosa_llm"):
        validate_output(raw, headlines)
