"""Fondos y ETF que tienen la acción, con su peso (SEC Form N-PORT Data Sets).
Nico, 8-nov-2026 (AITerminal): «escribe una acción y mira qué ETF la tienen»,
dentro de la ficha que ya existe."""

from __future__ import annotations

import io
import zipfile
from datetime import date, datetime
from decimal import Decimal

import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Company
from app.models.entities import Base
from app.models.public_market_data import PublicSourceDocument
from app.services import fund_holders as fh
from app.services.connectors import form_nport_dataset as nport

APPLE = "037833100"
URL = "https://www.sec.gov/files/dera/data/form-n-port-data-sets/2026q3_nport.zip"
REF = nport.NportDatasetRef(URL, 2026, 3)


def _zip(extra_holdings: list[str] | None = None) -> io.BytesIO:
    sub = ["ACCESSION_NUMBER\tFILING_DATE\tFILE_NUM\tSUB_TYPE\tREPORT_ENDING_PERIOD\tREPORT_DATE\tIS_LAST_FILING",
           "A1\t20-AUG-2026\t\tNPORT-P\t31-DEC-2026\t30-JUN-2026\tN",   # Big Index: 1000 acc (2 filas)
           "A0\t20-MAY-2026\t\tNPORT-P\t31-DEC-2026\t31-MAR-2026\tN",   # Big Index, informe anterior: no cuenta
           "B1\t21-AUG-2026\t\tNPORT-P\t30-SEP-2026\t30-JUN-2026\tN",   # Theme ETF: 50 acc, 8 %
           "B2\t25-AUG-2026\t\tNPORT-P/A\t30-SEP-2026\t30-JUN-2026\tN", # su enmienda: 60 acc, 9 % (sustituye)
           "C1\t22-AUG-2026\t\tNPORT-P\t30-SEP-2026\t31-JUL-2026\tN",   # Bond fund: solo PA y una corta
           "D1\t22-AUG-2026\t\tNPORT-N\t30-SEP-2026\t31-JUL-2026\tN"]   # no público: fuera
    reg = ["ACCESSION_NUMBER\tCIK\tREGISTRANT_NAME", "A1\t100\tBig Trust", "A0\t100\tBig Trust", "B1\t200\tTheme Trust",
           "B2\t200\tTheme Trust", "C1\t300\tBond Trust"]
    info = ["ACCESSION_NUMBER\tSERIES_NAME\tSERIES_ID\tSERIES_LEI\tTOTAL_ASSETS\tTOTAL_LIABILITIES\tNET_ASSETS",
            "A1\tBig Index Fund\tS000000001\t\t1\t0\t500000", "A0\tBig Index Fund\tS000000001\t\t1\t0\t400000",
            "B1\tTheme ETF\tS000000002\t\t1\t0\t700", "B2\tN/A\tS000000002\t\t1\t0\t700", "C1\tBond Fund\tS000000003\t\t1\t0\t9"]
    hold = ["ACCESSION_NUMBER\tHOLDING_ID\tISSUER_NAME\tISSUER_LEI\tISSUER_TITLE\tISSUER_CUSIP\tBALANCE\tUNIT\tOTHER_UNIT_DESC\tCURRENCY_CODE\tCURRENCY_VALUE\tEXCHANGE_RATE\tPERCENTAGE\tPAYOFF_PROFILE",
            f"A1\t1\tApple\t\tCOM\t{APPLE}\t600\tNS\t\tUSD\t120000\t\t2.0\tLong",
            f"A1\t2\tApple\t\tCOM\t{APPLE}\t400\tNS\t\tUSD\t80000\t\t1.5\tLong",
            f"A0\t3\tApple\t\tCOM\t{APPLE}\t9999\tNS\t\tUSD\t1\t\t9\tLong",
            f"B1\t4\tApple\t\tCOM\t{APPLE}\t50\tNS\t\tUSD\t10000\t\t8.0\tLong",
            f"B2\t5\tApple\t\tCOM\t{APPLE}\t60\tNS\t\tUSD\t12000\t\t9.0\tLong",
            f"C1\t6\tApple\t\tBOND\t{APPLE}\t1000\tPA\t\tUSD\t1000\t\t50\tLong",
            f"C1\t7\tApple\t\tCOM\t{APPLE}\t10\tNS\t\tUSD\t10\t\t1\tShort",
            f"D1\t8\tApple\t\tCOM\t{APPLE}\t77\tNS\t\tUSD\t10\t\t1\tLong", *(extra_holdings or [])]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, lines in (("SUBMISSION.tsv", sub), ("REGISTRANT.tsv", reg), ("FUND_REPORTED_INFO.tsv", info), ("FUND_REPORTED_HOLDING.tsv", hold)):
            zf.writestr(name, "\n".join(lines) + "\n")
    buf.seek(0)
    return buf


