"""Una operacion solo acepta un codigo de divisa que el resto de la app entienda.

La divisa admitia cualquier texto de 3 a 10 caracteres: «1e30», «EURO», « 5 »
o «ñ€😀» se guardaban (en mayusculas) y esa posicion o ese dividendo no
encontraba nunca tipo de cambio: la cartera quedaba «incompleta» para siempre.
Los codigos validos son los ISO de 3 letras y las subunidades que ya conoce la
valoracion (GBX, GBp, GBPENCE, ZAc, ILa...), con la misma regla de 3 letras que
la divisa base y los tipos de cambio.
"""

import pytest
from fastapi.testclient import TestClient

from app.core.csrf import generate_csrf_token
from app.core.database import init_db
from main import app

CSRF = {"X-CSRF-Token": generate_csrf_token()}
_N = iter(range(10_000))


def _post(client, currency, action="buy"):
    return client.post("/api/portfolio/transactions", json={
        "ticker": f"CURC{next(_N)}",  # un ticker por caso: no mezclar divisas
        "action": action, "quantity": "1" if action == "dividend" else "2", "price": "10",
        "currency": currency, "trade_date": "2024-01-02",
    }, headers=CSRF)


@pytest.mark.parametrize("currency", ["1e30", "1_000", " 5 ", "ñ€😀", "EURO", "US$", "E U"])
@pytest.mark.parametrize("action", ["buy", "dividend"])
def test_divisa_que_no_es_un_codigo_es_422(currency, action):
    init_db()
    response = _post(TestClient(app), currency, action)
    assert response.status_code == 422, (currency, response.text)


@pytest.mark.parametrize(("currency", "stored"), [
    ("eur", "EUR"), (" usd ", "USD"), ("GBp", "GBp"), ("GBX", "GBX"), ("GBPENCE", "GBPENCE"), ("ZAc", "ZAc"),
])
def test_codigos_validos_siguen_entrando(currency, stored):
    init_db()
    response = _post(TestClient(app), currency)
    assert response.status_code == 201, response.text
    assert response.json()["currency"] == stored
