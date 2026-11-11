"""F353: el filtro anual SEC ya NO es una moda sobre hechos (envenenable con
ruido TTM, demostrado por el auditor en tres rondas: ruido antiguo en 1 y 2
concepts, y ruido RECIENTE dominante que ganaba la moda de ventana). La
admision anual es por ANCLA DE FILING: cada hecho de flujo anual (300-380
dias, fp=FY) solo entra si su `accn` resuelve a un filing anual (10-K y
variantes) en submissions Y cierra en el mismo mes que ese filing declara
en portada (reportDate). Un TTM dentro de un 10-K real falla el mes; una
serie TTM coherente no puede mover una fecha de portada.

Reglas fijas de la barra de aceptacion (auditor, 28/09/2026):
- AA/AAL y variantes multi-concept, antiguo o reciente: el TTM nunca entra.
- Sin DEI vinculable: fail closed (cobertura parcial visible, cero relleno).
- Cambio real de calendario (ZWS Mar->Dic, JEF Dic->Nov): el ultimo FY ancla
  en el vigente y un SEGUNDO refresh conserva los FY historicos validos de
  la era anterior con valores y procedencia intactos (replace selectivo por
  (metric, period): restatement machaca, lo no re-anclable se preserva).
- 52/53 semanas (VFC): los tres FY entran, el TTM trimestral queda fuera y
  Q1-Q4 no se desplazan (mes normalizado: dia <= 7 = mes anterior).
- Ni hechos de otra fuente ni de otro tenant se borran.
"""