def test_reglas_nport_largos_en_acciones_y_ultimo_informe():
    latest = nport.latest_by_series(nport.parse_dataset(_zip(), {APPLE}))
    out = fh.summarize(latest, APPLE)
    assert out["funds"] == 2  # el de bonos (PA / corto) y el NPORT-N no cuentan
    assert out["shares"] == Decimal(1060) and out["value"] == Decimal(212000)
    assert [(r.display_name, r.shares[APPLE]) for r in out["top"]] == [("Big Index Fund", 1000), ("Theme Trust", 60)]
    assert [(r.display_name, r.weight[APPLE]) for r in out["by_weight"]] == [("Theme Trust", Decimal("9.0")), ("Big Index Fund", Decimal("3.5"))]
    assert out["top"][1].accession == "B2"  # la enmienda sustituye al original


def _db():
    db = Session(create_engine("sqlite://"))
    Base.metadata.create_all(db.get_bind())
    db.add(Company(ticker="AAPL", name="Apple", exchange="NASDAQ", company_type="mature", valuation_model="dcf", isin="US0378331005"))
    db.add(Company(ticker="CGEO.L", name="Georgia Capital", exchange="LSE", company_type="mature", valuation_model="dcf"))
    db.commit()
    return db


def test_guarda_y_lee_con_peso_fecha_y_enlace():
    db = _db()
    cusips = fh.universe_cusips(db)
    reports = nport.parse_dataset(_zip(), set(cusips))
    assert fh.ingest_reports(db, reports, REF, "x1", cusips)["companies"] == 1
    assert fh.ingest_reports(db, reports, REF, "x1", cusips)["companies"] == 0  # idempotente
    view = fh.fund_holders(db, "AAPL")
    assert view["status"] == "ok" and view["dataset"] == "2026q3"
    assert view["totals"] == {"funds": 2, "shares": 1060.0, "value_usd": 212000.0}
    big = view["top_funds"][0]
    assert big["name"] == "Big Index Fund" and big["shares"] == 1000 and big["weight_pct"] == 3.5
    assert big["report_date"] == "2026-06-30" and big["net_assets_usd"] == 500000.0
    assert big["filing_url"] == "https://www.sec.gov/Archives/edgar/data/100/A1/A1-index.htm"
    # la enmienda deja la serie en «N/A»: se muestra el registrante, nunca «N/A»
    assert view["by_weight"][0]["name"] == "Theme Trust" and view["by_weight"][0]["weight_pct"] == 9.0
    assert view["source"]["dataset_url"] == URL


def test_sin_cusip_sin_datos_y_desconocido():
    db = _db()
    assert fh.fund_holders(db, "CGEO.L")["status"] == "sin_identificador"
    assert fh.fund_holders(db, "AAPL")["status"] == "sin_datos"
    assert fh.fund_holders(db, "NOPE") is None


def test_job_descarga_solo_si_hay_fichero_nuevo():
    html = ('<a href="/files/dera/data/form-n-port-data-sets/2026q2_nport.zip">a</a>'
            '<a href="/files/dera/data/form-n-port-data-sets/2026q3_nport.zip">b</a>')
    assert [r.label for r in nport.list_datasets(html)] == ["2026q3", "2026q2"]
    body = _zip().getvalue()
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, text=html) if str(request.url) == nport.DATASETS_PAGE else httpx.Response(200, content=body)

    db = _db()
    out = fh.refresh_fund_holders(db, httpx.Client(transport=httpx.MockTransport(handler)))
    assert out["status"] == "ok" and out["companies"] == 1 and calls == [nport.DATASETS_PAGE, URL]
    again = fh.refresh_fund_holders(db, httpx.Client(transport=httpx.MockTransport(handler)))
    assert again["status"] == "sin_cambios" and calls[-1] == nport.DATASETS_PAGE
    assert db.query(PublicSourceDocument).filter(PublicSourceDocument.provider == fh.PROVIDER).count() == 1
    assert isinstance(db.query(PublicSourceDocument).first().fetched_at, datetime)
    assert date(2026, 6, 30)


