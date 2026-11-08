"""Handlers HTTP de app/api/routes/telegram_link.py sin cubrir: POST
/telegram-link (start) y POST /telegram-link/{id}/confirm."""

from app.api.routes import telegram_link as routes
from app.services.telegram_link import receive_bot_link
from tests.test_outbound_alerts import alert, db  # noqa: F401


def _token(start):
    return start["command"].split()[1]


def test_start_route_serializa_expires_at(db):
    result = routes.start(db=db)
    assert result["challenge_id"]
    # El handler convierte el datetime a ISO; el servicio devuelve datetime.
    assert isinstance(result["expires_at"], str)
    assert "T" in result["expires_at"]


def test_confirm_route_devuelve_verificado(db):
    link = routes.start(db=db)
    receive_bot_link(db, _token(link), "12345")
    payload = routes.LinkConfirmIn(chat_id="12345")
    result = routes.confirm(link["challenge_id"], payload, db=db)
    assert result["verified"]


def test_status_route_refleja_candidato_y_confirmacion(db):
    link = routes.start(db=db)
    receive_bot_link(db, _token(link), "12345")
    antes = routes.status(link["challenge_id"], db=db)
    assert antes == {"chat_id": "12345", "confirmed": False}
    routes.confirm(link["challenge_id"], routes.LinkConfirmIn(chat_id="12345"), db=db)
    despues = routes.status(link["challenge_id"], db=db)
    assert despues == {"chat_id": "12345", "confirmed": True}
