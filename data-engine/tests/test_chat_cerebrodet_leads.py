"""cerebro-det: leads seg06 e ins08 del benchmark Cerebro (2026-11-08), sin modelo.

- ins08: «¿Qué ha hecho Buffett con Apple en su último 13F?» acababa en
  «No tengo un fragmento verificable de ese autor»: pide su 13F, no una cita.
  Ahora responde con el último 13F guardado y el cambio frente al anterior.
- seg06: «¿Y si este mes aporto los 600 € del plan, cuánto tendría?» tras
  «¿Cuánto efectivo tengo?» iba a la vía general sin el saldo. Ahora suma el
  efectivo guardado y la aportación que da el usuario, con la cuenta a la vista.
Toda cifra sale de los datos guardados o de la pregunta.
"""

from __future__ import annotations

import asyncio
import re
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, CashBalance, FundManager, ManagerHolding
from app.schemas.api import ChatTurn
from app.services.chat_service import ChatService


class _NoLLM:
    name = "no-llm"
    model_router = None

    async def complete(self, *a, **k):
        raise AssertionError("esta respuesta no pasa por el modelo")


def _db() -> Session:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = Session(engine)
    session.info["tenant_id"] = 1
    return session


def _ask(db, question, history=None):
    return asyncio.run(
        ChatService(provider=_NoLLM()).answer(db, question, "portfolio", None, history=history)  # type: ignore[arg-type]
    )


def _seed_13f(db: Session, *, previous: bool = True) -> None:
    mgr = FundManager(cik="0001067983", name="BERKSHIRE HATHAWAY INC", last_report_date=date(2026, 6, 30), coverage="ok")
    db.add(mgr)
    db.flush()
    quarters = [(date(2026, 6, 30), "0000000000-26-000002", {"AAPL": ("APPLE INC", 60000, 280000000), "KO": ("COCA COLA CO", 28000, 400000000)})]
    if previous:
        quarters.append((date(2026, 3, 31), "0000000000-26-000001", {"AAPL": ("APPLE INC", 66000, 300000000), "KO": ("COCA COLA CO", 27000, 400000000)}))
    for report, accession, rows in quarters:
        for cusip, (name, value, shares) in rows.items():
            db.add(ManagerHolding(
                manager_id=mgr.id, accession_number=accession, report_date=report, filing_date=report,
                name_of_issuer=name, title_of_class="COM", cusip=cusip,
                value_usd_thousands=Decimal(value), shares=Decimal(shares), filing_url="https://www.sec.gov/f",
            ))
    db.commit()


def test_ins08_13f_de_buffett_con_apple_sin_modelo():
    db = _db()
    _seed_13f(db)
    resp = _ask(db, "¿Qué ha hecho Buffett con Apple en su último 13F?")

    assert resp.llm_trace["path"] == "investor_13f"
    assert "fragmento verificable" not in resp.answer
    assert "Warren Buffett (Berkshire Hathaway)" in resp.answer and "2026-06-30" in resp.answer
    assert "APPLE INC" in resp.answer and "COCA COLA" not in resp.answer
    assert "280.000.000 acciones" in resp.answer
    assert "redujo, -20.000.000 acciones" in resp.answer
    assert resp.sources and resp.sources[0]["type"] == "investor_13f"


def test_13f_por_firma_sin_empresa_lista_las_mayores_posiciones():
    db = _db()
    _seed_13f(db)
    resp = _ask(db, "Enséñame el último 13F de Berkshire")
    assert resp.llm_trace["path"] == "investor_13f"
    assert "APPLE INC" in resp.answer and "COCA COLA CO" in resp.answer
    assert "Cambios frente al 13F anterior (primero las posiciones más grandes):" in resp.answer


def test_13f_sin_historial_dice_que_falta_el_cambio():
    db = _db()
    _seed_13f(db, previous=False)
    resp = _ask(db, "¿Qué hizo Buffett con Apple en el 13F?")
    assert "N/D: falta el cambio de APPLE INC frente al 13F anterior" in resp.answer


def test_13f_no_ingerido_es_nd_con_motivo():
    resp = _ask(_db(), "¿Qué ha hecho Buffett con Apple en su último 13F?")
    assert resp.answer.startswith("N/D: falta el 13F de Berkshire Hathaway en la app (motivo:")
    assert not re.search(r"\d", resp.answer.replace("13F", ""))


def test_sin_13f_en_la_pregunta_no_cambia_la_ruta():
    from app.services.brain_13f_tools import answer_13f_question

    db = _db()
    _seed_13f(db)
    assert answer_13f_question(db, "¿Qué opina Buffett de Apple?") is None
    assert answer_13f_question(db, "¿Qué hay en el último 13F?") is None  # sin inversor nombrado


def _seed_cash(db: Session, balance: str | None = "3200", currency: str = "EUR") -> None:
    db.add(CashBalance(tenant_id=1, currency=currency, balance=None if balance is None else Decimal(balance), as_of=date(2026, 11, 7)))
    db.commit()


_SEG06 = "¿Y si este mes aporto los 600 € del plan, cuánto tendría?"
_HISTORY = [ChatTurn(role="user", content="¿Cuánto efectivo tengo?"),
            ChatTurn(role="assistant", content="Tienes efectivo guardado en tu cuenta.")]


def test_seg06_suma_el_efectivo_del_hilo_y_la_aportacion():
    db = _db()
    _seed_cash(db)
    resp = _ask(db, _SEG06, _HISTORY)

    assert resp.llm_trace["path"] == "account_cash_contribution"
    assert "3.200,00 €" in resp.answer
    assert "3.200,00 € + 600,00 € = 3.800,00 €" in resp.answer
    assert "No puedo responderte" not in resp.answer
    assert resp.sources and resp.sources[0]["type"] == "cash_balance"


def test_seg06_sin_saldo_en_esa_divisa_es_nd():
    db = _db()
    _seed_cash(db, currency="USD")
    resp = _ask(db, _SEG06, _HISTORY)
    assert "N/D: falta tu efectivo guardado en EUR (motivo: no hay saldo en esa divisa)" in resp.answer
    assert "3.800" not in resp.answer


def test_sin_hilo_de_efectivo_no_se_apropia_la_pregunta():
    from app.services.brain_account_tools import asks_cash_contribution

    assert not asks_cash_contribution(_SEG06, ["¿Qué tal va META?"])
    assert asks_cash_contribution("Si aporto 600 € a mi efectivo, ¿cuánto tendría?", [])
    assert not asks_cash_contribution("¿Cuánto tendría si aporto?", ["¿Cuánto efectivo tengo?"])  # sin importe


@pytest.mark.parametrize("amount,expected", [("1.200,50 €", "4.400,50 €"), ("150 euros", "3.350,00 €")])
def test_importes_en_formato_es(amount, expected):
    db = _db()
    _seed_cash(db)
    resp = _ask(db, f"¿Y si aporto {amount}, cuánto tendría?", _HISTORY)
    assert expected in resp.answer
