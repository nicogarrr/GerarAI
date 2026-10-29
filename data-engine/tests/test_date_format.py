"""format_date_es / format_percent_es: las fechas y porcentajes que nacen en
el backend para UI van en es-ES («30 sept 2026», «-0,60 %»), nunca ISO ni
punto decimal (auditoría F1/F5)."""

from __future__ import annotations

from datetime import UTC, date, datetime

from app.services.date_format import format_date_es
from app.services.number_format import format_percent_es


def test_fecha_corta_es():
    assert format_date_es(date(2026, 9, 30)) == "30 sept 2026"
    assert format_date_es("2026-09-30") == "30 sept 2026"
    assert format_date_es(datetime(2026, 10, 25, 12, 0, tzinfo=UTC)) == "25 oct 2026"


def test_datetime_iso_se_trunca_al_dia():
    assert format_date_es("2026-10-25T12:00:00+00:00") == "25 oct 2026"


def test_meses_es_en_borde_de_anyo():
    assert format_date_es("2026-01-01") == "1 ene 2026"
    assert format_date_es("2026-12-31") == "31 dic 2026"


def test_entrada_no_fecha_es_none_nunca_crudo():
    assert format_date_es(None) is None
    assert format_date_es("") is None
    assert format_date_es("no-es-fecha") is None


def test_porcentaje_es_conserva_precision():
    assert format_percent_es(-0.006019474711208242) == "-0,60 %"
    assert format_percent_es(0.25) == "25,00 %"
    assert format_percent_es(0.6) == "60,00 %"


def test_porcentaje_negativo_que_redondea_a_cero_es_cero():
    assert format_percent_es(-0.00001) == "0,00 %"


def test_porcentaje_no_numerico_es_none():
    assert format_percent_es(None) is None
    assert format_percent_es("abc") is None
