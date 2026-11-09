"""Harness de la fixture ``_reset_filing_deadline_failure_cache`` (conftest).

Con un sentinel NO vacio en el ``_FAILED_UNTIL`` original, la fixture debe
ofrecer al test un dict limpio y restaurar al terminar el contenido
original exactamente como estaba (snapshot + restauracion, nunca un
clear() pelado que destruya el estado previo de la sesion).
"""

import pytest

from app.services import catalyst_calendar_service as svc
from tests import conftest


def test_fixture_hace_snapshot_y_restaura_con_sentinel():
    original = svc._FAILED_UNTIL
    original["sentinela"] = 123.0
    snapshot = dict(original)
    try:
        gen = conftest._reset_filing_deadline_failure_cache.__wrapped__()
        next(gen)  # setup: snapshot interno + clear
        assert svc._FAILED_UNTIL == {}
        svc._FAILED_UNTIL["sucio"] = 1.0  # un test puede dejar basura
        with pytest.raises(StopIteration):
            next(gen)  # teardown: clear + restauracion
        assert snapshot == svc._FAILED_UNTIL
        assert svc._FAILED_UNTIL is original  # mismo objeto, nunca reasignado
    finally:
        svc._FAILED_UNTIL.clear()
