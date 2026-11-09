"""Bordes de app.services.scanned_accounts (OCR de cuentas escaneadas de Companies House).

Helpers puros llamados por via directa con entradas literales sinteticas: no se ejecuta
OCR real (ni tesseract ni pypdfium2) ni se toca red, disco fuera de pytest ni estado
global del modulo. Los Statement/Row se construyen a mano con valores literales.
"""

from decimal import Decimal

from app.services.scanned_accounts import (
    BALANCE,
    INCOME,
    Row,
    Statement,
    _column_units,
    _cur,
    _fig,
    _find,
    _mark_sums,
    _tol,
    _value,
    balance_check,
    classify_heading,
    figures_from_statements,
    income_check,
    parse_period,
    parse_statement,
    parse_units,
)


def _row(label: str, *vals: object, index: int = 0, page: int = 9, line: str | None = None) -> Row:
    return Row(
        label=label,
        values=[v if isinstance(v, Decimal) or v is None else Decimal(v) for v in vals],
        line=line if line is not None else label,
        index=index,
        page=page,
    )


def _st(
    kind: str,
    rows: list[Row],
    *,
    current_col: int | None = 0,
    scale: int | None = 1_000,
    decimals: bool = False,
) -> Statement:
    return Statement(
        kind=kind,
        pages=[9],
        title="titulo",
        consolidated=True,
        currency="GBP",
        scale=scale,
        unit="£'000",
        years=[2024, 2023] if current_col is not None else [],
        current_col=current_col,
        period_end="2024-12-31",
        rows=rows,
        decimals=decimals,
    )


# --------------------------------------------------------------------------- cabeceras


def test_classify_heading_otro_estado_en_cabecera_sin_fecha_salta_titulo() -> None:
    texto = "Cash flows\nIncome statement\n£m"
    assert classify_heading(texto) is None


def test_classify_heading_titulo_con_continued_se_descarta() -> None:
    texto = "Income statement continued\nyear ended 31 December 2024"
    assert classify_heading(texto) is None


def test_parse_units_palabra_de_moneda_tras_otra_en_la_lista() -> None:
    assert parse_units("thousands of pounds sterling") == ("GBP", 1_000, "thousands of pounds sterling")


def test_parse_units_escala_sin_moneda_conocida() -> None:
    assert parse_units("Assets in millions of wodgets") == (None, 1_000_000, "millions of wodgets")


def test_parse_period_sin_fecha() -> None:
    assert parse_period("no hay fechas aqui") is None


def test_parse_period_mes_irreconocible() -> None:
    assert parse_period("period ended 12 Flobnar 2024") is None


def test_parse_period_fecha_imposible() -> None:
    assert parse_period("as at 30 February 2024") is None


def test_parse_period_ordinal() -> None:
    assert parse_period("year ended 31st December 2024") == "2024-12-31"


def test_value_token_no_numerico() -> None:
    assert _value("wodget") is None


def test_value_parentesis_y_nil() -> None:
    assert _value("(1,234)") == Decimal("-1234")
    assert _value("nil") == Decimal(0)


def test_column_units_simbolo_legible() -> None:
    assert _column_units(["£'000 £'000"], None) == ("GBP", 1_000, "£'000", None)


def test_column_units_simbolo_ilegible_sin_pista() -> None:
    assert _column_units(["im im"], None) == (
        None,
        1_000_000,
        "m",
        "simbolo de moneda ilegible («im»)",
    )


def test_column_units_simbolo_ilegible_con_pista() -> None:
    assert _column_units(["im im"], "GBP") == (
        "GBP",
        1_000_000,
        "£m",
        "simbolo de moneda leido como «im»; moneda deducida del documento (GBP)",
    )


def test_column_units_linea_con_menos_de_dos_hits_se_salta() -> None:
    assert _column_units(["solo £'000 aqui", "£m £m"], None) == ("GBP", 1_000_000, "£m", None)


# ----------------------------------------------------------------------- parse_statement


