"""Estimaciones de prensa con su divisa (hallazgo del auditor, «Fórmulas: estimaciones de prensa»).

Antes: todo importe en «$» se guardaba como USD, también los «C$» de una empresa canadiense; y un
objetivo «to C$54» ni se leía. Ahora la divisa sale de la marca del texto (US$, C$, A$…); un «$» a
secas es USD solo si la empresa no usa otro dólar; si lo usa (CAD, AUD…), la cifra se aparta con el
motivo «divisa ambigua» en vez de guardarse con una divisa inventada."""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from app.services import analyst_press_estimates as ape

CNQ = SimpleNamespace(ticker="CNQ", name="Canadian Natural Resources Limited")


def test_marca_de_divisa_junto_al_dolar() -> None:
    s = "RBC sees revenue of C$41.2 billion in 2027 and a price target to US$54."
    assert ape.marked_currency(s, s.index("C$") - 1) == "CAD"
    assert ape.marked_currency(s, s.index("US$")) == "USD"
    assert ape.marked_currency("a $54 price target", 0) is None


def test_dolar_a_secas_segun_la_divisa_de_la_empresa() -> None:
    assert ape.resolve_currency(None, "USD") == "USD"
    assert ape.resolve_currency(None, "EUR") == "USD"  # un «$» sobre Airbus no son euros
    assert ape.resolve_currency(None, "CAD") is None  # ambiguo: no se inventa
    assert ape.resolve_currency("CAD", "USD") == "CAD"


def test_lectura_guarda_la_marca_y_lee_objetivos_con_marca() -> None:
    text = ("Scotiabank expects Canadian Natural revenue of C$41.2 billion in 2027. "
            "Scotiabank raised its Canadian Natural price target to C$54.")
    reading = ape.read_article(ape.Article("https://x.example/c", "t", date(2026, 11, 6), text), company=CNQ)
    assert [(e.year, e.marked_currency) for e in reading.estimates] == [(2027, "CAD")]
    assert [(e.amount, e.marked_currency) for e in reading.targets] == [(54, "CAD")]


def test_objetivos_de_precio_no_mezclan_divisas_en_la_tesis() -> None:
    from app.services.expert_team.thesis_v2 import price_target_stats

    ccy, vals, apart = price_target_stats([{"target": 50, "currency": "CAD"}, {"target": 54, "currency": "CAD"},
                                           {"target": 40, "currency": "USD"}, {"target": 60, "currency": ""}])
    assert (ccy, vals) == ("CAD", [50.0, 54.0])
    assert apart == "1 en otra divisa, 1 sin divisa en la fuente"