MSFT = "594918104"
REF4 = nport.NportDatasetRef("https://www.sec.gov/files/dera/data/form-n-port-data-sets/2026q4_nport.zip", 2026, 4)


def test_ingesta_guarda_snapshot_vacio_y_no_sirve_el_trimestre_anterior():
    """Bug auditado: si el dataset nuevo no tiene el CUSIP en ningún fondo no se
    guardaba nada, y la ficha seguía sirviendo el trimestre anterior como actual."""
    db = _db()
    cusips = fh.universe_cusips(db)
    assert fh.ingest_reports(db, nport.parse_dataset(_zip(), set(cusips)), REF, "x1", cusips)["companies"] == 1
    out = fh.ingest_reports(db, nport.parse_dataset(_zip_con_solo_msft(), set(cusips)), REF4, "x2", cusips)
    assert out["companies"] == 1  # snapshot vacío: la empresa queda procesada para este fichero
    view = fh.fund_holders(db, "AAPL")
    assert view["status"] == "ok" and view["dataset"] == "2026q4"
    assert view["totals"] == {"funds": 0, "shares": 0.0, "value_usd": 0.0}
    assert view["top_funds"] == [] and view["by_weight"] == []
    assert view["source"]["dataset_url"] == REF4.url


def _zip_con_solo_msft() -> io.BytesIO:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("SUBMISSION.tsv", "\n".join([
            "ACCESSION_NUMBER\tFILING_DATE\tFILE_NUM\tSUB_TYPE\tREPORT_ENDING_PERIOD\tREPORT_DATE\tIS_LAST_FILING",
            "E1\t20-NOV-2026\t\tNPORT-P\t31-DEC-2026\t30-SEP-2026\tN"]) + "\n")
        zf.writestr("REGISTRANT.tsv", "ACCESSION_NUMBER\tCIK\tREGISTRANT_NAME\nE1\t900\tOther Trust\n")
        zf.writestr("FUND_REPORTED_INFO.tsv", "\n".join([
            "ACCESSION_NUMBER\tSERIES_NAME\tSERIES_ID\tSERIES_LEI\tTOTAL_ASSETS\tTOTAL_LIABILITIES\tNET_ASSETS",
            "E1\tOther Fund\tS000000009\t\t1\t0\t1000"]) + "\n")
        zf.writestr("FUND_REPORTED_HOLDING.tsv", "\n".join([
            "ACCESSION_NUMBER\tHOLDING_ID\tISSUER_NAME\tISSUER_LEI\tISSUER_TITLE\tISSUER_CUSIP\tBALANCE\tUNIT\tOTHER_UNIT_DESC\tCURRENCY_CODE\tCURRENCY_VALUE\tEXCHANGE_RATE\tPERCENTAGE\tPAYOFF_PROFILE",
            f"E1\t1\tMicrosoft\t\tCOM\t{MSFT}\t500\tNS\t\tUSD\t60000\t\t3.0\tLong"]) + "\n")
    buf.seek(0)
    return buf


def test_job_reprocesa_cuando_el_universo_crece_aunque_el_fichero_ya_estaba():
    """Bug auditado: bastaba UN documento del fichero para dar el trimestre por
    procesado; una empresa añadida al universo después se saltaba todo el trimestre."""
    html = '<a href="/files/dera/data/form-n-port-data-sets/2026q3_nport.zip">b</a>'
    body = _zip([f"A1\t9\tMicrosoft\t\tCOM\t{MSFT}\t500\tNS\t\tUSD\t60000\t\t3.0\tLong"]).getvalue()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=html) if str(request.url) == nport.DATASETS_PAGE else httpx.Response(200, content=body)

    db = _db()
    out = fh.refresh_fund_holders(db, httpx.Client(transport=httpx.MockTransport(handler)))
    assert out["status"] == "ok" and out["companies"] == 1
    # MSFT entra en el universo DESPUÉS de procesar el trimestre (su CUSIP está en el ZIP)
    db.add(Company(ticker="MSFT", name="Microsoft", exchange="NASDAQ", company_type="mature", valuation_model="dcf",
                   isin="US5949181045"))
    db.commit()
    again = fh.refresh_fund_holders(db, httpx.Client(transport=httpx.MockTransport(handler)))
    assert again["status"] == "ok" and again["companies"] == 1  # solo MSFT; AAPL ya estaba
    view = fh.fund_holders(db, "MSFT")
    assert view["status"] == "ok" and view["dataset"] == "2026q3"
    assert view["totals"] == {"funds": 1, "shares": 500.0, "value_usd": 60000.0}
    third = fh.refresh_fund_holders(db, httpx.Client(transport=httpx.MockTransport(handler)))
    assert third["status"] == "sin_cambios"  # universo completo ya procesado