def test_parse_statement_moneda_desde_pista_cuando_el_banner_no_la_da() -> None:
    texto = "thousands of wodgets\n2024 2023\nTurnover 1,000 900\nProfit 100 90"
    st = parse_statement(BALANCE, [(7, texto)], currency_hint="GEL")
    assert st.currency == "GEL"
    assert st.scale == 1_000
    assert st.unit == "thousands of wodgets"
    assert st.unit_note == "moneda deducida del documento (GEL)"
    assert st.years == [2024, 2023]
    assert st.current_col == 0
    assert st.period_end == "2024"
    assert [r.label for r in st.rows] == ["Turnover", "Profit"]


def test_parse_statement_anos_fuera_de_cabecera_y_periodo_en_conflicto() -> None:
    relleno = ["Directors and advisers"] * 13
    lineas = ["year ended 31 December 2022", *relleno, "2024 2023", "Turnover 1,000 900"]
    st = parse_statement(BALANCE, [(3, "\n".join(lineas))])
    assert st.years == [2024, 2023]
    assert st.current_col == 0
    # La fecha del periodo (2022) contradice la columna mas reciente (2024): se descarta
    # y queda el ano de la columna.
    assert st.period_end == "2024"
    assert st.pages == [3]


# ------------------------------------------------------------------------------ internos


def test_tol_sin_referencia() -> None:
    assert _tol(_st(BALANCE, [])) == Decimal(3)
    assert _tol(_st(BALANCE, [], decimals=True)) == Decimal("0.3")


def test_tol_con_referencia_grande() -> None:
    assert _tol(_st(BALANCE, []), Decimal("100000")) == Decimal("5.00000")


def test_cur_sin_columna_actual() -> None:
    st = _st(BALANCE, [], current_col=None)
    assert _cur(st, _row("Total assets", 100)) is None


def test_find_statement_none_y_ultimo() -> None:
    assert _find(None, lambda s: True) is None
    st = _st(BALANCE, [_row("Total assets", 100, index=0), _row("Total assets", 90, index=1)])
    encontrado = _find(st, lambda s: s == "total assets", last=True)
    assert encontrado is not None
    assert encontrado.index == 1


def test_mark_sums_marca_las_partidas_que_suman() -> None:
    a = _row("Debtors", 40, index=0)
    b = _row("Cash", 60, index=1)
    total = _row("Total assets", 100, index=2)
    st = _st(BALANCE, [a, b, total])
    _mark_sums(st)
    assert a.checked_in == "Total assets"
    assert b.checked_in == "Total assets"
    assert total.checked_in is None


def test_fig_comparativo_millones_y_perdida_sin_parentesis() -> None:
    st = _st(INCOME, [], scale=1_000_000, decimals=True)
    fila = _row("Loss for the year", Decimal("-4.7"), Decimal("11.0"), line="Loss for the year 4.7 11.0")
    fig = _fig(st, fila, "profit_for_year")
    assert fig["value"] == -4.7
    assert fig["comparative"] == 11.0
    assert fig["value_millions"] == -4.7
    assert fig["basis"] == "la etiqueta dice pérdida: se toma en negativo"
    assert fig["check"] is None
    assert fig["column"] == "2024"
    assert fig["statement"] == "income"


def test_fig_sin_comparativo_ni_escala() -> None:
    st = _st(BALANCE, [], scale=None)
    fila = _row("Cash at bank", Decimal("10"))
    fig = _fig(st, fila, "cash")
    assert fig["value"] == 10.0
    assert fig["comparative"] is None
    assert fig["value_millions"] is None
    assert fig["basis"] is None
    assert fig["scale"] is None


# --------------------------------------------------------------------- cuadres contables


def test_balance_check_sin_columnas_identificadas() -> None:
    st = _st(BALANCE, [_row("Total assets", 100)], current_col=None)
    assert balance_check(st) == (False, "no se identifican las columnas del ejercicio y el comparativo")


def test_balance_check_activo_contra_pasivo_y_patrimonio() -> None:
    st = _st(
        BALANCE,
        [
            _row("Total assets", 100, index=0),
            _row("Total equity", 60, index=1),
            _row("Total liabilities and equity", 100, index=2),
        ],
    )
    assert balance_check(st) == (True, "activo 100 = pasivo y patrimonio 100")


def test_balance_check_activo_y_pasivo_patrimonio_sin_fondos_propios() -> None:
    st = _st(
        BALANCE,
        [
            _row("Total assets", 100, index=0),
            _row("Total liabilities and equity", 100, index=1),
        ],
    )
    assert balance_check(st) == (
        False,
        "no cuadra o falta el patrimonio: activo 100, pasivo y patrimonio 100",
    )


