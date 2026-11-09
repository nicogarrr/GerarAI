"""Utilidades puras y dobles acotados del recolector de notas de analista.

Cubre las ramas que ``tests/test_analyst_note_collector.py`` no ejerce:
``CollectResult.as_dict``, ``_as_date`` (datetime, date, objeto con
``to_pydatetime``, cadena ISO valida/invalida), ``_positive`` (bool, None,
NaN, infinito, no positivos), ``_clean_str``, ``is_social_url`` con ``www.``,
``numbers_in``, ``_number_found`` (tolerancia) y ``_leaf_numbers`` (anidados),
``fetch_yahoo`` con ``fetch`` inyectado (exito y excepcion -> None) y
``_store`` con un servicio falso (cambia / no cambia / AnalystNoteError).

NO se prueba: ``_fetch_yahoo_sync`` (yfinance, red real), ``_default_reasoner``
(proveedor LLM real), ``extract_from_news`` ni ``collect_for_ticker`` (LLM):
quedan fuera por la exclusion de LLM. El servicio de ``_store`` es un doble
declarado: no se ejerce ``AnalystNoteService.upsert`` real ni persistencia.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime

from app.services.analyst_note_collector import (
    CollectResult,
    _as_date,
    _clean_str,
    _leaf_numbers,
    _number_found,
    _positive,
    _store,
    fetch_yahoo,
    is_social_url,
    numbers_in,
    parse_extraction,
)
from app.services.analyst_note_service import AnalystNoteError, AnalystNoteInput


def test_as_dict_devuelve_copia_exacta():
    res = CollectResult(status="stored", yahoo_status="ok", news_status="rejected", stored=2, unchanged=1, rejected=["x"], llm_calls=3)
    data = res.as_dict()
    assert data == {
        "status": "stored",
        "yahoo_status": "ok",
        "news_status": "rejected",
        "stored": 2,
        "unchanged": 1,
        "rejected": ["x"],
        "llm_calls": 3,
        "prompt_version": res.prompt_version,
    }
    data["rejected"].append("y")
    assert res.rejected == ["x"]  # la lista va copiada


def test_as_date_con_datetime_y_date():
    assert _as_date(datetime(2026, 11, 5, 10, 30)) == date(2026, 11, 5)
    assert _as_date(date(2026, 11, 5)) == date(2026, 11, 5)


def test_as_date_con_to_pydatetime():
    class PandasLike:
        def to_pydatetime(self):
            return datetime(2026, 11, 4, 9, 0)

    class Roto:
        def to_pydatetime(self):
            return "no es datetime"

    assert _as_date(PandasLike()) == date(2026, 11, 4)
    assert _as_date(Roto()) is None


def test_as_date_con_cadenas_y_basura():
    assert _as_date("2026-11-05") == date(2026, 11, 5)
    assert _as_date("  2026-11-05T12:00:00  ") == date(2026, 11, 5)
    assert _as_date("no es fecha") is None
    assert _as_date("   ") is None
    assert _as_date(None) is None
    assert _as_date(20261105) is None


def test_positive_descarta_bool_none_nan_inf_y_no_positivos():
    assert _positive(True) is None
    assert _positive(None) is None
    assert _positive(float("nan")) is None
    assert _positive(float("inf")) is None
    assert _positive(0) is None
    assert _positive(-3.5) is None
    assert _positive("abc") is None
    assert _positive(object()) is None
    assert _positive("273.5") == 273.5
    assert _positive(273) == 273.0


def test_clean_str_recorta_y_descarta_no_cadenas():
    assert _clean_str("  Buy  ") == "Buy"
    assert _clean_str("   ") is None
    assert _clean_str(None) is None
    assert _clean_str(42) is None


def test_is_social_url_con_www_y_subdominio():
    assert is_social_url("https://www.reddit.com/r/stocks/x") is True
    assert is_social_url("https://old.reddit.com/x") is True
    assert is_social_url("https://reddit.com.evil.example/x") is False
    assert is_social_url("https://finance.yahoo.com/x") is False
    assert is_social_url(None) is False
    assert is_social_url("") is False


def test_numbers_in_extrae_y_redondea():
    assert numbers_in("sube a $1,268.50 y baja a 12") == {1268.5, 12.0}
    assert numbers_in("") == set()
    assert numbers_in(None) == set()


def test_number_found_tolerancia_absoluta_y_relativa():
    found = {100.0}
    assert _number_found(100.004, found) is True
    assert _number_found(100.006, found) is False
    assert _number_found(1e9 * (1 + 5e-7), {1e9}) is True  # tolerancia relativa
    assert _number_found(50.0, set()) is False


def test_leaf_numbers_recorre_dicts_y_listas_ignorando_bool_y_texto():
    assert _leaf_numbers({"a": [1, {"b": 2.5}], "c": True, "d": "x"}) == [1.0, 2.5]
    assert _leaf_numbers(False) == []
    assert _leaf_numbers("3") == []
    assert _leaf_numbers(7) == [7.0]


def test_fetch_yahoo_con_fetch_inyectado_ok():
    def fake(symbol: str):  # sync: fetch_yahoo la ejecuta en un hilo (to_thread)
        assert symbol == "PLTR"
        return {"records": [], "closes": []}

    out = asyncio.run(fetch_yahoo("PLTR", fetch=fake))
    assert out == {"records": [], "closes": []}


def test_fetch_yahoo_devuelve_none_si_el_fetch_falla():
    import asyncio

    def roto(symbol: str):
        raise RuntimeError("Yahoo caido")

    assert asyncio.run(fetch_yahoo("PLTR", fetch=roto)) is None


class _ServicioFalso:
    """Doble declarado de AnalystNoteService para _store: no hay persistencia."""

    def __init__(self, comportamiento):
        self.comportamiento = comportamiento

    def upsert(self, db, tenant_id, item):
        accion = self.comportamiento[item.firm]
        if isinstance(accion, Exception):
            raise accion
        return object(), accion


def _nota(firm: str) -> AnalystNoteInput:
    return AnalystNoteInput(
        ticker="PLTR",
        firm=firm,
        note_date=date(2026, 11, 4),
        action="up",
        source_type="news",
    )


def test_store_cuenta_cambios_y_rechazos():
    servicio = _ServicioFalso(
        {
            "Nueva": True,
            "Vieja": False,
            "Rota": AnalystNoteError(["sin cita", "casa desconocida"]),
        }
    )
    res = CollectResult(status="stored")
    _store(None, 1, [_nota("Nueva"), _nota("Vieja"), _nota("Rota")], servicio, res)
    assert res.stored == 1
    assert res.unchanged == 1
    assert res.rejected == ["Rota 2026-11-04: sin cita; casa desconocida"]


def test_parse_extraction_rechaza_notas_que_no_son_objetos():
    notes, rejected = parse_extraction({"notes": ["cadena", 42]}, [], "PLTR")
    assert notes == []
    assert rejected == ["#1: no es un objeto", "#2: no es un objeto"]
