"""Institucionales de todo el 13F (Form 13F Data Sets de la SEC): quién tiene
la acción, quién compra y quién vende. Nico, 8-nov-2026: «quién compra y quién
vende» de AITerminal, dentro de la ficha que ya existe (sin pestaña nueva)."""

from __future__ import annotations

import io
import zipfile
from datetime import date
from decimal import Decimal

import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Company
from app.models.entities import Base
from app.models.public_market_data import PublicFinancialFact, PublicSourceDocument
from app.services import institutional_holders as ih
from app.services.connectors import form13f_dataset as ds

APPLE = "037833100"
OTHER = "594918104"

SUB_H = "ACCESSION_NUMBER\tFILING_DATE\tSUBMISSIONTYPE\tCIK\tPERIODOFREPORT"
COV_H = "ACCESSION_NUMBER\tREPORTCALENDARORQUARTER\tISAMENDMENT\tAMENDMENTNO\tAMENDMENTTYPE\tFILINGMANAGER_NAME"
INF_H = "ACCESSION_NUMBER\tINFOTABLE_SK\tNAMEOFISSUER\tTITLEOFCLASS\tCUSIP\tFIGI\tVALUE\tSSHPRNAMT\tSSHPRNAMTTYPE\tPUTCALL"


def _zip(subs, covs, infos, summary=()) -> io.BytesIO:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("SUBMISSION.tsv", "\n".join([SUB_H, *subs]) + "\n")
        zf.writestr("COVERPAGE.tsv", "\n".join([COV_H, *covs]) + "\n")
        zf.writestr("INFOTABLE.tsv", "\n".join([INF_H, *infos]) + "\n")
        zf.writestr("SUMMARYPAGE.tsv", "\n".join(["ACCESSION_NUMBER\tOTHERINCLUDEDMANAGERSCOUNT\tTABLEENTRYTOTAL", *summary]) + "\n")
    buf.seek(0)
    return buf


def _info(acc, cusip, shares, kind="SH", putcall=""):
    return f"{acc}\t1\tX\tCOM\t{cusip}\t\t1\t{shares}\t{kind}\t{putcall}"


