"""Helpers puros de financial_ingestion_service (fechas, periodos, recoleccion).

Primer lote de huecos del servicio (modulo n.1 del top-10 services/core).
Sin BD ni red: funciones puras de etiquetado temporal y de filtrado de
hechos SEC/ESEF.

- _norm_date: epoch en segundos y en milisegundos -> ISO; ISO tal cual;
  None, vacio y no parseable -> None (el caller conserva el valor verbatim).
- _published_by / _publication_date: fail closed sin `filed` o con `filed`
  ilegible; corte por fecha de publicacion.
- _period: etiqueta de periodo con fecha y trimestre; fiscal_year no entero
  no rompe; la fecha epoch se normaliza y la imposible se conserva verbatim.
- _fiscal_quarter_from_end: trimestre desde el cierre contra el mes modal;
  sin ancla modal o fecha ilegible -> None; el mes de cierre modal es Q4.
- _current_fiscal_month_from_anchors: moda de los ~5 filings mas recientes;
  sin anclas o con fechas ilegibles -> None; cierre en la primera semana del
  mes pertenece al mes anterior (52/53 semanas).
- _esef_annual_ends: solo hechos de duracion anual legibles; units/entries
  con forma inesperada se ignoran; miembros (dims) no son el consolidado.
- _opening_instant_as_closing: la apertura puesta el dia siguiente al cierre
  se reetiqueta al cierre solo cuando ese dia es fin de duracion anual del
  propio filing; periodo ilegible -> None.
- _fiscal_annual_pairs: solo hechos de flujo anuales (300-380 dias, fp=FY,
  10-K/20-F); el resto no entra.
- _quarters_from_ytd: el trimestre derivado (H1 - Q1) hereda el accn/filed
  del acumulado mas reciente y se marca _derived_from_ytd; un trimestre ya
  presentado no se pisa.
- _collect_by_concept: span fuera de rango omitido, InterestIncomeExpense
  NonoperatingNet solo como gasto (negativo -> positivo), as_of fail closed,
  ancla anual exigida y con el mismo mes de cierre.

NO prueba (declarado): los caminos async de refresh (FMP/SEC/ESEF) ni la
persistencia en BD; van en lotes siguientes con SQLite y clientes doblados.
"""

from datetime import date

from app.services import financial_ingestion_service as m

# --- _norm_date ---------------------------------------------------------


def test_norm_date_epoch_segundos():
    assert m._norm_date("1767225600") == "2026-01-01"


def test_norm_date_epoch_milisegundos():
    assert m._norm_date("1767225600000") == "2026-01-01"


def test_norm_date_iso_tal_cual():
    assert m._norm_date("2026-03-15") == "2026-03-15"


def test_norm_date_no_parseable_devuelve_none():
    assert m._norm_date("2025-99-99") is None
    assert m._norm_date("no-es-fecha") is None


def test_norm_date_none_y_vacio():
    assert m._norm_date(None) is None
    assert m._norm_date("   ") is None


# --- _published_by / _publication_date -----------------------------------


def test_published_by_sin_filed_fail_closed():
    assert m._published_by({}, date(2026, 1, 1)) is False
    assert m._published_by({"filed": "   "}, date(2026, 1, 1)) is False


def test_published_by_filed_ilegible_fail_closed():
    assert m._published_by({"filed": "no-es-fecha"}, date(2026, 1, 1)) is False


def test_published_by_corte_exacto():
    entrada = {"filed": "2026-03-02"}
    assert m._published_by(entrada, date(2026, 3, 2)) is True
    assert m._published_by(entrada, date(2026, 3, 1)) is False


def test_publication_date():
    assert m._publication_date({"filed": "2026-03-02"}) == date(2026, 3, 2)
    assert m._publication_date({"filed": "no-es-fecha"}) is None
    assert m._publication_date({}) is None


# --- _period --------------------------------------------------------------


def test_period_fecha_y_trimestre():
    fila = {"date": "2026-03-31", "period": "Q1", "calendarYear": "2026"}
    assert m._period(fila) == ("2026-03-31:Q1", 2026, "Q1")


def test_period_ano_y_trimestre_sin_fecha():
    fila = {"period": "Q2", "calendarYear": "2026"}
    assert m._period(fila) == ("2026:Q2", 2026, "Q2")


def test_period_fiscal_year_no_entero_no_rompe():
    fila = {"date": "2026-03-31", "period": "Q1", "calendarYear": "FY26"}
    etiqueta, year_int, quarter = m._period(fila)
    assert etiqueta == "2026-03-31:Q1"
    assert year_int is None
    assert quarter == "Q1"


def test_period_solo_fecha():
    assert m._period({"date": "2026-03-31"}) == ("2026-03-31", None, None)


def test_period_desconocido_y_fecha_epoch_normalizada():
    assert m._period({})[0] == "unknown"
    fila = {"date": "1767225600", "period": "FY", "calendarYear": "2025"}
    assert m._period(fila)[0] == "2026-01-01:FY"


