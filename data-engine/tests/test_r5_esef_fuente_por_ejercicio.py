"""Hechos ESEF citables por ejercicio (r5-bugs2, 11-nov-2026).

Antes: la ingesta ESEF deja ``Document.source_url`` vacío a propósito (un snapshot normalizado no es un filing)
y guarda en ``metadata.filing_sources`` la URL verificada (con sha256) de cada informe anual de filings.xbrl.org o
del NSM de la FCA. Nadie la leía: ``FinancialFact.source_url`` salía None para TODO hecho ESEF, y la salud
(Piotroski/Altman), que solo usa cifras con fuente https, decía «Sin ejercicios anuales con fuente» para Airbus,
Eurofins o Intertek aunque cada ejercicio tenga su informe oficial enlazable.

Ahora el hecho cita el informe del que sale su cifra: ``merge_facts`` fusiona del filing más reciente al más
antiguo, así que la cifra del ejercicio N viene del informe N+1 (comparativo, recoge reexpresiones) si está, y si
no del informe N. Sin informe que lo cubra, sigue None: nunca un enlace inventado.
"""
from datetime import date

from app.models import Document, FinancialFact

LEI = "MINO79WLOO247M1IL051"


def _src(year: int, origin: str = "filings.xbrl.org") -> dict:
    return {"period_end": f"{year}-12-31", "origin": origin,
            "url": f"https://filings.xbrl.org/{LEI}/{year}-12-31/ESEF/NL/0/{LEI}-{year}-12-31-en.json",
            "fxo_id": f"{LEI}-{year}-12-31-ESEF-NL-0", "sha256": "ab" * 32}


def _doc(sources: list[dict] | None, url: str | None = None) -> Document:
    meta = {"provider": "ESEF", "normalized": True}
    if sources is not None:
        meta["filing_sources"] = sources
    return Document(title="ESEF XBRL facts - AIR.PA", source_type="ESEF", source_url=url, metadata_=meta)


def _fact(period: str, doc: Document) -> FinancialFact:
    fact = FinancialFact(metric="net_income", value=1, unit="EUR", period=period, fiscal_quarter="FY")
    fact.source = doc
    return fact


def test_ultimo_ejercicio_cita_su_propio_informe():
    doc = _doc([_src(2025), _src(2024), _src(2023)])
    assert _fact("2025-12-31:FY", doc).source_url == _src(2025)["url"]


def test_ejercicio_anterior_cita_el_informe_siguiente_que_lo_trae_como_comparativo():
    doc = _doc([_src(2025), _src(2024), _src(2023)])
    assert _fact("2024-12-31:FY", doc).source_url == _src(2025)["url"]
    assert _fact("2023-12-31:FY", doc).source_url == _src(2024)["url"]


def test_ejercicio_mas_antiguo_cita_el_informe_que_lo_cubre():
    # 2022 solo lo cubre el informe de 2023 (comparativo); 2021 no lo cubre ninguno → None.
    doc = _doc([_src(2025), _src(2024), _src(2023)])
    assert _fact("2022-12-31:FY", doc).source_url == _src(2023)["url"]
    assert _fact("2021-12-31:FY", doc).source_url is None


def test_informe_nsm_de_la_fca_tambien_vale():
    nsm = {"period_end": "2025-12-31", "origin": "fca_nsm",
           "url": "https://data.fca.org.uk/artefacts/NSM/RNS/abc.zip", "sha256": "cd" * 32}
    assert _fact("2025-12-31:FY", _doc([nsm])).source_url == nsm["url"]


def test_sin_informes_o_enlace_no_https_sigue_sin_fuente():
    assert _fact("2025-12-31:FY", _doc(None)).source_url is None
    assert _fact("2025-12-31:FY", _doc([])).source_url is None
    bad = {**_src(2025), "url": "filings.xbrl.org/api/filings (fxo_id=x)"}
    assert _fact("2025-12-31:FY", _doc([bad])).source_url is None
    assert _fact("2025-12-31:FY", _doc([{"period_end": "basura", "url": _src(2025)["url"]}])).source_url is None
    assert _fact("sin-fecha", _doc([_src(2025)])).source_url is None


def test_url_guardada_del_documento_manda():
    real = "https://www.sec.gov/Archives/edgar/data/1/000000000125000001/x.htm"
    assert _fact("2025-12-31:FY", _doc([_src(2025)], url=real)).source_url == real


def test_salud_de_un_emisor_esef_ya_tiene_ejercicios_con_fuente():
    """La salud recibe las cifras ESEF con su informe: ya no «Sin ejercicios anuales con fuente»."""
    from app.services.financial_health import HealthFact, calculate_health

    doc = _doc([_src(2025), _src(2024), _src(2023)])
    values = {
        2023: {"total_assets": 100},
        2024: {"total_assets": 110, "net_income": 5, "long_term_debt": 30, "current_assets": 50,
               "current_liabilities": 30, "gross_profit": 30, "revenue": 100},
        2025: {"total_assets": 120, "net_income": 12, "long_term_debt": 20, "operating_cash_flow": 15,
               "current_assets": 70, "current_liabilities": 30, "gross_profit": 44, "revenue": 130,
               "common_stock_issued": 0},
    }
    facts = []
    for year, metrics in values.items():
        for metric, value in metrics.items():
            url = _fact(f"{year}-12-31:FY", doc).source_url
            facts.append(HealthFact(len(facts) + 1, metric, year, value, "EUR", date(year, 12, 31),
                                    url or "", "ESEF", 1))
    out = calculate_health(facts, sector="Industrials", company_type="operating", today=date(2026, 11, 11))
    assert out.get("reason") != "Sin ejercicios anuales con fuente"
    assert out["piotroski"]["score"] == 9
