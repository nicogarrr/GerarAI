"""Chat: la fecha de las noticias guardadas sale en el día de Madrid.

NewsEvent.date va en UTC. Una noticia de las 23:30 UTC del 18 oct (01:30 del
19 en Madrid, horario de verano) salía en el chat «18 oct 2026»; la app la
muestra con la fecha local. Vale para las noticias de una empresa y para las
de tus posiciones.
"""

import asyncio
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Company, NewsEvent, Position
from app.models.entities import Base
from app.services.chat_service import ChatService


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = 1
        yield session


def _setup(db):
    asts = Company(ticker="ASTS", name="AST SpaceMobile", exchange="NASDAQ", company_type="platform",
                   valuation_model="unassigned", currency="USD")
    db.add(asts)
    db.flush()
    db.add(Position(tenant_id=1, company_id=asts.id, quantity=10, average_cost=20, currency="USD",
                    market_value=300, market_value_base=300, as_of=date.today()))
    db.add(NewsEvent(tenant_id=1, company_id=asts.id, title="AST SpaceMobile anuncia acuerdo con operadora",
                     summary="AST SpaceMobile firma un acuerdo", source="SEC",
                     date=datetime(2026, 10, 18, 23, 30, tzinfo=UTC)))
    db.add(NewsEvent(tenant_id=2, company_id=asts.id, title="AST SpaceMobile noticia privada de otro",
                     summary="AST SpaceMobile", source="SEC", date=datetime(2026, 10, 18, 23, 30, tzinfo=UTC)))
    db.info.pop("tenant_id", None)
    db.commit()
    db.info["tenant_id"] = 1


@pytest.mark.parametrize(("question", "path"), [
    ("¿Qué noticias hay de ASTS últimamente y cómo afectan a mi cartera?", "company_news"),
    ("¿Qué noticias hay de mis empresas?", "portfolio_news"),
])
def test_news_date_is_madrid_day(db, question, path):
    _setup(db)
    response = asyncio.run(ChatService().answer(db, question, "portfolio", None))
    assert response.llm_trace["path"] == path
    assert "AST SpaceMobile anuncia acuerdo con operadora' (19 oct 2026" in response.answer
    assert "18 oct" not in response.answer
    assert "privada de otro" not in response.answer
