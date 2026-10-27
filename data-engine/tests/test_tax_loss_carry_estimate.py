"""Arrastre estimativo de saldos negativos (art. 49 LIRPF) sin anexo C.3.

Sin los saldos declarados, el libro estima lo pendiente. Antes cada
ejercicio previo con saldo negativo se arrastraba ENTERO, aunque un
ejercicio intermedio ya lo hubiera compensado. Ejemplo a mano:

  2022: -1.000 € de GyP
  2023: +600 € de GyP  -> compensa 600 de 2022 (art. 49.1.b)
  2024: 0
  2025: +1.000 € de GyP
  => pendiente a 1/1/2025: 400 € (no 1.000). Aplicado en 2025: 400.
"""

from decimal import Decimal

from app.services.tax_irpf_filing import build_loss_compensation


def _prior(year, net, rcm=None, incomplete=False):
    return {"year": year, "net_gyp_base": net, "net_rcm_base": rcm, "incomplete": incomplete}


def test_intermediate_gain_consumes_prior_loss():
    out = build_loss_compensation(
        [_prior(2021, 0.0), _prior(2022, -1000.0), _prior(2023, 600.0), _prior(2024, 0.0)],
        Decimal("1000"), Decimal("0"), 2025,
    )
    assert out["estimativo"] is True
    [loss] = out["prior_losses"]
    assert loss["year"] == 2022
    assert loss["pending_start_base"] == 400.0
    assert loss["applied_to_gains_base"] == 400.0
    assert out["remaining_to_carry_base"] == 0.0


def test_fully_consumed_loss_disappears():
    out = build_loss_compensation(
        [_prior(2022, -300.0), _prior(2023, 500.0)], Decimal("200"), Decimal("0"), 2025,
    )
    assert out["prior_losses"] == []
    assert out["applied_to_gains_total_base"] == 0.0


def test_intermediate_dividends_absorb_25_percent():
    # 2023: perdida de 1.000 y 400 de dividendos -> 100 (25 %) compensan en 2023
    # (casilla 0446 de ese ejercicio). 2024: 0 GyP, 800 de dividendos -> 200 mas.
    # Pendiente a 2025: 1.000 - 100 - 200 = 700.
    out = build_loss_compensation(
        [_prior(2023, -1000.0, 400.0), _prior(2024, 0.0, 800.0)],
        Decimal("0"), Decimal("0"), 2025,
    )
    [loss] = out["prior_losses"]
    assert loss["pending_start_base"] == 700.0
    assert out["remaining_to_carry_base"] == 700.0


def test_oldest_loss_consumed_first_in_intermediate_year():
    # 2022: -300, 2023: -500, 2024: +400 -> se aplica primero 2022 (300) y
    # luego 100 de 2023. Pendiente: 2023 = 400.
    out = build_loss_compensation(
        [_prior(2022, -300.0), _prior(2023, -500.0), _prior(2024, 400.0)],
        Decimal("0"), Decimal("0"), 2025,
    )
    assert [(p["year"], p["pending_start_base"]) for p in out["prior_losses"]] == [(2023, 400.0)]


def test_unknown_rcm_does_not_invent_consumption():
    # Sin dividendos conocidos del ejercicio intermedio no se resta nada por
    # el 25 %: mejor no inventar una compensacion.
    out = build_loss_compensation(
        [_prior(2023, -1000.0, None), _prior(2024, 0.0, None)],
        Decimal("0"), Decimal("0"), 2025,
    )
    assert out["prior_losses"][0]["pending_start_base"] == 1000.0


def test_declared_pending_still_authoritative():
    out = build_loss_compensation(
        [_prior(2022, -1000.0), _prior(2023, 600.0)], Decimal("1000"), Decimal("0"), 2025,
        declared_pending={2022: Decimal("1000")},
    )
    assert out["estimativo"] is False
    assert out["prior_losses"][0]["pending_start_base"] == 1000.0
