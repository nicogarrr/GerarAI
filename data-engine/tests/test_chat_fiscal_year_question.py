"""«¿Cuál es mi plusvalía realizada este año?» respondía con el ejercicio anterior.

El bloque fiscal del contexto personal usa por defecto el último ejercicio
cerrado (bien para «¿cuál es mi plusvalía?»), pero el año que pide la pregunta
se ignoraba: «este año» en noviembre de 2026 contestaba «Ejercicio 2025: …»
aunque las ventas de 2026 ya estuvieran guardadas.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base

NOW = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)


@pytest.fixture
def years(monkeypatch):
    import app.core.local_date as local_date
    import app.services.user_context as user_context

    monkeypatch.setattr(local_date, "_utc_now", lambda: NOW)
    seen: list[int] = []

    def fake_fiscal_block(db, year):
        seen.append(year)
        block = user_context.ContextBlock(key="fiscal")
        block.lines.append(f"- Ejercicio {year}: prueba.")
        return block

    monkeypatch.setattr(user_context, "_fiscal_block", fake_fiscal_block)
    return seen


def _ask(question: str) -> None:
    from app.services.personal_answer import answer_personal_question, detect_personal_intent

    intent = detect_personal_intent(question)
    assert intent is not None and intent.kind == "fiscal"
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.info["tenant_id"] = 1
        asyncio.run(answer_personal_question(db, question, intent, None, use_llm=False))
    engine.dispose()


@pytest.mark.parametrize(("question", "year"), [
    ("¿Cuál es mi plusvalía realizada este año?", 2026),
    ("¿Cuánto IRPF llevo este ejercicio?", 2026),
    ("¿Qué plusvalías tengo en 2024?", 2024),
    ("¿Cuál fue mi plusvalía del año pasado?", 2025),
    ("¿Cuál es mi plusvalía realizada?", 2025),
])
def test_el_ejercicio_es_el_que_pide_la_pregunta(years, question, year):
    _ask(question)
    assert years == [year]
