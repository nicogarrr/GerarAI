"""date_es: la fecha dentro de una frase en español va en es-ES, nunca ISO."""

from app.services.memo_text_es import date_es


def test_fecha_iso_a_es():
    assert date_es("2026-10-17") == "17 de octubre de 2026"


def test_datetime_iso_a_es_solo_dia():
    assert date_es("2026-09-25T10:00:00") == "25 de septiembre de 2026"
    assert date_es("2020-01-15") == "15 de enero de 2020"


def test_meses_completos():
    esperado = [
        "enero", "febrero", "marzo", "abril", "mayo", "junio",
        "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
    ]
    for mes, nombre in enumerate(esperado, start=1):
        assert date_es(f"2026-{mes:02d}-05") == f"5 de {nombre} de 2026"


def test_valor_no_fecha_se_devuelve_intacto():
    # Nunca se inventa un día: lo irreconocible queda como estaba.
    assert date_es("próximamente") == "próximamente"
    assert date_es("") == ""
    assert date_es(None) == ""
