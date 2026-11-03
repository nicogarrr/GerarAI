"""Experto fiscal: cita el IRPF de vender hoy en vez de calcularlo él (y perderse).

Prueba real 2026-11-03 (cerebro-real-2, OpenCode Go, EXPERT_TEAM_ENABLED=true
en local): con «¿Merece la pena mantener Uber o venderla?» el experto fiscal
razonaba los tramos del ahorro a mano, agotaba su tope de salida
(finish_reason=length, 2.600 tokens, 21,8 s, el más lento del equipo) y en la
respuesta salía «Fiscal: sin datos suficientes». Además, una cuota que calcula
el modelo no está en la evidencia y el validador de citas la tiraría. Ahora
tiene una herramienta más, ``sale_tax_estimate``: la plusvalía latente de toda
la posición y el IRPF del ahorro de esa plusvalía, calculados por el código
(``calculate_savings_tax``, los mismos tramos que el resto de la app).
"""

from __future__ import annotations

from decimal import Decimal

from app.models.entities import Company, Position
from app.services.expert_team import RunContext, build_tools
from app.services.expert_team.citations import citation_validator
from app.services.expert_team.ledger import EvidenceLedger
from app.services.expert_team.models import Claim
from app.services.expert_team.roster import default_experts
from app.services.tax_irpf_filing import calculate_savings_tax
from tests.test_expert_team_experts import TODAY, db  # noqa: F401 — fixture compartida


def _msft_position(session, **values):
    msft = session.query(Company).filter(Company.ticker == "MSFT").one()
    for position in session.query(Position).filter(Position.company_id == msft.id, Position.tenant_id == 1):
        for key, value in values.items():
            setattr(position, key, value)
    session.commit()


def test_tax_expert_reads_the_sale_estimate():
    tax = next(spec for spec in default_experts() if spec.name == "tax")
    assert "sale_tax_estimate" in tax.tools


def test_estimate_is_the_code_irpf_of_the_latent_gain(db):  # noqa: F811
    _msft_position(db, cost_basis_base=Decimal("3000"), market_value_base=Decimal("4000"),
                   unrealized_pnl_base=Decimal("10000"), base_currency="EUR")
    out = build_tools(db, today=TODAY)["sale_tax_estimate"].fn(RunContext(tenant_id=1, ticker="MSFT"))
    assert out is not None
    assert out.data["gain_if_sold_all"] == 10000.0
    assert out.data["irpf_if_sold_all"] == float(calculate_savings_tax(Decimal("10000"), TODAY.year))
    assert out.data["base_currency"] == "EUR"
    assert out.source["table"] == "code:tax_irpf_filing.calculate_savings_tax"


def test_loss_owes_nothing(db):  # noqa: F811
    _msft_position(db, unrealized_pnl_base=Decimal("-500"), base_currency="EUR")
    out = build_tools(db, today=TODAY)["sale_tax_estimate"].fn(RunContext(tenant_id=1, ticker="MSFT"))
    assert out is not None
    assert out.data["gain_if_sold_all"] == -500.0 and out.data["irpf_if_sold_all"] == 0.0


def test_no_position_no_estimate(db):  # noqa: F811
    assert build_tools(db, today=TODAY)["sale_tax_estimate"].fn(RunContext(tenant_id=1, ticker="NOPE")) is None


def test_a_claim_with_the_estimate_passes_the_citation_validator(db):  # noqa: F811
    _msft_position(db, unrealized_pnl_base=Decimal("10000"), base_currency="EUR")
    out = build_tools(db, today=TODAY)["sale_tax_estimate"].fn(RunContext(tenant_id=1, ticker="MSFT"))
    ledger = EvidenceLedger()
    evidence = ledger.add(expert="tax", tool="sale_tax_estimate", source=out.source, data=out.data)
    tax = next(spec for spec in default_experts() if spec.name == "tax")
    owed = f"{out.data['irpf_if_sold_all']:,.0f}".replace(",", ".")
    claim = Claim(text=f"Si vendes hoy, pagarías unos {owed} € de IRPF.", citations=(evidence.id,))
    assert citation_validator()(claim, ledger, tax) == ""