def test_corregir_el_cusip_invalida_el_snapshot_y_se_recalcula():
    """Residual de #4843 (N-PORT): corregir el CUSIP de una empresa ya procesada
    dejaba la ficha sirviendo posiciones del CUSIP anterior. Ahora el snapshot va
    ligado al CUSIP: la lectura solo sirve el calculado con el actual y re-ingerir
    el mismo fichero crea un snapshot nuevo."""
    db = _db()
    cusips = fh.universe_cusips(db)
    assert set(cusips) == {APPLE}
    assert fh.ingest_reports(db, nport.parse_dataset(_zip(), set(cusips)), REF, "x1", cusips)["companies"] == 1
    # El CUSIP guardado resulta erróneo y se corrige al de Microsoft (que sí está en el ZIP).
    db.query(Company).filter(Company.ticker == "AAPL").one().isin = "US5949181045"
    db.commit()
    cusips = fh.universe_cusips(db)
    assert set(cusips) == {MSFT}
    # La lectura no sirve el snapshot del CUSIP anterior.
    assert fh.fund_holders(db, "AAPL")["status"] == "sin_datos"
    # Re-ingerir el mismo fichero crea un snapshot nuevo para el CUSIP corregido.
    reports = nport.parse_dataset(_zip_con_solo_msft(), set(cusips))
    assert fh.ingest_reports(db, reports, REF, "x1", cusips)["companies"] == 1
    view = fh.fund_holders(db, "AAPL")
    assert view["status"] == "ok" and view["cusip"] == MSFT
    assert view["totals"] == {"funds": 1, "shares": 500.0, "value_usd": 60000.0}


def test_documento_sin_cusip_grabado_sigue_sirviendo():
    """Documentos de antes de la vinculación (listing_key sin CUSIP) se siguen
    sirviendo tal cual: no se rompe lo ya guardado."""
    db = _db()
    cusips = fh.universe_cusips(db)
    fh.ingest_reports(db, nport.parse_dataset(_zip(), set(cusips)), REF, "x1", cusips)
    doc = db.query(PublicSourceDocument).one()
    doc.listing_key = "nport:2026q3"  # como quedó antes de la vinculación
    db.commit()
    view = fh.fund_holders(db, "AAPL")
    assert view["status"] == "ok" and view["dataset"] == "2026q3" and view["totals"]["funds"] == 2


def test_refresh_recalcula_si_el_snapshot_no_es_del_cusip_actual():
    """«Procesado» exige documento calculado con el CUSIP actual: un documento
    legado (sin CUSIP) o con otro CUSIP obliga a recalcular, así corregir la
    identidad de una empresa invalida su snapshot guardado."""
    html = '<a href="/files/dera/data/form-n-port-data-sets/2026q3_nport.zip">b</a>'
    body = _zip().getvalue()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=html) if str(request.url) == nport.DATASETS_PAGE else httpx.Response(200, content=body)

    for legacy_key in ("nport:2026q3", f"nport:2026q3:{MSFT}"):
        db = _db()
        db.add(PublicSourceDocument(company_id=1, listing_key=legacy_key, provider=fh.PROVIDER, source_url=URL,
                                    checksum="x", fetched_at=datetime(2026, 9, 1), official=True))
        db.commit()
        out = fh.refresh_fund_holders(db, httpx.Client(transport=httpx.MockTransport(handler)))
        assert out["status"] == "ok" and out["companies"] == 1  # recalcula, no «sin_cambios»
        again = fh.refresh_fund_holders(db, httpx.Client(transport=httpx.MockTransport(handler)))
        assert again["status"] == "sin_cambios"


def test_ingesta_sin_informes_validos_no_persiste_ni_marca_procesado():
    """Parser que devuelve {} (cabeceras o fechas cambiadas, sin lanzar): N/D,
    no «0 fondos», y el fichero NO queda procesado (el reintento no se congela)."""
    db = _db()
    cusips = fh.universe_cusips(db)
    out = fh.ingest_reports(db, {}, REF, "x9", cusips)
    assert out["status"] == "sin_datos" and out["companies"] == 0 and out["series"] == 0
    assert db.query(PublicSourceDocument).count() == 0
    assert fh.fund_holders(db, "AAPL")["status"] == "sin_datos"