def test_period_fecha_imposible_se_conserva_verbatim():
    fila = {"date": "2025-99-99", "period": "FY"}
    assert m._period(fila)[0] == "2025-99-99:FY"


# --- _fiscal_quarter_from_end ---------------------------------------------


def test_fiscal_quarter_sin_modal_devuelve_none():
    assert m._fiscal_quarter_from_end("2026-03-31", None) is None


def test_fiscal_quarter_fecha_ilegible_devuelve_none():
    assert m._fiscal_quarter_from_end("no-es-fecha", "12") is None
    assert m._fiscal_quarter_from_end("2026-03-31", "abc") is None


def test_fiscal_quarter_mes_de_cierre_modal_es_q4():
    assert m._fiscal_quarter_from_end("2026-12-31", "12") == "Q4"


def test_fiscal_quarter_tres_meses_tras_el_modal_es_q1():
    assert m._fiscal_quarter_from_end("2026-03-31", "12") == "Q1"
    assert m._fiscal_quarter_from_end("2026-06-30", "12") == "Q2"


# --- _current_fiscal_month_from_anchors ------------------------------------


def test_mes_modal_sin_anclas_devuelve_none():
    assert m._current_fiscal_month_from_anchors({}) is None


def test_mes_modal_fechas_ilegibles_devuelve_none():
    assert m._current_fiscal_month_from_anchors({"accn1": "no-es-fecha"}) is None


def test_mes_modal_primera_semana_es_mes_anterior():
    # VFC cierra el sabado mas cercano al 31 de marzo: 2026-04-04 es "marzo".
    anchors = {"a1": "2026-04-04", "a2": "2025-03-29", "a3": "2024-03-30"}
    assert m._current_fiscal_month_from_anchors(anchors) == "03"


def test_mes_modal_ventana_cinco_recientes_gana_a_la_historia():
    # La moda se computa sobre los ~5 filings mas recientes, no sobre toda
    # la historia: con 8 anclas donde los 5 recientes son 3x"03" + 2x"12"
    # y los 3 antiguos son "12", la historia completa daria "12" (5 vs 3)
    # y la ventana da "03". Caso real: emisores que cambian de calendario
    # fiscal (BRT Sep->Dec, VFC Dic->Mar) quedaban congelados en el ano viejo.
    anchors = {
        "a1": "2026-03-31", "a2": "2025-03-29", "a3": "2024-03-30",
        "a4": "2023-12-31", "a5": "2022-12-31",
        "a6": "2021-12-31", "a7": "2020-12-31", "a8": "2019-12-31",
    }
    assert m._current_fiscal_month_from_anchors(anchors) == "03"


# --- _esef_annual_ends ------------------------------------------------------


def test_esef_annual_ends_ignora_formas_inesperadas():
    facts = {"concepto1": "no-es-dict", "concepto2": {"EUR": "no-es-lista"}}
    assert m._esef_annual_ends(facts) == frozenset()


def test_esef_annual_ends_solo_duraciones_anuales():
    facts = {
        "ifrs-full:Revenue": {
            "EUR": [
                {"start": "2025-01-01", "end": "2025-12-31", "val": 10},
                {"start": "2025-01-01", "end": "2025-03-31", "val": 2},
                {"start": "2025-01-01", "end": "2024-12-31", "val": 9, "dims": {"m": "x"}},
            ]
        }
    }
    assert m._esef_annual_ends(facts) == frozenset({"2025-12-31"})


# --- _opening_instant_as_closing -------------------------------------------


def test_apertura_sin_instant_o_con_end_devuelve_none():
    assert m._opening_instant_as_closing({"end": "2025-12-31"}, "2025-12-31", frozenset()) is None
    assert m._opening_instant_as_closing(
        {"instant": "2025-01-01"}, "2025-01-01", frozenset({"2025-01-01"})
    ) is None


def test_apertura_periodo_ilegible_devuelve_none():
    assert m._opening_instant_as_closing({"instant": "x"}, "no-es-fecha", frozenset()) is None


def test_apertura_dia_siguiente_al_cierre_anual_se_reetiqueta():
    entrada = {"instant": "2023-01-02T00:00:00"}
    assert (
        m._opening_instant_as_closing(entrada, "2023-01-01", frozenset({"2022-12-31"}))
        == "2022-12-31"
    )
    # Sin evidencia de que el dia anterior cierre una duracion anual: None.
    assert m._opening_instant_as_closing(entrada, "2023-01-01", frozenset()) is None


# --- _fiscal_annual_pairs ----------------------------------------------------


