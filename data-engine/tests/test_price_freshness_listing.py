"""A8 con etiquetas reales: Flex de IBKR (BM, IBIS, SBF, AEB) y «TSE» por sufijo.

Valores derivados a mano (horario de invierno desde el 25-oct-2026):
- BME cierra a las 17:30 de Madrid (CET = UTC+1) -> 16:30 UTC.
- Xetra 17:30 Berlín y Euronext 17:30 París -> 16:30 UTC.
- TSX cierra a las 16:00 de Toronto (EDT = UTC-4 hasta el 1-nov-2026) -> 20:00 UTC.
"""

from datetime import UTC, date, datetime

import pytest

from app.services.price_freshness import close_is_stale, session_close_at

THU = date(2026, 10, 29)
# Viernes 30-oct a las 09:00 Madrid (08:00 UTC), antes de la apertura europea.
FRI_MORNING = datetime(2026, 10, 30, 8, 0, tzinfo=UTC)


@pytest.mark.parametrize("label", ["BM", "IBIS", "IBIS2", "SBF", "AEB", "ENEXT.BE", "LSEETF"])
def test_ibkr_flex_venue_codes_have_a_session_close(label):
    assert session_close_at(THU, label) is not None
    # El cierre del jueves sigue vigente el viernes antes de abrir.
    assert close_is_stale(THU, label, 1, now=FRI_MORNING) is False


def test_bm_close_instant_derived_by_hand():
    assert session_close_at(THU, "BM") == datetime(2026, 10, 29, 16, 30, tzinfo=UTC)


def test_tse_with_toronto_suffix_uses_tsx_close():
    # «TSE» es Toronto en la Flex de IBKR: RY.TO cierra a las 20:00 UTC.
    assert session_close_at(THU, "TSE", "RY.TO") == datetime(2026, 10, 29, 20, 0, tzinfo=UTC)
    assert close_is_stale(THU, "TSE", 1, now=FRI_MORNING, ticker="RY.TO") is False
    assert (
        close_is_stale(THU, "TSE", 1, now=datetime(2026, 10, 30, 20, 0, tzinfo=UTC), ticker="RY.TO") is True
    )


def test_tse_with_tokyo_suffix_or_no_suffix_stays_unknown():
    # Tokio (.T) no tiene calendario en el código: regla de días naturales.
    assert session_close_at(THU, "TSE", "7203.T") is None
    assert session_close_at(THU, "TSE", "RY") is None
    assert close_is_stale(THU, "TSE", 1, now=FRI_MORNING, ticker="7203.T") is True


def test_suffix_covers_unknown_label():
    assert session_close_at(THU, "UNKNOWN", "ITX.MC") == datetime(2026, 10, 29, 16, 30, tzinfo=UTC)
    # Clase de acción US (BRK.B) no es un sufijo de bolsa: manda la etiqueta.
    assert session_close_at(THU, "NYSE", "BRK.B") == datetime(2026, 10, 29, 20, 0, tzinfo=UTC)
