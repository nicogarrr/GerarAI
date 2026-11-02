"""Herramientas del experto fiscal: la posición suma todas tus carteras y «hoy» es el día de Madrid.

Antes, ``user_position`` devolvía SOLO la primera fila de la empresa: con la
misma acción en dos carteras, el experto fiscal razonaba con media posición.
Ahora suma cantidades e importes de todas tus filas abiertas (coste medio
ponderado si comparten divisa; si falta un importe en alguna fila se deja
vacío en vez de dar una suma parcial). Y la fecha por defecto de las
herramientas (ventana de noticias, año de los tramos del IRPF, fecha de la
fuente) es el día de Madrid (``local_today``), no el del servidor en UTC.
SQLite en memoria, sin red.
"""

from __future__ import annotations

from datetime import date

from app.models.entities import Company, Position
from app.services.expert_team import RunContext, build_tools
from app.services.expert_team import tools as team_tools
from tests.test_expert_team_experts import TODAY, db  # noqa: F401 — fixture compartida


def _msft(session) -> Company:
    return session.query(Company).filter(Company.ticker == "MSFT").one()


def test_position_sums_every_portfolio(db):  # noqa: F811
    msft = _msft(db)
    db.add_all(
        [
            Position(tenant_id=1, company_id=msft.id, quantity=5, average_cost=360, market_value_base=2000.0,
                     currency="USD"),
            Position(tenant_id=1, company_id=msft.id, quantity=0, average_cost=999, market_value_base=0.0,
                     currency="USD"),  # vendida: no cuenta
        ]
    )
    db.commit()
    out = build_tools(db, today=TODAY)["user_position"].fn(RunContext(tenant_id=1, ticker="MSFT"))
    assert out is not None
    assert out.data["quantity"] == 15.0
    assert out.data["average_cost"] == 320.0  # (10·300 + 5·360) / 15
    assert out.data["market_value_base"] == 6000.0
    assert out.data["positions_count"] == 2
    assert out.data["currency"] == "USD"
    assert out.data["cost_basis_base"] is None  # la primera fila no lo tiene: sin suma parcial


def test_position_with_mixed_currencies_has_no_average(db):  # noqa: F811
    msft = _msft(db)
    db.add(Position(tenant_id=1, company_id=msft.id, quantity=2, average_cost=280, currency="EUR"))
    db.commit()
    out = build_tools(db, today=TODAY)["user_position"].fn(RunContext(tenant_id=1, ticker="MSFT"))
    assert out is not None
    assert out.data["quantity"] == 12.0
    assert out.data["average_cost"] is None and out.data["currency"] is None


def test_single_position_unchanged_and_other_tenant_isolated(db):  # noqa: F811
    out = build_tools(db, today=TODAY)["user_position"].fn(RunContext(tenant_id=1, ticker="MSFT"))
    assert out is not None
    assert out.data["quantity"] == 10.0 and out.data["average_cost"] == 300.0
    assert out.data["market_value_base"] == 4000.0  # el 1.0 es del otro tenant


def test_default_day_is_madrid(db, monkeypatch):  # noqa: F811
    monkeypatch.setattr(team_tools, "local_today", lambda: date(2027, 1, 1))
    bands = build_tools(db)["irpf_savings_bands"].fn(RunContext(tenant_id=1, ticker="MSFT"))
    assert bands.data["year"] == 2027
    position = build_tools(db)["user_position"].fn(RunContext(tenant_id=1, ticker="MSFT"))
    assert position is not None and position.source["date"] == "2027-01-01"