def test_fiscal_annual_pairs_solo_flujo_anual_de_10k():
    us_gaap = {
        "Revenues": {
            "units": {
                "USD": [
                    {"start": "2025-01-01", "end": "2025-12-31", "fp": "FY", "form": "10-K", "val": 10},
                    {"start": "2025-01-01", "end": "2025-03-31", "fp": "Q1", "form": "10-Q", "val": 2},
                    {"start": "2025-01-01", "end": "2025-12-31", "fp": "FY", "form": "8-K", "val": 10},
                    {"start": "2025-01-01", "end": "2025-04-30", "fp": "FY", "form": "10-K", "val": 3},
                    {"end": "2025-12-31", "fp": "FY", "form": "10-K", "val": 10},
                ]
            }
        }
    }
    pares = m._fiscal_annual_pairs(us_gaap)
    assert pares == [("12", "2025-12-31")]


# --- _quarters_from_ytd ------------------------------------------------------


def test_quarters_from_ytd_deriva_el_trimestre_que_falta():
    ytd = {
        "2025-03-31": {"start": "2025-01-01", "end": "2025-03-31", "val": 100, "accn": "a1", "filed": "2025-04-20"},
        "2025-06-30": {"start": "2025-01-01", "end": "2025-06-30", "val": 250, "accn": "a2", "filed": "2025-07-25"},
    }
    derivados = m._quarters_from_ytd({}, ytd)
    assert set(derivados) == {"2025-06-30"}
    q2 = derivados["2025-06-30"]
    assert q2["val"] == 150
    assert q2["_derived_from_ytd"] is True
    # Hereda accn Y filed del acumulado mas reciente (el filing conocible).
    assert q2["accn"] == "a2"
    assert q2["filed"] == "2025-07-25"


def test_quarters_from_ytd_no_pisa_trimestre_presentado():
    presentado = {
        "2025-06-30": {"start": "2025-04-01", "end": "2025-06-30", "val": 150, "accn": "a3", "filed": "2025-07-25"},
    }
    ytd = {
        "2025-03-31": {"start": "2025-01-01", "end": "2025-03-31", "val": 100, "accn": "a1", "filed": "2025-04-20"},
        "2025-06-30": {"start": "2025-01-01", "end": "2025-06-30", "val": 250, "accn": "a2", "filed": "2025-07-25"},
    }
    assert m._quarters_from_ytd(presentado, ytd) == {}


# --- _collect_by_concept ----------------------------------------------------


def _entrada(**campos):
    base = {
        "start": "2025-01-01", "end": "2025-12-31", "val": 10,
        "fp": "FY", "form": "10-K", "filed": "2026-03-02", "accn": "a1",
    }
    base.update(campos)
    return base


def test_collect_span_fuera_de_rango_se_omite():
    us_gaap = {"Revenues": {"units": {"USD": [_entrada(end="2025-04-30")]}}}
    recolectado = m._collect_by_concept(
        us_gaap, ["Revenues"], "USD",
        forms={"10-K"}, periods={"FY"}, min_span=300, max_span=380,
    )
    assert recolectado == {}


def test_collect_interes_neto_solo_como_gasto_en_positivo():
    concepto = "InterestIncomeExpenseNonoperatingNet"
    us_gaap = {concepto: {"units": {"USD": [
        _entrada(val=-250),
        _entrada(val=300, end="2024-12-31", start="2024-01-01"),
    ]}}}
    recolectado = m._collect_by_concept(
        us_gaap, [concepto], "USD",
        forms={"10-K"}, periods={"FY"}, min_span=None, max_span=None,
    )
    # El gasto (negativo) entra guardado en positivo; el ingreso (positivo)
    # no es gasto y se omite.
    assert recolectado[concepto]["2025-12-31"]["val"] == 250
    assert "2024-12-31" not in recolectado[concepto]


def test_collect_as_of_fail_closed():
    us_gaap = {"Revenues": {"units": {"USD": [_entrada(filed="2026-03-02")]}}}
    recolectado = m._collect_by_concept(
        us_gaap, ["Revenues"], "USD",
        forms={"10-K"}, periods={"FY"}, min_span=None, max_span=None,
        as_of=date(2026, 3, 1),
    )
    assert recolectado == {}


def test_collect_ancla_anual_exigida_y_mismo_mes():
    entrada = _entrada(accn="a1")
    us_gaap = {"Revenues": {"units": {"USD": [entrada]}}}
    # Sin ancla para ese accn: no entra (fail closed).
    assert m._collect_by_concept(
        us_gaap, ["Revenues"], "USD",
        forms={"10-K"}, periods={"FY"}, min_span=None, max_span=None,
        annual_anchors={},
    ) == {}
    # Ancla de OTRO mes de cierre: la fila TTM dentro de un 10-K no entra.
    assert m._collect_by_concept(
        us_gaap, ["Revenues"], "USD",
        forms={"10-K"}, periods={"FY"}, min_span=None, max_span=None,
        annual_anchors={"a1": "2025-06-30"},
    ) == {}
    # Ancla coherente (mismo mes): entra.
    recolectado = m._collect_by_concept(
        us_gaap, ["Revenues"], "USD",
        forms={"10-K"}, periods={"FY"}, min_span=None, max_span=None,
        annual_anchors={"a1": "2025-12-31"},
    )
    assert "2025-12-31" in recolectado["Revenues"]