import asyncio
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.entities import Base, Company, Document, FinancialFact
from app.services import financial_ingestion_service as ingestion
from app.services.financial_ingestion_service import (
    FinancialIngestionService,
    _current_fiscal_month_from_anchors,
    _normalized_fiscal_month,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _company(db, ticker):
    company = Company(
        ticker=ticker, name=ticker, exchange="NYSE", currency="USD",
        sector="S", industry="I", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def _accn(year):
    return f"0000000000-{str(year)[-2:]}-000001"


def _fy(start, end, val, filed, form="10-K", accn=None, fp="FY"):
    return {"fy": int(end[:4]), "fp": fp, "form": form, "start": start,
            "end": end, "val": val, "filed": filed, "accn": accn or _accn(end[:4])}


def _years(start_year, end_year, start_md, end_md, base_val):
    """Serie anual start_year..end_year con cierre end_md, cada ejercicio con
    el accn de su propio 10-K."""
    return [
        _fy(f"{y - 1}-{start_md}", f"{y}-{end_md}", base_val + y, f"{y + 1}-02-01")
        for y in range(start_year, end_year + 1)
    ]


def _years_cal(start_year, end_year, base_val):
    """Serie anual de ano natural: FY2023 = 2023-01-01 -> 2023-12-31."""
    return [
        _fy(f"{y}-01-01", f"{y}-12-31", base_val + y, f"{y + 1}-02-01")
        for y in range(start_year, end_year + 1)
    ]


def _anchors(pairs):
    """{accn: reportDate} - la evidencia de submissions."""
    return {accn: report for accn, report in pairs}


def _anchors_for_years(start_year, end_year, end_md):
    return _anchors([(_accn(y), f"{y}-{end_md}") for y in range(start_year, end_year + 1)])


class _FakeSEC:
    facts = None
    anchors: dict = {}

    async def cik_for_ticker(self, ticker, entity_name=None):
        return "0000000000"

    async def company_facts(self, cik):
        return self.facts

    async def annual_report_anchors(self, cik):
        return self.anchors


def _ingest(db, ticker, facts, anchors):
    cls = type("FakeSECInstance", (_FakeSEC,), {"facts": facts, "anchors": anchors})
    monkey = cls()
    ingestion.SECClient = lambda *a, **k: monkey
    company = _company(db, ticker)
    result = asyncio.run(FinancialIngestionService().refresh_from_sec(db=db, company=company))
    return company, result


def _fy_rows(db, company, metric="revenue"):
    rows = db.scalars(select(FinancialFact).where(
        FinancialFact.company_id == company.id,
        FinancialFact.metric == metric,
        FinancialFact.fiscal_quarter == "FY",
        FinancialFact.is_reported.is_(True),
    ).order_by(FinancialFact.period.desc())).all()
    return {r.period: r.value for r in rows}


def _all_fy_periods(db, company):
    return set(db.scalars(select(FinancialFact.period).where(
        FinancialFact.company_id == company.id,
        FinancialFact.fiscal_quarter == "FY",
        FinancialFact.is_reported.is_(True),
    )).all())


# --- Celda 1+2: AA/AAL original y ruido antiguo dominante (1 y 2 concepts) ---

def _ttm_rows(years, base_val):
    """2 acumulados TTM (~365d, cierre Mar) por ano, etiquetados FY dentro
    del 10-K del ejercicio natural de ese ano (accn valido, mes distinto)."""
    rows = []
    for y in years:
        rows.append(_fy(f"{y - 1}-04-01", f"{y}-03-31", base_val, f"{y + 1}-02-01", accn=_accn(y)))
        rows.append(_fy(f"{y - 1}-04-01", f"{y}-03-31", base_val - 1, f"{y + 1}-03-01", accn=_accn(y)))
    return rows


def test_aa_aal_ttm_dentro_del_10k_rechazado_1_concept(db):
    """14 FY reales Dic 2012-2025 + 2 TTM Mar/ano 2012-2019 (dominantes en la
    era antigua) con accn de 10-K real: el mes no casa con la portada, fuera."""
    rev = {"units": {"USD": _years_cal(2012, 2025, 100) + _ttm_rows(range(2012, 2020), 999)}}
    anchors = _anchors_for_years(2012, 2025, "12-31")
    company, _r = _ingest(db, "AA", {"facts": {"us-gaap": {"Revenues": rev}}}, anchors)
    periods = _fy_rows(db, company)
    assert periods["2025-12-31:FY"] == Decimal(str(100 + 2025))
    assert not any(p.endswith("-03-31:FY") for p in _all_fy_periods(db, company))


def test_ttm_antiguo_dominante_2_concepts(db):
    """La misma siembra en Revenues + OperatingIncomeLoss: tampoco entra."""
    facts = {"facts": {"us-gaap": {
        "Revenues": {"units": {"USD": _years_cal(2012, 2025, 100) + _ttm_rows(range(2012, 2020), 999)}},
        "OperatingIncomeLoss": {"units": {"USD": _years_cal(2012, 2025, 40) + _ttm_rows(range(2012, 2020), 888)}},
    }}}
    anchors = _anchors_for_years(2012, 2025, "12-31")
    company, _r = _ingest(db, "AAL", facts, anchors)
    assert "2025-12-31:FY" in _fy_rows(db, company)
    assert not any(p.endswith("-03-31:FY") for p in _all_fy_periods(db, company))


# --- Celda 3: ruido TTM RECIENTE dominante ---

def test_ttm_reciente_dominante_ancla_dei_obliga_dic(db):
    """El hueco del tercer bounce: 2 TTM Mar/ano 2020-2025 (12 filas en 2
    concepts = 24 contra 14 reales) ganaban cualquier moda. Con ancla DEI de
    10-K reciente, solo Dic entra; Mar nunca."""
    facts = {"facts": {"us-gaap": {
        "Revenues": {"units": {"USD": _years_cal(2012, 2025, 100) + _ttm_rows(range(2020, 2026), 999)}},
        "OperatingIncomeLoss": {"units": {"USD": _years_cal(2012, 2025, 40) + _ttm_rows(range(2020, 2026), 888)}},
    }}}
    anchors = _anchors_for_years(2012, 2025, "12-31")
    company, _r = _ingest(db, "POIS", facts, anchors)
    periods = _fy_rows(db, company)
    assert periods["2025-12-31:FY"] == Decimal(str(100 + 2025))
    assert not any(p.endswith("-03-31:FY") for p in _all_fy_periods(db, company))


def test_sin_dei_fail_closed_ningun_fy(db):
    """Sin submissions (o sin filings anuales vinculables): NINGUN hecho
    anual entra, y la cobertura queda visiblemente vacia en el resultado.
    Nunca se rellena con la moda contaminada."""
    rev = {"units": {"USD": _years_cal(2012, 2025, 100) + _ttm_rows(range(2020, 2026), 999)}}
    company, result = _ingest(db, "NODEI", {"facts": {"us-gaap": {"Revenues": rev}}}, {})
    assert _fy_rows(db, company) == {}
    assert result["fy_periods"] == []
    assert result["annual_anchored_filings"] == 0


def test_hecho_sin_accn_o_accn_desconocido_rechazado(db):
    """DEI aislado o no vinculable no autoriza: sin accn o con accn que no
    resuelve a un 10-K en submissions, el hecho queda fuera."""
    real = [_fy("2024-01-01", "2024-12-31", 500, "2025-02-01")]
    sin_accn = [{"fy": 2023, "fp": "FY", "form": "10-K", "start": "2023-01-01",
                 "end": "2023-12-31", "val": 400, "filed": "2024-02-01"}]
    accn_fantasma = [_fy("2022-01-01", "2022-12-31", 300, "2023-02-01", accn="9999999999-23-999999")]
    rev = {"units": {"USD": real + sin_accn + accn_fantasma}}
    anchors = _anchors([(_accn(2024), "2024-12-31")])
    company, _r = _ingest(db, "GHOST", {"facts": {"us-gaap": {"Revenues": rev}}}, anchors)
    assert _fy_rows(db, company) == {"2024-12-31:FY": Decimal("500")}


# --- Celda 4: cambio real de calendario + preservacion en re-import ---

def _zws_fixture():
    """ZWS: era Mar hasta 2020 (spinoff), calendario Dic desde 2021."""
    rev = {"units": {"USD":
        _years(2015, 2020, "04-01", "03-31", 1_800_000_000)
        + _years_cal(2021, 2025, 1_200_000_000)}}
    op = {"units": {"USD":
        _years(2015, 2020, "04-01", "03-31", 300_000_000)
        + _years_cal(2021, 2025, 200_000_000)}}
    anchors = _anchors(
        [(_accn(y), f"{y}-03-31") for y in range(2015, 2021)]
        + [(_accn(y), f"{y}-12-31") for y in range(2021, 2026)]
    )
    facts = {"facts": {"us-gaap": {"Revenues": rev, "OperatingIncomeLoss": op}}}
    return facts, anchors


def test_zws_cambio_calendario_ambas_eras_y_segundo_refresh_idempotente(db):
    """Ultimo FY ancla en el vigente (Dic); la era Mar entra anclada a SUS
    10-K; un segundo refresh del mismo documento deja valores y procedencia
    intactos, sin duplicar."""
    facts, anchors = _zws_fixture()
    company, result = _ingest(db, "ZWS", facts, anchors)
    periods = _fy_rows(db, company)
    assert max(periods) == "2025-12-31:FY"
    assert periods["2025-12-31:FY"] == Decimal(str(1_200_000_000 + 2025))
    assert periods["2020-03-31:FY"] == Decimal(str(1_800_000_000 + 2020))

    snapshot = sorted(
        (f.metric, f.period, str(f.value), f.source_id)
        for f in db.scalars(select(FinancialFact).where(
            FinancialFact.company_id == company.id)).all()
    )
    _ingest_second(db, company, facts, anchors)
    snapshot2 = sorted(
        (f.metric, f.period, str(f.value), f.source_id)
        for f in db.scalars(select(FinancialFact).where(
            FinancialFact.company_id == company.id)).all()
    )
    assert snapshot == snapshot2


def _ingest_second(db, company, facts, anchors):
    cls = type("FakeSECSecond", (_FakeSEC,), {"facts": facts, "anchors": anchors})
    monkey = cls()
    ingestion.SECClient = lambda *a, **k: monkey
    return asyncio.run(FinancialIngestionService().refresh_from_sec(db=db, company=company))


def test_zws_segundo_refresh_con_ventana_recortada_preserva_era_anterior(db):
    """Si submissions pierde los 10-K de la era Mar (ventana historica), el
    re-import NO borra los FY Mar validos ya verificados: replace selectivo,
    valores y procedencia intactos. Y sin aceptar TTM solapados como precio:
    un TTM Mar sembrado sigue fuera."""
    facts, anchors = _zws_fixture()
    # TTM Mar solapado con la era real Mar (mismo cierre, accn de 10-K Dic)
    facts["facts"]["us-gaap"]["Revenues"]["units"]["USD"].append(
        _fy("2018-04-01", "2019-03-31", 555, "2022-02-01", accn=_accn(2021))
    )
    company, _r = _ingest(db, "ZWS2", facts, anchors)
    antes = _fy_rows(db, company)
    assert "2019-03-31:FY" in antes  # era real Mar anclada a su 10-K de 2019
    assert antes["2019-03-31:FY"] == Decimal(str(1_800_000_000 + 2019))  # no el TTM

    anchors_recortados = _anchors(
        [(_accn(y), f"{y}-12-31") for y in range(2021, 2026)]
    )
    _ingest_second(db, company, facts, anchors_recortados)
    despues = _fy_rows(db, company)
    for periodo, valor in antes.items():
        assert despues[periodo] == valor, periodo


def test_jef_cambio_dic_a_nov(db):
    """JEF: historia Dic, calendario vigente Nov desde 2024."""
    rev = {"units": {"USD":
        _years_cal(2017, 2023, 5_000_000_000)
        + _years(2024, 2025, "12-01", "11-30", 7_000_000_000)}}
    anchors = _anchors(
        [(_accn(y), f"{y}-12-31") for y in range(2017, 2024)]
        + [(_accn(y), f"{y}-11-30") for y in range(2024, 2026)]
    )
    company, _r = _ingest(db, "JEF", {"facts": {"us-gaap": {"Revenues": rev}}}, anchors)
    periods = _fy_rows(db, company)
    assert max(periods) == "2025-11-30:FY"
    assert periods["2023-12-31:FY"] == Decimal(str(5_000_000_000 + 2023))
    _ingest_second(db, company, {"facts": {"us-gaap": {"Revenues": rev}}},
                   _anchors([(_accn(y), f"{y}-11-30") for y in range(2024, 2026)]))
    assert _fy_rows(db, company) == periods


def test_restatement_machaca_cifra_vieja(db):
    """El mismo periodo re-expresado (10-K/A, filed posterior): la cifra
    vieja NO se mantiene; queda una sola fila con el valor enmendado."""
    v1 = {"units": {"USD": [_fy("2024-01-01", "2024-12-31", 100, "2025-02-01")]}}
    anchors = _anchors([(_accn(2024), "2024-12-31"), (_accn(2025), "2024-12-31")])
    company, _r = _ingest(db, "REST", {"facts": {"us-gaap": {"Revenues": v1}}}, anchors)
    assert _fy_rows(db, company) == {"2024-12-31:FY": Decimal("100")}

    v2 = {"units": {"USD": [
        _fy("2024-01-01", "2024-12-31", 100, "2025-02-01"),
        _fy("2024-01-01", "2024-12-31", 110, "2025-06-01", form="10-K/A", accn=_accn(2025)),
    ]}}
    _ingest_second(db, company, {"facts": {"us-gaap": {"Revenues": v2}}}, anchors)
    rows = _fy_rows(db, company)
    assert rows == {"2024-12-31:FY": Decimal("110")}


def test_comparativas_del_mismo_10k_entran_sin_duplicar(db):
    """Un 10-K trae el ejercicio y 2 comparativas con el MISMO accn: mes
    igual, anos distintos - los tres FY entran y el periodo no se duplica."""
    accn = _accn(2025)
    rev = {"units": {"USD": [
        _fy("2025-01-01", "2025-12-31", 300, "2026-02-01", accn=accn),
        _fy("2024-01-01", "2024-12-31", 200, "2026-02-01", accn=accn),
        _fy("2023-01-01", "2023-12-31", 100, "2026-02-01", accn=accn),
    ]}}
    anchors = _anchors([(accn, "2025-12-31")])
    company, result = _ingest(db, "COMP", {"facts": {"us-gaap": {"Revenues": rev}}}, anchors)
    rows = _fy_rows(db, company)
    assert rows == {
        "2025-12-31:FY": Decimal("300"),
        "2024-12-31:FY": Decimal("200"),
        "2023-12-31:FY": Decimal("100"),
    }
    assert result["fy_periods"] == sorted(rows.keys(), reverse=True)


# --- Celda 5: 52/53 semanas ---

def test_vfc_52_53_semanas_tres_fy_y_trimestres_sin_desplazar(db):
    """VFC: cierres 2023-04-01 / 2024-03-30 / 2025-03-29 son el mismo mes
    fiscal (marzo). Los tres FY entran; un TTM etiquetado FY con cierre en
    otro mes queda fuera; Q1 (abr-jun) se etiqueta contra el cierre fiscal."""
    rev = {"units": {"USD": [
        _fy("2022-04-03", "2023-04-01", 11_000, "2023-05-25", accn=_accn(2023)),
        _fy("2023-04-02", "2024-03-30", 10_500, "2024-05-23", accn=_accn(2024)),
        _fy("2024-03-31", "2025-03-29", 10_000, "2025-05-22", accn=_accn(2025)),
        _fy("2024-01-01", "2024-12-28", 9_999, "2025-05-22", accn=_accn(2025)),
    ]}}
    q1 = {"units": {"USD": [
        {"fy": 2025, "fp": "Q1", "form": "10-Q", "start": "2024-03-31",
         "end": "2024-06-29", "val": 2_500, "filed": "2024-08-01", "accn": "0000000000-24-000101"},
    ]}}
    anchors = _anchors([
        (_accn(2023), "2023-04-01"), (_accn(2024), "2024-03-30"), (_accn(2025), "2025-03-29"),
    ])
    facts = {"facts": {"us-gaap": {"Revenues": rev, "RevenueFromContractWithCustomerExcludingAssessedTax": q1}}}
    company, _r = _ingest(db, "VFC", facts, anchors)
    periods = _fy_rows(db, company)
    assert set(periods) == {"2023-04-01:FY", "2024-03-30:FY", "2025-03-29:FY"}
    quarters = set(db.scalars(select(FinancialFact.period).where(
        FinancialFact.company_id == company.id,
        FinancialFact.metric == "revenue",
        FinancialFact.fiscal_quarter != "FY",
    )).all())
    assert "2024-06-29:Q1" in quarters


# --- Celda 6: replace selectivo, otras fuentes y tenants ---

def test_otras_fuentes_y_otros_tenants_intactos(db):
    """Un hecho FMP del mismo emisor y un hecho SEC de otro tenant sobreviven
    al refresh SEC."""
    company, _r = _ingest(db, "MULTI", {"facts": {"us-gaap": {
        "Revenues": {"units": {"USD": _years_cal(2023, 2025, 100)}},
    }}}, _anchors_for_years(2023, 2025, "12-31"))
    fmp_doc = Document(company_id=company.id, title="FMP normalized financials - MULTI",
                       source_type="FMP", source_url="x", metadata_={})
    db.add(fmp_doc)
    db.flush()
    db.add(FinancialFact(company_id=company.id, metric="revenue", value=Decimal("1"),
                         unit="USD", period="2025-12-31:FY", fiscal_year=2025,
                         fiscal_quarter="FY", source_id=fmp_doc.id, source_type="FMP",
                         is_reported=True, confidence=Decimal("0.9")))
    # Filas de otro tenant: se insertan con una sesion sin tenant scoping
    # (la sesion del test esta atada a tenant-test y el guard de escritura
    # cruzada las rechazaria).
    factory = sessionmaker(bind=db.get_bind())
    with factory() as s2:
        otro_doc = Document(company_id=company.id, title="SEC XBRL facts - MULTI (otro tenant)",
                            source_type="SEC", source_url="y", metadata_={}, tenant_id="otro-tenant")
        s2.add(otro_doc)
        s2.flush()
        s2.add(FinancialFact(company_id=company.id, metric="revenue", value=Decimal("2"),
                             unit="USD", period="2019-06-30:FY", fiscal_year=2019,
                             fiscal_quarter="FY", source_id=otro_doc.id, source_type="SEC",
                             is_reported=True, confidence=Decimal("0.9"), tenant_id="otro-tenant"))
        s2.commit()

    _ingest_second(db, company, {"facts": {"us-gaap": {
        "Revenues": {"units": {"USD": _years_cal(2023, 2025, 100)}},
    }}}, _anchors_for_years(2023, 2025, "12-31"))

    assert db.scalar(select(FinancialFact).where(FinancialFact.source_type == "FMP")) is not None
    with factory() as s3:
        assert s3.scalar(select(FinancialFact).where(
            FinancialFact.tenant_id == "otro-tenant")) is not None


def test_cobertura_parcial_visible_no_aparenta_diez_anos(db):
    """Solo 3 de 10 ejercicios son anclables: el resultado declara esos 3,
    no aparenta 10 anos de historia."""
    rev = {"units": {"USD": _years_cal(2016, 2025, 100)}}
    anchors = _anchors_for_years(2023, 2025, "12-31")
    company, result = _ingest(db, "PART", {"facts": {"us-gaap": {"Revenues": rev}}}, anchors)
    rows = _fy_rows(db, company)
    assert set(rows) == {"2023-12-31:FY", "2024-12-31:FY", "2025-12-31:FY"}
    assert result["fy_periods"] == sorted(rows.keys(), reverse=True)


# --- Helpers de mes ---

def test_mes_normalizado_drift_52_53():
    assert _normalized_fiscal_month("2023-04-01") == "03"
    assert _normalized_fiscal_month("2025-03-29") == "03"
    assert _normalized_fiscal_month("2026-01-02") == "12"
    assert _normalized_fiscal_month("2025-12-31") == "12"
    assert _normalized_fiscal_month("basura") is None


def test_mes_vigente_desde_anclas_recientes():
    anchors = {f"a{y}": f"{y}-12-31" for y in range(2021, 2026)}
    anchors["viejo"] = "2010-03-31"
    assert _current_fiscal_month_from_anchors(anchors) == "12"
    assert _current_fiscal_month_from_anchors({}) is None
    # Un solo 10-K reciente (caso JEF tras el cambio) basta para etiquetar.
    assert _current_fiscal_month_from_anchors({"a": "2025-11-30"}) == "11"


# --- Bounce 4: instantaneos tambien pasan la ancla ---

def _instant(end, val, filed, form="10-K", accn=None):
    """Hecho instantaneo (balance): sin start, fp FY."""
    return {"fy": int(end[:4]), "fp": "FY", "form": form, "end": end,
            "val": val, "filed": filed, "accn": accn or _accn(end[:4])}


def test_instantaneos_sin_ancla_fail_closed(db):
    """Assets con form 10-K, fp FY y accn ausente o desconocido NO entra,
    igual que un flow: sin DEI no hay NINGUNA fila anual y fy_periods es [].
    (Repro directo del bounce 4.)"""
    facts = {"facts": {"us-gaap": {
        "Assets": {"units": {"USD": [
            _instant("2025-03-31", 700, "2025-05-01", accn="unknown"),
            _instant("2025-12-31", 800, "2026-02-01"),
            {k: v for k, v in _instant("2024-12-31", 750, "2025-02-01").items() if k != "accn"},
        ]}},
        "Revenues": {"units": {"USD": _years_cal(2024, 2025, 100)}},
    }}}
    company, result = _ingest(db, "INST", facts, {})
    assert _fy_rows(db, company) == {}
    assert not db.scalars(select(FinancialFact).where(
        FinancialFact.company_id == company.id,
        FinancialFact.fiscal_quarter == "FY",
    )).first()
    assert result["fy_periods"] == []
    assert result["annual_anchored_filings"] == 0


def test_instantaneos_anclados_entran_y_comparativas(db):
    """Assets a cierre de ejercicio anclado a su 10-K entra; la comparativa
    del mismo filing tambien; un instantaneo a cierre de trimestre dentro
    del 10-K (mes distinto), no."""
    accn = _accn(2025)
    facts = {"facts": {"us-gaap": {
        "Assets": {"units": {"USD": [
            _instant("2025-12-31", 800, "2026-02-01", accn=accn),
            _instant("2024-12-31", 750, "2026-02-01", accn=accn),
            _instant("2025-09-30", 790, "2026-02-01", accn=accn),
        ]}},
    }}}
    company, result = _ingest(db, "INST2", facts, _anchors([(accn, "2025-12-31")]))
    assets = {f.period: f.value for f in db.scalars(select(FinancialFact).where(
        FinancialFact.company_id == company.id,
        FinancialFact.metric == "total_assets",
        FinancialFact.fiscal_quarter == "FY",
    ))}
    assert assets == {"2025-12-31:FY": Decimal("800"), "2024-12-31:FY": Decimal("750")}
    assert set(result["fy_periods"]) == set(assets)


# --- Bounce 5: cap alineado con replace y reporte ---

def test_mas_de_20_fy_cap_no_borra_ni_exagera(db):
    """25 ejercicios anclados: entran los 20 mas recientes; fy_periods
    declara exactamente esos 20 (no los 25); un FY viejo previamente
    verificado fuera del cap NO se borra en el segundo refresh."""
    rev = {"units": {"USD": _years_cal(2001, 2025, 100)}}
    anchors = _anchors_for_years(2001, 2025, "12-31")
    facts = {"facts": {"us-gaap": {"Revenues": rev}}}
    company, result = _ingest(db, "CAP", facts, anchors)
    periods = _fy_rows(db, company)
    assert len(periods) == 20
    assert max(periods) == "2025-12-31:FY"
    assert min(periods) == "2006-12-31:FY"
    assert result["fy_periods"] == sorted(periods.keys(), reverse=True)

    # Simula un FY2005 verificado en un import anterior con ventana mayor.
    doc = db.scalar(select(Document).where(
        Document.company_id == company.id, Document.source_type == "SEC"))
    db.add(FinancialFact(company_id=company.id, metric="revenue",
                         value=Decimal("105"), unit="USD",
                         period="2005-12-31:FY", fiscal_year=2005,
                         fiscal_quarter="FY", source_id=doc.id,
                         source_type="SEC", is_reported=True,
                         confidence=Decimal("0.95")))
    db.commit()
    _ingest_second(db, company, facts, anchors)
    despues = _fy_rows(db, company)
    assert despues["2005-12-31:FY"] == Decimal("105")  # fuera del cap: preservado
    assert len(despues) == 21


def test_anclas_efts_parciales_se_propagan_al_resultado_sin_tocar_valores(db):
    """F351: si las anclas vienen del fallback EFTS (parcial), el resultado de
    refresh_from_sec lo dice; los valores financieros son los mismos."""
    from app.services.connectors.sec import AnchorMap

    facts = {"facts": {"us-gaap": {
        "Revenues": {"units": {"USD": _years_cal(2020, 2025, 100)}},
    }}}
    plain = _anchors_for_years(2020, 2025, "12-31")
    company, base = _ingest(db, "ANCP", facts, plain)
    assert base["annual_anchor_partial"] is False
    assert base["annual_anchor_source"] == "sec-submissions"
    assert base["annual_anchor_note"] is None
    base_rows = _fy_rows(db, company)

    partial = AnchorMap(plain)
    partial.partial = True
    partial.source = "efts-full-text-search"
    result = _ingest_second(db, company, facts, partial)
    assert result["annual_anchor_partial"] is True
    assert result["annual_anchor_source"] == "efts-full-text-search"
    assert "parcial" in result["annual_anchor_note"]
    assert _fy_rows(db, company) == base_rows