def _datasets():
    """Q1 (ZIP anterior) y Q2 (ZIP reciente) con los casos de las reglas."""
    q1 = _zip(
        [f"Q1-{m}\t15-MAY-2026\t13F-HR\t{cik}\t31-MAR-2026" for m, cik in (("A", "1"), ("B", "2"), ("C", "3"), ("D", "4"), ("E", "5"), ("F", "6"), ("N", "8"))],
        [f"Q1-{m}\t31-MAR-2026\t\t\t\t{name}" for m, name in (("A", "Alpha"), ("B", "Beta"), ("C", "Gamma"), ("D", "Delta"), ("E", "Eps"), ("F", "Phi"))],
        [_info("Q1-A", APPLE, 100), _info("Q1-B", APPLE, 50), _info("Q1-C", APPLE, 30), _info("Q1-D", APPLE, 20), _info("Q1-E", APPLE, 5),
         _info("Q1-F", OTHER, 3), _info("Q1-N", OTHER, 1)],
        ["Q1-N\t0\t40", "Q1-A\t0\t1"],
    )
    q2 = _zip(
        [
            "Q2-A\t10-AUG-2026\t13F-HR\t1\t30-JUN-2026",   # Alpha: 100 -> 150 (dos filas) y una CALL que no cuenta
            "Q2-B\t11-AUG-2026\t13F-HR\t2\t30-JUN-2026",   # Beta: 50 -> 40 tras RESTATEMENT
            "Q2-B2\t20-AUG-2026\t13F-HR/A\t2\t30-JUN-2026",
            "Q2-C\t12-AUG-2026\t13F-HR\t3\t30-JUN-2026",   # Gamma: presenta sin Apple -> vende_todo
            "Q2-F\t13-AUG-2026\t13F-HR\t6\t30-JUN-2026",   # Phi: nuevo 70 (+10 en NEW HOLDINGS)
            "Q2-F2\t21-AUG-2026\t13F-HR/A\t6\t30-JUN-2026",
            "Q2-E\t14-AUG-2026\t13F-HR\t5\t30-JUN-2026",   # Eps: igual
            "Q2-E2\t22-AUG-2026\t13F-HR/A\t5\t30-JUN-2026",  # enmienda sin tipo: se ignora
            "Q2-N\t14-AUG-2026\t13F-HR\t8\t30-JUN-2026",   # Nu: su 13F de Q1 declara 40 filas y trae 1 -> sin_13f_previo, no es compra
            "OLD\t01-JUN-2026\t13F-HR\t9\t31-DEC-2025",
            "NT\t10-AUG-2026\t13F-NT\t7\t30-JUN-2026",
            # Delta (cik 4) no presenta Q2 -> sin_13f_aun
        ],
        [
            "Q2-A\t30-JUN-2026\t\t\t\tAlpha", "Q2-B\t30-JUN-2026\t\t\t\tBeta", "Q2-B2\t30-JUN-2026\tY\t1\tRESTATEMENT\tBeta",
            "Q2-C\t30-JUN-2026\t\t\t\tGamma", "Q2-F\t30-JUN-2026\t\t\t\tPhi", "Q2-F2\t30-JUN-2026\tY\t1\tNEW HOLDINGS\tPhi",
            "Q2-E\t30-JUN-2026\t\t\t\tEps", "Q2-E2\t30-JUN-2026\tY\t2\t\tEps", "Q2-N\t30-JUN-2026\t\t\t\tNu",
        ],
        [
            _info("Q2-A", APPLE, 100), _info("Q2-A", APPLE, 50), _info("Q2-A", APPLE, 999, putcall="CALL"),
            _info("Q2-A", APPLE, 7, kind="PRN"), _info("Q2-B", APPLE, 55), _info("Q2-B2", APPLE, 40),
            _info("Q2-C", OTHER, 10), _info("Q2-F", APPLE, 60), _info("Q2-F2", APPLE, 10), _info("Q2-E", APPLE, 5),
            _info("Q2-E2", APPLE, 500), _info("Q2-N", APPLE, 900),
        ],
    )
    return q2, q1


def _parsed_con(cusips: set[str]):
    q2, q1 = _datasets()
    return [ds.parse_dataset(q2, cusips, url="https://www.sec.gov/files/x/01jun2026-31aug2026_form13f.zip"),
            ds.parse_dataset(q1, cusips, url="https://www.sec.gov/files/x/01mar2026-31may2026_form13f.zip")]


def _parsed():
    return _parsed_con({APPLE})


def test_reglas_13f_opciones_filas_y_enmiendas():
    periods, ignored = ds.resolve_periods(_parsed())
    q2 = periods[date(2026, 6, 30)]
    assert q2["0000000001"].shares[APPLE] == Decimal(150)  # sin CALL ni PRN
    assert q2["0000000002"].shares[APPLE] == Decimal(40)   # RESTATEMENT sustituye
    assert q2["0000000002"].accession == "Q2-B2"
    assert q2["0000000006"].shares[APPLE] == Decimal(70)   # NEW HOLDINGS suma
    assert q2["0000000005"].shares[APPLE] == Decimal(5)    # enmienda sin tipo ignorada
    # la enmienda sin tipo, el 13F de Q1 de Nu incompleto (1 de 40 filas) y el de 2025 sin filas
    assert ignored == 3
    assert "0000000008" not in periods[date(2026, 3, 31)]
    assert "0000000007" not in q2  # 13F-NT sin posiciones


