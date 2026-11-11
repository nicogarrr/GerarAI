"""«Directivos e incentivos» (management_alignment) para emisores europeos y para los que no presentan en la
moneda en la que cotizan.

Antes: (1) todo hecho ESEF se descartaba porque se exigía una fecha de depósito que filings.xbrl.org no da y se
leía la URL del snapshot (vacía) en vez del informe anual del ejercicio; (2) las cifras se comparaban con la
moneda de COTIZACIÓN (TSM en TWD y CNQ en CAD cotizan en USD), así que sus recompras/SBC/ingresos se perdían.
Escenarios sintéticos; las etiquetas de empresa no son afirmaciones financieras.
"""
from datetime import date
from decimal import Decimal
from types import SimpleNamespace as NS

from app.services import management_alignment as m

TODAY = date(2026, 11, 11)
URL25 = "https://filings.xbrl.org/LEI/2025-12-31/ESEF/GB/0/report.json"
URL24 = "https://filings.xbrl.org/LEI/2024-12-31/ESEF/GB/0/report.json"


def esef_doc(**meta):
    base = {"reporting_currency": "GBP", "snapshot_fetched_at": "2026-04-02T10:00:00+00:00",
            "filing_sources": [{"period_end": "2025-12-31", "origin": "filings.xbrl.org", "url": URL25},
                               {"period_end": "2024-12-31", "origin": "filings.xbrl.org", "url": URL24}]}
    return NS(source_url=None, company_id=7, metadata_={**base, **meta})


def esef_fact(metric, amount, year=2025, doc=None, **kw):
    return NS(**{"id": 1, "metric": metric, "value": Decimal(str(amount)), "unit": "GBP", "period": f"{year}-12-31:FY",
                 "fiscal_year": year, "fiscal_quarter": "FY", "filed": None, "source_type": "ESEF", "is_reported": True,
                 "accession_number": None, "source": doc if doc is not None else esef_doc(), **kw})


EUROPEAN = NS(cik=None, currency="GBP", ticker="EU1")


def test_esef_sin_fecha_de_deposito_cita_el_informe_del_ejercicio():
    e = m._evidence(esef_fact("revenue", 3000), EUROPEAN, TODAY)
    assert e is not None
    assert e["url"] == URL25
    assert e["filed"] is None  # filings.xbrl.org no da fecha de depósito: no se inventa
    prior = m._evidence(esef_fact("revenue", 2900, 2024), EUROPEAN, TODAY)
    assert prior is not None and prior["url"] == URL25  # el comparativo sale del informe más reciente que lo cubre


def test_esef_nsm_usa_su_fecha_de_deposito():
    doc = esef_doc(filing_sources=[{"period_end": "2025-12-31", "origin": "fca_nsm", "url": URL25,
                                    "submitted_date": "2026-03-05"}])
    e = m._evidence(esef_fact("revenue", 3000, doc=doc), EUROPEAN, TODAY)
    assert e is not None and e["filed"] == "2026-03-05"


def test_esef_sin_informe_o_sin_cota_temporal_no_publica_cifra():
    assert m._evidence(esef_fact("revenue", 3000, doc=esef_doc(filing_sources=[])), EUROPEAN, TODAY) is None
    no_known = esef_doc(snapshot_fetched_at=None)
    assert m._evidence(esef_fact("revenue", 3000, doc=no_known), EUROPEAN, TODAY) is None
    # Con «hoy» anterior a la descarga del informe no se mira al futuro.
    assert m._evidence(esef_fact("revenue", 3000), EUROPEAN, date(2026, 3, 1)) is None


def test_esef_moneda_de_los_informes_sin_ingresos_de_metadata():
    rows = m.dilution_years([esef_fact("common_stock_repurchased", 250)], NS(cik=None, currency="GBX", ticker="EU2"), [], TODAY)
    assert rows and rows[-1]["repurchases"]["value"] == 250 and rows[-1]["repurchases"]["unit"] == "GBP"


def sec_fact(metric, amount, year=2025, unit="TWD"):
    return NS(id=1, metric=metric, value=Decimal(str(amount)), unit="shares" if metric.startswith("shares_") else unit,
              period=f"{year}-12-31:FY", fiscal_year=year, fiscal_quarter="FY", filed=date(year + 1, 4, 15),
              source_type="SEC", is_reported=True, accession_number=f"0001046179-{str(year + 1)[2:]}-000001", source=None)


def test_adr_que_presenta_en_su_moneda_no_pierde_cifras():
    adr = NS(cik="0001046179", currency="USD", ticker="ADR1")  # cotiza en USD, presenta en TWD
    facts = [sec_fact("revenue", 1000), sec_fact("stock_based_compensation", 20), sec_fact("common_stock_repurchased", 30),
             sec_fact("operating_cash_flow", 500), sec_fact("capital_expenditure", -300), sec_fact("shares_diluted", 25)]
    row = m.dilution_years(facts, adr, [], TODAY)[-1]
    assert row["sbc_revenue_pct"]["value"] == 2.0
    assert row["sbc_fcf_pct"]["value"] == 10.0
    assert row["repurchases"]["value"] == 30 and row["repurchases"]["unit"] == "TWD"
    assert not any("Recompras N/D" in w for w in row["warnings"])


def test_cifra_en_otra_moneda_que_la_de_los_informes_sigue_fuera():
    adr = NS(cik="0001046179", currency="USD", ticker="ADR1")
    facts = [sec_fact("revenue", 1000), sec_fact("stock_based_compensation", 20, unit="USD")]
    row = m.dilution_years(facts, adr, [], TODAY)[-1]
    assert row["sbc"] is None and row["sbc_revenue_pct"]["value"] is None
