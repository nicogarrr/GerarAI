"""Veracidad de PRESENTACION del fact pack (sin cambiar cifras ni motor).

- El precio se referencia como ultimo cierre registrado con su fecha cuando
  el paquete la trae; sin fecha no se afirma actualidad.
- Cada fundamental declara si es dato reportado o cifra derivada de partidas
  reportadas (is_reported), sin inventar fuente concreta.
Fixtures sinteticas autocontenidas.
"""
from types import SimpleNamespace

from app.services.thesis_deep_narrative import fact_pack

COMPANY = SimpleNamespace(currency="USD", ticker="META", name="Meta Platforms")


def _fact(metric, is_reported, value="1000000.0", unit="USD"):
    return SimpleNamespace(
        metric=metric, value=value, unit=unit, period="2025-12-31:FY",
        source_type="SEC", source_id=None, is_reported=is_reported,
        fiscal_year=2025, fiscal_quarter="FY",
    )


def _pack(*, market_as_of="2026-10-23", facts=None):
    valuation = {
        "status": "ok", "current_price": 642.62, "base_value": 564.75,
        "margin_of_safety": 0.021,
        "reverse_dcf": {"required_revenue_growth": 0.255,
                        "solved_value_per_share": 642.62},
    }
    ltm = {
        "trace": {"market_as_of": market_as_of, "market_price_source": "market_price"},
        "assumptions": {"fcf_margin": {"value": 0.327, "unit": "ratio",
                                       "source_type": "computed", "basis": "mediana"}},
    }
    return fact_pack(
        company=COMPANY, valuation=valuation, long_term_model=ltm,
        hypothesis=None, news_items=[],
        financial_facts=facts if facts is not None else [
            _fact("revenue", True), _fact("fcf_margin", False, "0.229", "ratio"),
        ],
    )


def _texto(pack, prefix):
    return next(f["texto"] for f in pack if f["texto"].startswith(prefix))


def test_precio_con_fecha_no_dice_actual():
    pack = _pack()
    precio = _texto(pack, "Último precio registrado")
    assert "23 de octubre de 2026" in precio and "642.62 USD" in precio
    assert "actual" not in precio
    for f in pack:
        assert "precio actual" not in f["texto"].lower(), f["id"]
        assert "Al precio actual" not in f["texto"], f["id"]


def test_precio_sin_fecha_no_afirma_actualidad():
    pack = _pack(market_as_of=None)
    precio = next(f["texto"] for f in pack if "642.62 USD" in f["texto"] and "precio" in f["texto"])
    assert "fecha de cierre no disponible" in precio
    assert "actual" not in precio


def test_derivados_no_se_presentan_como_reportados():
    pack = _pack(facts=[
        _fact("revenue", True),
        _fact("free_cash_flow", False),
        _fact("fcf_margin", False, "0.229", "ratio"),
        _fact("revenue_growth", False, "0.222", "ratio"),
        _fact("net_debt", False),
    ])
    reportado = _texto(pack, "Ingresos de META")
    assert "dato reportado" in reportado and "fuente SEC" in reportado
    assert "acredita publicación, no veracidad" in reportado
    assert "derivada" not in reportado
    for prefix in ("Flujo de caja libre", "Margen de FCF", "Crecimiento de ingresos", "Deuda neta"):
        texto = _texto(pack, prefix)
        assert "cifra derivada de partidas SEC" in texto, texto
        assert "no es un dato reportado" in texto
        assert "fuente SEC" not in texto
    intro = _texto(pack, "Bloque de fundamentales")
    assert "reportado o cifra derivada" in intro
    assert "NO son comparables" in intro
    assert "Bloque de fundamentales reportados" not in intro


def test_supuesto_fcf_no_llama_reportado_al_margen_registrado():
    pack = _pack()
    supuesto = _texto(pack, "Supuestos del motor")
    assert "margen FCF registrado" in supuesto
    assert "margen FCF reportado" not in supuesto


def test_cifras_no_cambian():
    """Misma cifra, misma fuente/locator: solo cambia la presentacion."""
    pack = _pack()
    precio = _texto(pack, "Último precio registrado")
    assert "642.62 USD" in precio
    derivado = _texto(pack, "Margen de FCF")
    assert "22,9 %" in derivado
    assert all(f["fuente"] for f in pack)


def test_is_reported_desconocido_no_se_convierte():
    pack = _pack(facts=[_fact("revenue", None)])
    texto = _texto(pack, "Ingresos de META")
    assert "estado de reporte no disponible" in texto
    assert "dato reportado" not in texto and "cifra derivada" not in texto


def test_fecha_malformada_equivale_a_ausente():
    for mala in ("23/10/2026", "no-date", "2026-13-99"):
        pack = _pack(market_as_of=mala)
        precio = next(f["texto"] for f in pack if "642.62 USD" in f["texto"] and "precio" in f["texto"])
        assert "fecha de cierre no disponible" in precio, mala
        assert mala not in precio and "actual" not in precio
