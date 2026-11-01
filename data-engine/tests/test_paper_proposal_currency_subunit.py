"""Paper trading: la moneda de la propuesta conserva la subunidad (GBp no es GBP).

El generador LLM ancla la propuesta a la moneda del quote de Yahoo; en Londres
es ``GBp`` (peniques). El esquema la pasaba por ``.upper()`` -> ``GBP`` y
``apply_quote`` exige la misma moneda que el quote (``GBp``): la propuesta de
cualquier ticker ``.L`` se quedaba «pendiente» para siempre, sin entrar nunca.
Tambien se aceptaba cualquier texto como moneda («XYZ»).
"""
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models import Tenant
from app.models.paper_trading import PaperTrade
from app.schemas.paper_trading import PaperProposal
from app.services.paper_trading_service import create_proposal, refresh_trades


def body(**kwargs):
    return {"proposal_key": "run-1-VOD", "ticker": "VOD.L", "direction": "long",
            "horizon": "short", "thesis": "Una tesis simulada con fuente y riesgos", "conviction": "0.8",
            "proposed_entry": "70", "stop": "60", "target": "90", "quantity": "10",
            "inference_basis": "Inferido a partir de los documentos oficiales", **kwargs}


@pytest.fixture
def db():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        session.add(Tenant(id=1, external_id="paper-pence"))
        session.commit()
        session.info["tenant_id"] = 1
        yield session
    engine.dispose()


@pytest.mark.parametrize(("sent", "stored"), [("GBp", "GBp"), ("ZAc", "ZAc"), ("usd", "USD"), ("GBX", "GBX")])
def test_moneda_conserva_la_subunidad(sent, stored):
    assert PaperProposal(**body(currency=sent)).currency == stored


@pytest.mark.parametrize("sent", ["XYZ", "NaN", "EURO"])
def test_moneda_inventada_se_rechaza(sent):
    with pytest.raises(ValidationError):
        PaperProposal(**body(currency=sent))


@pytest.mark.parametrize(("proposal_currency", "quote_currency"), [("GBp", "GBp"), ("GBX", "GBp")])
def test_propuesta_en_peniques_entra_con_el_quote_de_londres(db, proposal_currency, quote_currency):
    row = create_proposal(db, PaperProposal(**body(currency=proposal_currency)))
    row.created_at = datetime.now(UTC) - timedelta(minutes=5)
    db.commit()
    fresh = datetime.now(UTC)
    result = refresh_trades(db, lambda ticker: {"live_c": 68, "live_t": fresh.timestamp(), "currency": quote_currency})
    assert result["updated"] == 1
    db.expire_all()
    stored = db.get(PaperTrade, row.id)
    assert stored is not None
    assert stored.status == "open"
    assert stored.entry_price == Decimal(68)


def test_libras_y_peniques_no_se_mezclan(db):
    # Niveles en libras (GBP) y quote en peniques: no es la misma escala, no entra.
    row = create_proposal(db, PaperProposal(**body(currency="GBP", proposed_entry="0.70", stop="0.60", target="0.90")))
    row.created_at = datetime.now(UTC) - timedelta(minutes=5)
    db.commit()
    fresh = datetime.now(UTC)
    refresh_trades(db, lambda ticker: {"live_c": 68, "live_t": fresh.timestamp(), "currency": "GBp"})
    db.expire_all()
    stored = db.get(PaperTrade, row.id)
    assert stored is not None
    assert stored.status == "pending"