def test_original_incompleto_se_rescata_con_su_restatement_completa():
    """Un banco presentó su 13F con 378 de 33.063 filas y la tabla entera en una
    RESTATEMENT del mismo día: la cartera es la RESTATEMENT, no «sin 13F».
    Una RESTATEMENT incompleta, en cambio, no sustituye a un original completo."""
    q = _zip(
        ["J1\t13-MAY-2026\t13F-HR\t11\t31-MAR-2026", "J2\t13-MAY-2026\t13F-HR/A\t11\t31-MAR-2026",
         "K1\t13-MAY-2026\t13F-HR\t12\t31-MAR-2026", "K2\t14-MAY-2026\t13F-HR/A\t12\t31-MAR-2026"],
        ["J1\t31-MAR-2026\t\t\t\tJota", "J2\t31-MAR-2026\tY\t1\tRESTATEMENT\tJota",
         "K1\t31-MAR-2026\t\t\t\tKappa", "K2\t31-MAR-2026\tY\t1\tRESTATEMENT\tKappa"],
        [_info("J1", OTHER, 1), _info("J2", APPLE, 300), _info("J2", OTHER, 2),
         _info("K1", APPLE, 80), _info("K1", OTHER, 4), _info("K2", APPLE, 1)],
        ["J1\t0\t2", "J2\t0\t2", "K1\t0\t2", "K2\t0\t40"],
    )
    periods, ignored = ds.resolve_periods([ds.parse_dataset(q, {APPLE}, url="https://www.sec.gov/files/x/q.zip")])
    q1 = periods[date(2026, 3, 31)]
    assert q1["0000000011"].accession == "J2" and q1["0000000011"].shares[APPLE] == Decimal(300)
    assert q1["0000000012"].accession == "K1" and q1["0000000012"].shares[APPLE] == Decimal(80)
    assert ignored == 1  # la RESTATEMENT incompleta de Kappa


def test_estado_por_gestor_y_totales():
    periods, _ = ds.resolve_periods(_parsed())
    out = ih.summarize(periods, APPLE, date(2026, 6, 30), date(2026, 3, 31))
    t = out["totals"]
    assert (t["holders"], t["holders_prior"]) == (5, 5)
    assert (t["shares"], t["shares_prior"]) == (Decimal(1165), Decimal(205))
    assert (t["nuevo"], t["aumenta"], t["reduce"], t["igual"], t["vende_todo"], t["sin_13f_aun"], t["sin_13f_previo"]) == (1, 1, 1, 1, 1, 1, 1)
    # Neto solo de quien presentó ambos trimestres: +50 -10 -30 +0 +70 = +80 (Nu no presentó Q1, Delta no ha presentado Q2).
    assert t["net_comparable"] == Decimal(80)
    assert [r.manager for r in out["top"]] == ["Nu", "Alpha", "Phi", "Beta", "Eps"]
    # Nu (900, sin 13F previo) NO es un comprador: no consta qué tenía.
    assert [(r.manager, r.change) for r in out["buyers"]] == [("Phi", 70), ("Alpha", 50)]
    assert [(r.manager, r.status) for r in out["sellers"]] == [("Gamma", "vende_todo"), ("Beta", "reduce")]


def _db():
    db = Session(create_engine("sqlite://"))
    Base.metadata.create_all(db.get_bind())
    db.add(Company(ticker="AAPL", name="Apple", exchange="NASDAQ", company_type="mature", valuation_model="dcf", isin="US0378331005"))
    db.add(Company(ticker="CGEO.L", name="Georgia Capital", exchange="LSE", company_type="mature", valuation_model="dcf"))
    db.commit()
    return db


