"""Chat en inglés: panel plegado `sections` de la ficha y motivo de una tesis archivada.

Con el inglés elegido, la respuesta visible de la ficha ya salía en inglés
(#4046), pero el panel plegado («Ver detalle») seguía con «No hay hechos
financieros fiables almacenados…», «Aun no hay tesis almacenada…», las acciones
propuestas («Crear la primera tesis…») y el motivo de una tesis archivada
(«El modelo no es publicable…»). En español nada cambia.
"""

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.i18n import _request_language, set_language_scope
from app.models.entities import Base, Company
from app.schemas.api import VALUATION_WITHHELD_REASON
from app.services.chat_company_en import thesis_section_text_en
from app.services.chat_service import ChatService
from app.services.thesis_publication_gate import (
    MODEL_WITHHELD_REASON,
    NO_MODEL_WITHHELD_REASON,
    archived_thesis_notice,
    withheld_reason_en,
)

_SPANISH = (
    "No hay hechos financieros", "Calculo bloqueado", "No se recupero memoria", "No hay afirmaciones",
    "Aun no hay tesis", "No se encontraron contradicciones", "Faltan entradas", "seguir monitorizando",
    "Hay que revisar", "Crear la primera tesis", "Ingerir hechos", "Revisar afirmaciones",
)


@pytest.fixture(autouse=True)
def _flag(monkeypatch):
    monkeypatch.setenv("I18N_GENERATION_ENABLED", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _ask(language: str, question: str):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    db.info["tenant_id"] = 1
    db.info["language"] = language
    db.add(Company(ticker="ASTS", name="ASTS Inc", exchange="NASDAQ", currency="USD",
                   company_type="platform", valuation_model="unassigned"))
    db.commit()
    token = set_language_scope(language)
    try:
        return asyncio.run(ChatService().answer(db, question, "portfolio", None, use_jev=False))
    finally:
        _request_language.reset(token)


def test_folded_sections_and_actions_in_english():
    response = _ask("en", "Tell me about ASTS")
    bodies = {section.key: section.body for section in response.sections}
    assert bodies["facts"] == "- There are no reliable stored financial facts for this company."
    assert bodies["calculations"] == "- Calculation blocked: stored financial facts are missing."
    assert bodies["user_hypotheses"] == "- No relevant user memory was retrieved."
    assert bodies["inferences"] == "No thesis stored yet for ASTS."
    assert bodies["insufficient_data"].startswith("- Missing stored inputs: revenue")
    assert bodies["conclusion"].endswith("keep monitoring.")
    assert "Create the first thesis for ASTS" in response.proposed_actions
    text = "\n".join([*bodies.values(), *response.proposed_actions])
    for spanish in _SPANISH:
        assert spanish not in text


def test_folded_sections_unchanged_in_spanish():
    response = _ask("es", "Háblame de ASTS")
    bodies = {section.key: section.body for section in response.sections}
    assert bodies["facts"] == "- No hay hechos financieros fiables almacenados para esta empresa."
    assert bodies["inferences"] == "Aun no hay tesis almacenada para ASTS."
    assert bodies["conclusion"] == (
        "- La evidencia recuperada no exige un cambio automatico de tesis; seguir monitorizando."
    )
    assert "Crear la primera tesis para ASTS" in response.proposed_actions


def test_archived_thesis_reason_in_english():
    thesis = SimpleNamespace(id=7, version=3, created_at=datetime(2026, 9, 1, tzinfo=UTC), status="final",
                             rating="buy", expected_value=None, current_price=None)
    assert withheld_reason_en(MODEL_WITHHELD_REASON).startswith("The model is not publishable")
    assert withheld_reason_en(NO_MODEL_WITHHELD_REASON).startswith("There is no verified publishable model")
    assert withheld_reason_en(VALUATION_WITHHELD_REASON).startswith("Valuation not available")
    assert withheld_reason_en("motivo nuevo") == "motivo nuevo"
    assert thesis_section_text_en("ASTS", thesis, MODEL_WITHHELD_REASON) == (
        "Archived thesis v3 (2026-09-01): The model is not publishable; the archived text and figures are "
        "not current analysis. [thesis_version:7]"
    )
    # El castellano y el valor guardado no cambian.
    assert archived_thesis_notice(thesis, MODEL_WITHHELD_REASON) == (
        "Tesis archivada v3 (2026-09-01): El modelo no es publicable; el texto y las cifras archivados no son "
        "análisis actual."
    )
