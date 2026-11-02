"""PDF de cartera: cifras en formato español y «1 posición activa».

El informe es en castellano («Composición de la Cartera», «Títulos») pero las
cifras salían en formato inglés (4,500.00; 100.0%) y con una sola
posición decía «Consta de 1 posiciones activas».
"""

from tests.test_thesis_pdf_export import _page_text, env  # noqa: F401 - fixture


def test_portfolio_pdf_spanish_numbers_and_singular(env):  # noqa: F811
    client, _factory, port_id = env
    res = client.get(f"/api/portfolio/{port_id}/pdf")
    assert res.status_code == 200
    page1, _page2 = _page_text(res.content)
    flat = " ".join(page1.split())
    assert "1 posición activa" in flat and "1 posiciones" not in flat
    assert "4.500,00 " in flat and "4,500.00" not in flat
    assert "1.000,00" in flat and "1,000.00" not in flat
    assert "100,0 %" in flat and "100.0%" not in flat