def test_guarda_y_lee_con_cita_por_cifra():
    db = _db()
    cusips = ih.universe_cusips(db)
    assert set(cusips) == {APPLE}
    result = ih.ingest_parsed(db, _parsed(), ["c2", "c1"], cusips)
    assert result["status"] == "ok" and result["companies"] == 1
    again = ih.ingest_parsed(db, _parsed(), ["c2", "c1"], cusips)
    assert again["companies"] == 0  # idempotente por checksum
    assert db.query(PublicSourceDocument).count() == 1
    assert db.query(PublicFinancialFact).filter(PublicFinancialFact.accession == "Q2-B2").count() == 1

    view = ih.institutional_holders(db, "aapl")
    assert view["status"] == "ok" and view["period"] == "2026-06-30" and view["prior_period"] == "2026-03-31"
    assert view["source"]["dataset_url"].endswith("01jun2026-31aug2026_form13f.zip")
    assert view["source"]["prior_dataset_url"].endswith("01mar2026-31may2026_form13f.zip")
    assert view["totals"]["holders"] == 5 and view["totals"]["sin_13f_aun"] == 1 and view["totals"]["sin_13f_previo"] == 1
    assert view["top_holders"][0]["name"] == "Nu" and view["top_holders"][0]["status"] == "sin_13f_previo"
    top = view["top_holders"][1]
    assert top["name"] == "Alpha" and top["shares"] == 150 and top["prev_shares"] == 100
    assert top["change_pct"] == 50.0 and round(top["pct_of_13f"], 2) == round(150 / 1165 * 100, 2)
    assert top["filing_url"] == "https://www.sec.gov/Archives/edgar/data/1/Q2A/Q2-A-index.htm"
    assert [s["name"] for s in view["sellers"]] == ["Gamma", "Beta"]
    assert view["sellers"][0]["status"] == "vende_todo" and view["sellers"][0]["shares"] == 0


def test_sin_cusip_y_sin_datos_son_honestos():
    db = _db()
    assert ih.institutional_holders(db, "CGEO.L")["status"] == "sin_identificador"
    assert ih.institutional_holders(db, "AAPL")["status"] == "sin_datos"
    assert ih.institutional_holders(db, "NOPE") is None


def test_pagina_de_la_sec_y_job_sin_cambios():
    html = ('<a href="/files/structureddata/data/form-13f-data-sets/01mar2026-31may2026_form13f.zip">x</a>'
            '<a href="/files/datastandardsinnovation/data/form-13f-data-sets/01jun2026-31aug2026_form13f.zip">y</a>')
    refs = ds.list_datasets(html)
    assert [r.window_end for r in refs] == [date(2026, 8, 31), date(2026, 5, 31)]
    db = _db()
    db.add(PublicSourceDocument(company_id=1, listing_key=f"13f:2026-06-30:{APPLE}", provider=ih.PROVIDER, source_url=refs[0].url,
                                checksum="x", fetched_at=__import__("datetime").datetime(2026, 9, 1), official=True))
    db.commit()
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, text=html)

    out = ih.refresh_institutional_holders(db, httpx.Client(transport=httpx.MockTransport(handler)))
    assert out["status"] == "sin_cambios"
    assert calls == [ds.DATASETS_PAGE]  # no descarga los ZIP si ya está


def test_job_descarga_y_calcula():
    html = ('<a href="/files/a/01mar2026-31may2026_form13f.zip">x</a><a href="/files/a/01jun2026-31aug2026_form13f.zip">y</a>')
    q2, q1 = _datasets()

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == ds.DATASETS_PAGE:
            return httpx.Response(200, text=html)
        return httpx.Response(200, content=(q2 if "jun2026" in url else q1).getvalue())

    db = _db()
    out = ih.refresh_institutional_holders(db, httpx.Client(transport=httpx.MockTransport(handler)))
    assert out["status"] == "ok" and out["companies"] == 1 and out["period"] == "2026-06-30"
    assert ih.institutional_holders(db, "AAPL")["totals"]["shares"] == 1165


def test_no_cambia_el_limite_global_del_modulo_csv():
    """El parser 13F subía csv.field_size_limit al importarse y rompía el
    importador de CSV del usuario (que confía en el límite de 128 KB)."""
    import csv
    import importlib

    before = csv.field_size_limit()
    importlib.reload(ds)
    ds.parse_dataset(_datasets()[0], {APPLE}, url="https://www.sec.gov/files/x/q.zip")
    assert csv.field_size_limit() == before


