"""Cifras citadas de cuentas escaneadas (Companies House): estados primarios por OCR.

Fixtures: texto OCR de las paginas de los estados (tesseract, 300 ppp) de cuatro depositos
reales, nunca los PDF: Brit Group Holdings 2025 (15884169, $m, consolidado), Georgia Capital
PLC 2025 (10852406, miles de lari), Brit Insurance Holdings 2025 (03121594, FRS 102, $000) y
Greene King 2025/26 (00024511, £m con el simbolo mal leido y el pasivo entre parentesis).
"""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from app.services import scanned_accounts as sa

FX = Path(__file__).parent / "fixtures" / "scanned_accounts"


def _page(name: str) -> str:
    return (FX / f"{name}.txt").read_text()


def _figures(prefix: str, income: str, balance: str, inc_page: int, bal_page: int) -> dict[str, Any]:
    inc = sa.parse_statement(sa.INCOME, [(inc_page, _page(f"{prefix}_{income}"))])
    bal = sa.parse_statement(sa.BALANCE, [(bal_page, _page(f"{prefix}_{balance}"))])
    return sa.figures_from_statements(inc, bal)


def _by_metric(result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {f["metric"]: f for f in result["figures"]}


# ------------------------------------------------------------------------ lectura de lineas
@pytest.mark.parametrize(("line", "decimals", "label", "values"), [
    ("Insurance revenue . 5,18 2,950.3 2,856.0", True, "Insurance revenue", ["2950.3", "2856.0"]),
    ("Insurance service expenses 5, 18 (2,349.4) (2,163.0)", True, "Insurance service expenses",
     ["-2349.4", "-2163.0"]),
    ("Deferred tax assets 20 0.8 -", True, "Deferred tax assets", ["0.8", "0"]),
    ("Finance costs : 13° (25.0) (13.3)", True, "Finance costs", ["-25.0", "-13.3"]),
    ("Treasury shares {1} (2)", False, "Treasury shares", ["-1", "-2"]),
    ("Gains on vestments at fair value 6  =1,774,207 242,989", False, "Gains on vestments at fair value",
     ["1774207", "242989"]),
    ("Borrowings 2I (1,724.4) (1,268.3)", True, "Borrowings", ["-1724.4", "-1268.3"]),
])
def test_parse_line_columnas_parentesis_notas(line: str, decimals: bool, label: str, values: list[str]) -> None:
    got = sa.parse_line(line, 2, decimals)
    assert got is not None
    assert got[0] == label
    assert got[1] == [Decimal(v) for v in values]


def test_parse_line_columna_ilegible_no_se_adivina() -> None:
    # «Derivative contracts 22 ee ©) 12.1»: falta la cifra del ejercicio; 22 es la nota, nunca la cifra
    got = sa.parse_line("Derivative contracts . . 22 ee ©) 12.1", 2, True)
    assert got is not None and got[1] == [None, None]


def test_unidades_y_periodo() -> None:
    assert sa.parse_units("31 December 2025 2024\nNote $m $m")[:2] == ("USD", 1_000_000)
    assert sa.parse_units("As at 31 December 2025 (Thousands of Georgian Lari)")[:2] == ("GEL", 1_000)
    assert sa.parse_units("Note £000 £'000")[:2] == ("GBP", 1_000)
    assert sa.parse_period("For the year ended 31 December 2025") == "2025-12-31"
    assert sa.parse_period("FOR THE 53 WEEKS ENDED 04 JANUARY 2026") == "2026-01-04"


# ------------------------------------------------------------------ titulos de los estados
def test_titulos_consolidados_y_distractores() -> None:
    heads = json.loads((FX / "headings.json").read_text())
    brit = sa.locate_statements({int(k): v for k, v in heads["brit_group"].items()})
    # Consolidados: la cuenta de resultados (76) y la de resultado global (77); el balance
    # consolidado (78) y NO el de la sociedad (176). Ni el cambio en patrimonio (80, 177).
    assert [p for p, _c, _t in brit[sa.INCOME]] == [76, 77]
    assert [p for p, _c, _t in brit[sa.BALANCE]] == [78]
    cgeo = sa.locate_statements({int(k): v for k, v in heads["georgia_capital"].items()})
    # «Strong balance sheet…» (38), «Post-balance sheet events» (177) o las notas no son estados.
    assert [p for p, _c, _t in cgeo[sa.BALANCE]] == [187]
    assert [p for p, _c, _t in cgeo[sa.INCOME]] == [188]


# ------------------------------------------------------------------- cifras de los 4 depositos
def test_brit_group_holdings_2025_cifras_con_pagina() -> None:
    res = _figures("brit_group", "p076_income", "p078_balance", 76, 78)
    assert res["checks"]["balance"]["ok"] and res["checks"]["income"]["ok"]
    figs = _by_metric(res)
    expected = {"revenue": 2950.3, "profit_before_tax": 716.7, "profit_for_year": 651.8, "profit_attributable": 651.8,
                "total_equity": 2723.8, "equity_attributable": 2723.8, "net_assets": 2723.8, "cash": 577.2,
                "borrowings": 685.3}
    assert {k: figs[k]["value"] for k in expected} == expected
    assert figs["cash"]["page"] == 78 and figs["revenue"]["page"] == 76
    assert figs["borrowings"]["line"] == "Borrowings . i 25 685.3 159.5"
    assert (figs["total_equity"]["unit"], figs["total_equity"]["currency"]) == ("$m", "USD")
    assert figs["total_equity"]["period_end"] == "2025-12-31" and figs["total_equity"]["comparative"] == 2291.6
    assert figs["cash"]["check"] == "suma en «Total assets»"
    assert figs["profit_attributable"]["basis"].startswith("sin minoritarios")


def test_georgia_capital_2025_nav_en_miles_de_lari() -> None:
    res = _figures("georgia_capital", "p188_income", "p187_balance", 188, 187)
    figs = _by_metric(res)
    assert res["checks"]["balance"]["why"] == "activo 5198380 = pasivo 3853 + patrimonio 5194527"
    assert figs["net_assets"]["value"] == 5194527 and figs["net_assets"]["value_millions"] == pytest.approx(5194.527)
    assert figs["net_assets"]["currency"] == "GEL" and figs["net_assets"]["scale"] == 1_000
    assert figs["profit_before_tax"]["value"] == 1892642 and figs["cash"]["value"] == 13495
    assert "borrowings" not in figs  # no tiene deuda en su balance: no se inventa


def test_brit_insurance_holdings_frs102_patrimonio_neto() -> None:
    res = _figures("brit_insurance_holdings", "p011_income", "p013_balance", 11, 13)
    figs = _by_metric(res)
    assert res["checks"]["balance"]["why"] == "patrimonio neto 1969179 = fondos propios 1969179"
    assert figs["net_assets"]["value"] == 1969179 and figs["profit_before_tax"]["value"] == 208793
    assert figs["cash"]["label"] == "Cash at bank and in hand" and figs["cash"]["value"] == 4710
    assert "revenue" not in figs  # holding sin linea de ingresos


def test_greene_king_pasivo_entre_parentesis_y_simbolo_mal_leido() -> None:
    inc = sa.parse_statement(sa.INCOME, [(20, _page("greene_king_p020_income_psm4"))], currency_hint="GBP")
    bal = sa.parse_statement(sa.BALANCE, [(22, _page("greene_king_p022_balance"))], currency_hint="GBP")
    res = sa.figures_from_statements(inc, bal)
    figs = _by_metric(res)
    assert res["checks"]["balance"]["ok"], res["checks"]["balance"]["why"]
    assert figs["net_assets"]["value"] == 2301.8 and figs["borrowings"]["value"] == pytest.approx(2206.8)
    assert figs["total_equity"]["unit"] == "£m" and "deducida del documento" in figs["total_equity"]["unit_note"]
    assert figs["profit_for_year"]["value"] == -34.7  # «Loss attributable … 34.7»: perdida


def test_iceland_foods_etiqueta_partida_y_frs102() -> None:
    # «(Loss) / profit and total comprehensive income for the» + «: : (4.7) 11.0» en la linea siguiente
    res = _figures("iceland_foods", "p031_income", "p032_balance", 31, 32)
    figs = _by_metric(res)
    assert res["checks"]["income"]["ok"] and res["checks"]["balance"]["ok"]
    assert figs["revenue"]["label"] == "Turnover" and figs["revenue"]["value"] == 4117.5
    assert figs["profit_before_tax"]["value"] == -0.9 and figs["profit_for_year"]["value"] == -4.7
    assert figs["total_equity"]["label"] == "Shareholder's funds" and figs["net_assets"]["value"] == 707.3
    assert figs["cash"]["currency"] == "GBP" and figs["cash"]["period_end"] == "2025-03-28"


def test_lectura_que_no_cuadra_no_se_usa_y_dice_por_que() -> None:
    # La primera pasada de OCR leyo «Tax 9 (41.3)» por (11.3): la cuenta no cuadra y sus cifras no se usan.
    res = _figures("greene_king", "p020_income", "p022_balance", 20, 22)
    assert not res["checks"]["income"]["ok"]
    rejected = {f["metric"]: f for f in res["rejected"]}
    assert rejected["profit_before_tax"]["reason"].startswith("no cuadra")
    assert "profit_before_tax" not in _by_metric(res)


def test_balance_que_no_cuadra_rechaza_todas_sus_cifras() -> None:
    text = _page("brit_group_p078_balance").replace("Total equity . - 2,723.8", "Total equity . - 2,728.8")
    res = sa.figures_from_statements(None, sa.parse_statement(sa.BALANCE, [(78, text)]))
    assert res["figures"] == []
    assert {f["metric"] for f in res["rejected"]} >= {"total_equity", "cash", "borrowings"}
    assert all(f["reason"].startswith("no cuadra") for f in res["rejected"])


# --------------------------------------------------------------- PDF completo (OCR simulado)
def _blank_pdf(pages: int) -> bytes:
    import io

    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument.new()
    for _ in range(pages):
        doc.new_page(595, 842)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def test_extract_from_pdf_retoma_otra_pasada_si_no_cuadra() -> None:
    pages = {2: _page("greene_king_p020_income"), 3: _page("greene_king_p022_balance")}
    heads = {2: "GROUP INCOME STATEMENT\nFOR THE 53 WEEKS ENDED 04 JANUARY 2026", 3: "GROUP BALANCE SHEET\nAS AT 04 JANUARY 2026\nNote £m £m"}
    calls: list[tuple[int, str]] = []
    state = {"i": 0}

    def ocr(png: bytes, psm: str = "6") -> str:
        state["i"] += 1
        n = state["i"]
        if n <= 4:  # indice de titulos, una pagina cada vez
            return heads.get(n, "Strategic report")
        calls.append((n, psm))
        if len(calls) == 1:
            return pages[2]
        if len(calls) == 2:
            return pages[3]
        if len(calls) == 3:  # segunda pasada (psm 4) de la cuenta de resultados
            return _page("greene_king_p020_income_psm4")
        return pages[3]

    res = sa.extract_from_pdf(_blank_pdf(4), ocr=ocr)
    assert res["status"] == "ok", res.get("reason")
    assert res["statements"]["income"]["ocr_pass"] == "300 ppp, psm 4"
    figs = _by_metric(res)
    assert figs["profit_before_tax"]["page"] == 2 and figs["net_assets"]["page"] == 3
    assert res["page_count"] == 4


def test_extract_from_pdf_sin_estados() -> None:
    res = sa.extract_from_pdf(_blank_pdf(2), ocr=lambda png, psm="6": "Directors' report")
    assert res["status"] == "not_found" and res["figures"] == []


# --------------------------------------------------- integracion: Companies House y SOTP
def _cached() -> dict[str, Any]:
    res = _figures("brit_group", "p076_income", "p078_balance", 76, 78)
    return {**res, "status": "ok", "reason": None, "statements": {}}


def test_latest_accounts_adjunta_cifras_ocr_con_enlace_a_la_pagina(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import companies_house_evidence as che

    monkeypatch.setattr(sa, "load_cached", lambda number, made_up: _cached() if number == "15884169" else None)
    doc = "https://find-and-update.company-information.service.gov.uk/company/15884169/filing-history/TX/document?format=pdf&download=0"
    row = {"company_number": "15884169", "made_up_to": "2025-12-31", "document_url": doc}
    che.attach_scanned_figures(row)
    figs = {f["metric"]: f for f in row["figures"]}
    assert figs["total_equity"]["page_url"] == doc + "#page=78"
    assert figs["total_equity"]["concept"] == "pág. 78: «Total equity»"
    pending = {"company_number": "99999999", "made_up_to": "2025-12-31", "document_url": doc}
    che.attach_scanned_figures(pending)
    assert pending["scanned"] == {"status": "pending"}


def test_companies_house_outputs_cita_pagina_y_linea(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import companies_house_evidence as che
    from app.services.expert_team.sotp_valuer import companies_house_outputs

    monkeypatch.setattr(sa, "load_cached", lambda number, made_up: _cached())
    row = {"company_number": "15884169", "company_name": "BRIT GROUP HOLDINGS LIMITED", "made_up_to": "2025-12-31",
           "document_url": "https://find-and-update.company-information.service.gov.uk/x/document?format=pdf",
           "accounts_type": "group", "via": "PSC"}
    che.attach_scanned_figures(row)
    out = companies_house_outputs({"members": [row]})[0]
    cifras = out.data["cifras"]
    assert cifras["total_equity"]["millones"] == 2723.8 and cifras["total_equity"]["pagina"] == 78
    assert cifras["cash"]["enlace"].endswith("#page=78")
    assert "pág. 78: «Cash and cash equivalents 24 577.2 476.4»" in out.data["quote"]
    assert "el balance cuadra" in out.data["nota"]


def test_queue_scanned_reads_encola_una_vez(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import companies_house_evidence as che
    from app.workers import dramatiq_app

    sent: list[tuple[Any, ...]] = []
    claimed: set[str] = set()
    monkeypatch.setattr(dramatiq_app.extract_scanned_accounts, "send", lambda *a, **k: sent.append(a))
    monkeypatch.setattr(sa, "claim_pending", lambda n, m: not (n in claimed or claimed.add(n)))
    result = {"members": [
        {"company_number": "10852406", "company_name": "GEORGIA CAPITAL PLC", "via": "nombre exacto del holding",
         "document_url": "https://find-and-update.company-information.service.gov.uk/a", "made_up_to": "2025-12-31",
         "accounts_type": "full", "scanned": {"status": "pending"}},
        {"company_number": "15884169", "company_name": "BRIT", "via": "PSC", "depth": 2, "pages": 193,
         "document_url": "https://find-and-update.company-information.service.gov.uk/b", "made_up_to": "2025-12-31",
         "accounts_type": "group", "scanned": {"status": "pending"}},
        {"company_number": "00000001", "company_name": "IXBRL LTD", "via": "PSC", "depth": 3,
         "document_url": "https://find-and-update.company-information.service.gov.uk/c", "accounts_type": "group",
         "figures": [{"metric": "revenue"}]},
    ]}
    assert che.queue_scanned_reads(result, "CGEO.L") == 2
    assert che.queue_scanned_reads(result, "CGEO.L") == 0
    assert [a[0] for a in sent] == ["10852406", "15884169"]


def test_descarga_solo_de_companies_house() -> None:
    with pytest.raises(ValueError):
        sa.download_public_pdf("https://example.com/accounts.pdf")


def test_sotp_get_lleva_companies_house_de_la_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api.routes import sotp

    doc = "https://find-and-update.company-information.service.gov.uk/x/document?format=pdf"
    monkeypatch.setattr(sa, "for_ticker", lambda t: [{**_cached(), "company_name": "BRIT GROUP HOLDINGS LIMITED",
                                                      "company_number": "15884169", "made_up_to": "2025-12-31",
                                                      "document_url": doc, "page_count": 193}])
    rows = sotp.companies_house_scanned("FFH.TO")
    assert rows[0]["company_number"] == "15884169" and rows[0]["page_count"] == 193
    cash = next(f for f in rows[0]["figures"] if f["metric"] == "cash")
    assert cash["page_url"] == doc + "#page=78" and cash["line"].startswith("Cash and cash equivalents")