def test_balance_check_sin_totales_legibles() -> None:
    st = _st(BALANCE, [_row("Wodgets", 1)])
    assert balance_check(st) == (False, "no se leen los totales del balance (activo, pasivo, patrimonio)")


def test_income_check_sin_beneficio_legible() -> None:
    st = _st(INCOME, [_row("Turnover", 100)])
    assert income_check(st) == (False, "no se leen el beneficio antes de impuestos y el del ejercicio")


def test_income_check_impuesto_en_positivo() -> None:
    st = _st(
        INCOME,
        [
            _row("Profit before taxation", 100, index=0),
            _row("Taxation", 20, index=1),
            _row("Profit for the financial year", 80, index=2),
        ],
    )
    assert income_check(st) == (True, "antes de impuestos 100 − impuesto 20 = beneficio del ejercicio 80")


# ------------------------------------------------------------- figures_from_statements


def test_figures_atribuible_tras_beneficio_del_ejercicio() -> None:
    income = _st(
        INCOME,
        [
            _row("Profit before taxation", 100, index=0),
            _row("Taxation", 20, index=1),
            _row("Profit for the year", 80, index=2),
            _row("Attributable to owners of the parent", 75, index=3),
        ],
    )
    resultado = figures_from_statements(income, None)
    assert resultado["checks"]["income"]["ok"] is True
    metricas = [f["metric"] for f in resultado["figures"]]
    assert metricas == ["profit_before_tax", "profit_for_year", "profit_attributable"]
    atribuible = resultado["figures"][2]
    assert atribuible["label"] == "Attributable to owners of the parent"
    assert atribuible["value"] == 75.0
    assert atribuible["basis"] is None
    assert resultado["rejected"] == []


def test_figures_sin_atribuible_cuando_hay_minoritarios() -> None:
    income = _st(
        INCOME,
        [
            _row("Profit before taxation", 100, index=0),
            _row("Taxation", 20, index=1),
            _row("Profit for the year", 80, index=2),
            _row("Non-controlling interests", 5, index=3),
        ],
    )
    resultado = figures_from_statements(income, None)
    assert [f["metric"] for f in resultado["figures"]] == ["profit_before_tax", "profit_for_year"]


def test_figures_balance_completo_con_efectivo_y_deuda() -> None:
    balance = _st(
        BALANCE,
        [
            _row("Total assets", 100, index=0),
            _row("Total liabilities", -40, index=1),
            _row("Total equity", 60, index=2),
            _row("Cash at bank and in hand", 10, index=3),
            _row("Borrowings", 30, index=4),
        ],
    )
    resultado = figures_from_statements(None, balance)
    assert resultado["checks"]["balance"]["ok"] is True
    assert [f["metric"] for f in resultado["figures"]] == [
        "total_equity",
        "equity_attributable",
        "net_assets",
        "cash",
        "borrowings",
    ]
    patrimonio, atribuible, netos, caja, deuda = resultado["figures"]
    assert patrimonio["value"] == 60.0
    assert patrimonio["check"] == "cuadre del balance"
    assert atribuible["basis"] == "sin minoritarios en el balance: atribuible = patrimonio total"
    assert netos["value"] == 60.0
    assert netos["basis"] == "activo total − pasivo total"
    assert netos["label"] == "Total assets − Total liabilities"
    assert netos["line"] == "Total assets | Total liabilities"
    assert caja["value"] == 10.0
    assert deuda["value"] == 30.0
    assert deuda["basis"] is None
    assert resultado["rejected"] == []


def test_figures_balance_solo_atribuible_sin_totales() -> None:
    balance = _st(
        BALANCE,
        [_row("Total equity attributable to owners of the parent", 60, index=0)],
    )
    resultado = figures_from_statements(None, balance)
    assert resultado["checks"]["balance"]["ok"] is False
    assert resultado["figures"] == []
    assert len(resultado["rejected"]) == 1
    rechazada = resultado["rejected"][0]
    assert rechazada["metric"] == "equity_attributable"
    assert rechazada["value"] == 60.0
    assert rechazada["reason"] == "no se leen los totales del balance (activo, pasivo, patrimonio)"