def _datasets_sin_apple():
    """Q3 y Q4 de 2026: los gestores presentan 13F, pero ninguno tiene Apple."""
    q3 = _zip(
        ["Q3-A\t10-NOV-2026\t13F-HR\t1\t30-SEP-2026", "Q3-B\t11-NOV-2026\t13F-HR\t2\t30-SEP-2026"],
        ["Q3-A\t30-SEP-2026\t\t\t\tAlpha", "Q3-B\t30-SEP-2026\t\t\t\tBeta"],
        [_info("Q3-A", OTHER, 100), _info("Q3-B", OTHER, 50)],
    )
    q4 = _zip(
        ["Q4-A\t10-FEB-2027\t13F-HR\t1\t31-DEC-2026", "Q4-B\t11-FEB-2027\t13F-HR\t2\t31-DEC-2026"],
        ["Q4-A\t31-DEC-2026\t\t\t\tAlpha", "Q4-B\t31-DEC-2026\t\t\t\tBeta"],
        [_info("Q4-A", OTHER, 110), _info("Q4-B", OTHER, 40)],
    )
    return q4, q3


def test_ingesta_guarda_snapshot_vacio_sin_holders_en_ningun_periodo():
    """Bug auditado: si el CUSIP no aparece ni en el trimestre actual ni en el
    anterior no se guardaba nada, y la ficha servía el trimestre viejo como actual."""
    db = _db()
    cusips = ih.universe_cusips(db)
    assert ih.ingest_parsed(db, _parsed(), ["c2", "c1"], cusips)["companies"] == 1
    q4, q3 = _datasets_sin_apple()
    parses = [ds.parse_dataset(q4, set(cusips), url="https://www.sec.gov/files/x/01sep2026-30nov2026_form13f.zip"),
              ds.parse_dataset(q3, set(cusips), url="https://www.sec.gov/files/x/01jun2026-31aug2026_form13f.zip")]
    out = ih.ingest_parsed(db, parses, ["c4", "c3"], cusips)
    assert out["status"] == "ok" and out["companies"] == 1  # snapshot vacío persistido
    view = ih.institutional_holders(db, "AAPL")
    assert view["status"] == "ok" and view["period"] == "2026-12-31" and view["prior_period"] == "2026-09-30"
    assert view["totals"]["holders"] == 0 and view["totals"]["holders_prior"] == 0
    assert view["totals"]["shares"] == 0 and view["totals"]["shares_prior"] == 0
    assert view["top_holders"] == [] and view["buyers"] == [] and view["sellers"] == []


def test_job_reprocesa_cuando_el_universo_crece():
    """Bug auditado: bastaba UN documento del ZIP reciente para darlo por hecho;
    una empresa añadida al universo después se saltaba todo el trimestre."""
    html = ('<a href="/files/a/01mar2026-31may2026_form13f.zip">x</a><a href="/files/a/01jun2026-31aug2026_form13f.zip">y</a>')
    q2, q1 = _datasets()

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == ds.DATASETS_PAGE:
            return httpx.Response(200, text=html)
        return httpx.Response(200, content=(q2 if "jun2026" in url else q1).getvalue())

    db = _db()
    out = ih.refresh_institutional_holders(db, httpx.Client(transport=httpx.MockTransport(handler)))
    assert out["status"] == "ok" and out["companies"] == 1
    # MSFT entra en el universo DESPUÉS (su CUSIP, 594918104, sí está en los ZIP)
    db.add(Company(ticker="MSFT", name="Microsoft", exchange="NASDAQ", company_type="mature", valuation_model="dcf",
                   isin="US5949181045"))
    db.commit()
    again = ih.refresh_institutional_holders(db, httpx.Client(transport=httpx.MockTransport(handler)))
    assert again["status"] == "ok" and again["companies"] == 1  # solo MSFT; AAPL ya estaba
    view = ih.institutional_holders(db, "MSFT")
    assert view["status"] == "ok" and view["period"] == "2026-06-30" and view["totals"]["holders"] >= 1
    third = ih.refresh_institutional_holders(db, httpx.Client(transport=httpx.MockTransport(handler)))
    assert third["status"] == "sin_cambios"  # universo completo ya procesado


