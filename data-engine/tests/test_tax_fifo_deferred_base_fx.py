"""Estado diferido en divisa base de un lote comprado SIN tipo de cambio.

Convención documentada en tax_report_service (_defer_base): si no se conoce
el tipo de cambio de la compra, el diferido en base del lote queda
DESCONOCIDO (None) y su futura venta se declara sin importe en base. Un
0 numérico rompe ese invariante: si el lote absorbe después una pérdida
wash-sale cuyo importe en euros sí se conoce, acumula un deferred_base con
pinta de dato cierto que no lo es (el coste base del lote es desconocido).
"""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from app.services.tax_report_service import replay_tax_fifo

D = Decimal


def _tx(i, action, qty, price, day):
    return SimpleNamespace(
        id=i, action=action, quantity=D(str(qty)), price=D(str(price)),
        fees=D("0"), currency="USD", trade_date=day, raw_payload={},
    )


def test_lote_sin_fx_no_acumula_diferido_en_base_numerico():
    # Lote B (se vende con pérdida, FX conocido en compra y venta).
    # Lote A: compra posterior SIN tipo de cambio -> coste base desconocido.
    events = [
        _tx(1, "buy", 10, 100, date(2025, 1, 5)),    # lote B
        _tx(2, "buy", 10, 100, date(2025, 1, 10)),   # lote A, sin FX
        _tx(3, "sell", 10, 90, date(2025, 2, 1)),    # vende B con pérdida
    ]
    known = {date(2025, 1, 5): D("1.00"), date(2025, 2, 1): D("0.90")}
    # La compra del lote A (10/01) no tiene tipo publicado.

    def resolve(currency, as_of):
        if currency == "EUR":
            return D(1)
        return known.get(as_of)

    lots, year_sales = replay_tax_fifo(events, resolve, date(2025, 1, 1), date(2025, 12, 31))

    # La pérdida (10 x (90-100) $; en euros 810 - 1000 = -190) queda bloqueada
    # por la recompra previa (lote A dentro de los 2 meses, sigue en cartera).
    (sale_entry,) = year_sales
    assert sale_entry["sale"] is not None
    assert sale_entry["sale"]["blocked_qty"] == D("10")

    (lot_a,) = [lot for lot in lots if lot["unit_base"] is None]
    # El diferido en divisa sí se acumula (la pérdida en dólares es conocida)...
    assert lot_a["deferred"] == D("100")
    # ...pero el diferido en EUROS de un lote cuyo coste en euros es
    # desconocido debe quedar desconocido (None), no un número.
    assert lot_a["deferred_base"] is None