def test_ingesta_sin_13f_validos_no_persiste_ni_marca_procesado():
    """Todos los 13F ignorados (incompletos: 1 fila de 40 declaradas): N/D, no
    «0 gestores», y el fichero NO queda procesado (el reintento no se congela)."""
    db = _db()
    cusips = ih.universe_cusips(db)
    q2 = _zip(["I2\t15-AUG-2026\t13F-HR\t1\t30-JUN-2026"], ["I2\t30-JUN-2026\t\t\t\tAlpha"], [_info("I2", APPLE, 110)], ["I2\t0\t40"])
    q1 = _zip(["I1\t15-MAY-2026\t13F-HR\t1\t31-MAR-2026"], ["I1\t31-MAR-2026\t\t\t\tAlpha"], [_info("I1", APPLE, 100)], ["I1\t0\t40"])
    parses = [ds.parse_dataset(q2, set(cusips), url="https://www.sec.gov/files/x/q2.zip"),
              ds.parse_dataset(q1, set(cusips), url="https://www.sec.gov/files/x/q1.zip")]
    out = ih.ingest_parsed(db, parses, ["i2", "i1"], cusips)
    assert out["status"] == "sin_datos"
    assert db.query(PublicSourceDocument).count() == 0
    assert ih.institutional_holders(db, "AAPL")["status"] == "sin_datos"


def test_ingesta_actual_sin_13f_validos_no_persiste_aunque_el_previo_sea_valido():
    """ZIP actual con 1 fila de 40 declaradas (ningún 13F válido) + ZIP previo
    válido: N/D, no «no aparece en este fichero», y no queda marcado procesado."""
    db = _db()
    cusips = ih.universe_cusips(db)
    q2 = _zip(["I2\t15-AUG-2026\t13F-HR\t1\t30-JUN-2026"], ["I2\t30-JUN-2026\t\t\t\tAlpha"], [_info("I2", APPLE, 110)], ["I2\t0\t40"])
    q1 = _zip(["P1\t15-MAY-2026\t13F-HR\t1\t31-MAR-2026"], ["P1\t31-MAR-2026\t\t\t\tAlpha"], [_info("P1", OTHER, 100)], ["P1\t0\t1"])
    parses = [ds.parse_dataset(q2, set(cusips), url="https://www.sec.gov/files/x/q2.zip"),
              ds.parse_dataset(q1, set(cusips), url="https://www.sec.gov/files/x/q1.zip")]
    out = ih.ingest_parsed(db, parses, ["i2", "i1"], cusips)
    assert out["status"] == "sin_datos"
    assert db.query(PublicSourceDocument).count() == 0
    assert ih.institutional_holders(db, "AAPL")["status"] == "sin_datos"


def test_corregir_el_cusip_invalida_el_snapshot_y_se_recalcula():
    """Residual de #4843: corregir el CUSIP de una empresa ya procesada no
    invalidaba nada — la ficha servía las posiciones calculadas para el CUSIP
    anterior. Ahora el snapshot va ligado al CUSIP: la lectura solo sirve el
    calculado con el actual y re-ingerir los mismos ZIP crea un snapshot nuevo."""
    db = _db()
    cusips = ih.universe_cusips(db)
    assert set(cusips) == {APPLE}
    assert ih.ingest_parsed(db, _parsed(), ["c2", "c1"], cusips)["companies"] == 1
    # El CUSIP guardado resulta erróneo y se corrige al de Microsoft.
    db.query(Company).filter(Company.ticker == "AAPL").one().isin = "US5949181045"
    db.commit()
    assert set(ih.universe_cusips(db)) == {OTHER}
    # La lectura no sirve el snapshot del CUSIP anterior.
    assert ih.institutional_holders(db, "AAPL")["status"] == "sin_datos"
    # Re-ingerir los mismos ZIP crea un snapshot nuevo (no choca con el viejo).
    out = ih.ingest_parsed(db, _parsed_con({OTHER}), ["c2", "c1"], ih.universe_cusips(db))
    assert out["companies"] == 1
    assert db.query(PublicSourceDocument).count() == 2
    view = ih.institutional_holders(db, "AAPL")
    assert view["status"] == "ok" and view["cusip"] == OTHER and view["period"] == "2026-06-30"
    assert view["totals"]["shares"] == 10 and view["totals"]["shares_prior"] == 3


def test_documento_sin_cusip_grabado_sigue_sirviendo():
    """Documentos de antes de la vinculación (listing_key sin CUSIP) se siguen
    sirviendo tal cual: no se rompe lo ya guardado."""
    db = _db()
    ih.ingest_parsed(db, _parsed(), ["c2", "c1"], ih.universe_cusips(db))
    doc = db.query(PublicSourceDocument).one()
    doc.listing_key = "13f:2026-06-30"  # como quedó antes de la vinculación
    db.commit()
    view = ih.institutional_holders(db, "AAPL")
    assert view["status"] == "ok" and view["period"] == "2026-06-30" and view["totals"]["shares"] == 1165


def test_refresh_recalcula_si_el_snapshot_no_es_del_cusip_actual():
    """«Procesado» exige documento calculado con el CUSIP actual: un documento
    legado (sin CUSIP) o con otro CUSIP obliga a recalcular, así corregir la
    identidad de una empresa invalida su snapshot guardado."""
    html = ('<a href="/files/a/01mar2026-31may2026_form13f.zip">x</a><a href="/files/a/01jun2026-31aug2026_form13f.zip">y</a>')
    q2, q1 = _datasets()

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == ds.DATASETS_PAGE:
            return httpx.Response(200, text=html)
        return httpx.Response(200, content=(q2 if "jun2026" in url else q1).getvalue())

    for legacy_key in ("13f:2026-06-30", f"13f:2026-06-30:{OTHER}"):
        db = _db()
        db.add(PublicSourceDocument(company_id=1, listing_key=legacy_key, provider=ih.PROVIDER,
                                    source_url="https://www.sec.gov/files/a/01jun2026-31aug2026_form13f.zip",
                                    checksum="x", fetched_at=__import__("datetime").datetime(2026, 9, 1), official=True))
        db.commit()
        out = ih.refresh_institutional_holders(db, httpx.Client(transport=httpx.MockTransport(handler)))
        assert out["status"] == "ok" and out["companies"] == 1  # recalcula, no «sin_cambios»
        again = ih.refresh_institutional_holders(db, httpx.Client(transport=httpx.MockTransport(handler)))
        assert again["status"] == "sin_cambios"


def test_ingesta_previo_sin_13f_validos_no_persiste_aunque_el_actual_sea_valido():
    """Simétrico: ZIP previo sin 13F válidos + ZIP actual válido. Comparar con
    un trimestre vacío inventaría «nuevo»/«sin 13F previo» en todos: N/D."""
    db = _db()
    cusips = ih.universe_cusips(db)
    q2 = _zip(["P2\t15-AUG-2026\t13F-HR\t1\t30-JUN-2026"], ["P2\t30-JUN-2026\t\t\t\tAlpha"], [_info("P2", OTHER, 110)], ["P2\t0\t1"])
    q1 = _zip(["I1\t15-MAY-2026\t13F-HR\t1\t31-MAR-2026"], ["I1\t31-MAR-2026\t\t\t\tAlpha"], [_info("I1", APPLE, 100)], ["I1\t0\t40"])
    parses = [ds.parse_dataset(q2, set(cusips), url="https://www.sec.gov/files/x/q2.zip"),
              ds.parse_dataset(q1, set(cusips), url="https://www.sec.gov/files/x/q1.zip")]
    out = ih.ingest_parsed(db, parses, ["i2", "i1"], cusips)
    assert out["status"] == "sin_datos"
    assert db.query(PublicSourceDocument).count() == 0
    assert ih.institutional_holders(db, "AAPL")["status"] == "sin_datos"
