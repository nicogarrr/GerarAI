"""Huecos deterministas de valoración (carril fx-nav, 9-nov-2026).

(a) Tipos de cambio que faltan: la tesis de TSM se paraba en «sin tipo de cambio USD→TWD» porque nadie
    pedía el tipo de la divisa de reporte de una empresa que no está en la cartera ni en el seguimiento
    (o en una BD sembrada solo con la tabla del BCE). Ahora el job de tesis pide, antes de valorar, los
    tipos que falten de CUALQUIER divisa de la empresa al BCE o al banco central emisor; lo que siga sin
    tipo queda con su motivo.
(b) Holdings sin ingresos operativos: CGEO.L se paraba en «sin ingresos anuales». Ahora una holding o
    sociedad de inversión (por tipo de entidad o por la estructura del filing) se valora por su NAV
    (valor contable = NAV, P/VC = prima/descuento sobre el NAV), con el NAV de las cuentas depositadas
    (OCR de Companies House) cuando las hay, y la deuda probada por ese balance.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.models.entities import Base, Company, FinancialFact, FXRate, Portfolio
from app.services import fx_backfill
from app.services import shareholder_irr_service as svc
from app.services.connectors.ecb import ECBRates
from app.services.connectors.official_fx import CBC_DAILY_URL
from app.services.market_refresh_service import MarketRefreshService

DAY = date(2026, 11, 9)
CBC_HTML = """<table class="rwd-table"> <tr> <th>Date</th> <th>NTD/USD</th> </tr>
<tr> <td data-th="Date"><span>2026/11/06</span></td> <td data-th="NTD/USD"><span>32.768</span></td> </tr></table>"""


# ------------------------------------------------------------------------------- (a) tipos de cambio
class _ECBSinTwd:
    async def fetch(self, *, base_currency, quote_currencies):
        published = {"USD": Decimal("0.87"), "GBP": Decimal("1.14")}
        return ECBRates(rate_date=date(2026, 11, 6), rates={c: published[c] for c in quote_currencies if c in published})


def _fetcher(pages):
    async def fetch(url: str) -> str:
        for prefix, body in pages.items():
            if url.startswith(prefix):
                return body
        raise ValueError(f"sin pagina para {url}")

    return fetch


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as session:
        session.info["tenant_id"] = "tenant-test"
        session.add(Portfolio(name="Main", base_currency="EUR", is_default=True))
        for ticker, ccy, unit in (("TSM", "USD", "TWD"), ("XYZ", "USD", "ARS")):
            company = Company(ticker=ticker, name=ticker, exchange="X", currency=ccy, sector="S", industry="I",
                              company_type="operating", valuation_model="unassigned", special_sources=[],
                              special_risks=[], factor_tags=[])
            session.add(company)
            session.flush()
            session.add(FinancialFact(company_id=company.id, metric="revenue", value=Decimal("1"), unit=unit,
                                      period="2025-12-31:FY"))
        session.commit()
        yield session


def _service():
    return MarketRefreshService(fx_provider=_ECBSinTwd(), official_fx_fetcher=_fetcher({CBC_DAILY_URL: CBC_HTML}))


def _company(db, ticker):
    return db.scalar(select(Company).where(Company.ticker == ticker))


def test_tipo_que_falta_se_pide_y_la_conversion_de_la_tir_ya_funciona(db):
    from app.services.user_sotp_service import convert_amount

    tsm = _company(db, "TSM")
    assert fx_backfill.company_currencies(db, tsm) == {"USD", "TWD"}
    # antes: sin fila TWD, convert_amount → None y la TIR «sin tipo de cambio USD→TWD»
    assert convert_amount(db, 375.44, "USD", "TWD", DAY) is None
    out = fx_backfill.ensure_company_fx(db, tsm, as_of=DAY, refresh_service=_service())
    assert out["missing"] == [] and {w["currency"] for w in out["written"]} == {"USD", "TWD"}
    rows = {r.quote_currency: r for r in db.scalars(select(FXRate)).all()}
    assert rows["TWD"].source.startswith("CBC") and rows["USD"].source == "ECB"
    conv = convert_amount(db, 375.44, "USD", "TWD", DAY)
    assert conv is not None and conv[0] == pytest.approx(375.44 * 32.768, rel=1e-6)


def test_divisa_sin_fuente_queda_con_su_motivo_y_no_se_inventa(db):
    out = fx_backfill.ensure_company_fx(db, _company(db, "XYZ"), as_of=DAY, refresh_service=_service())
    assert [m["currency"] for m in out["missing"]] == ["ARS"]
    assert "BCE" in out["missing"][0]["reason"]
    assert "ARS" not in {r.quote_currency for r in db.scalars(select(FXRate)).all()}


def test_tipo_reciente_no_se_vuelve_a_pedir(db):
    tsm = _company(db, "TSM")
    fx_backfill.ensure_company_fx(db, tsm, as_of=DAY, refresh_service=_service())

    class _Boom:
        async def fetch(self, **kw):
            raise AssertionError("no debía pedir nada")

    again = fx_backfill.ensure_company_fx(db, tsm, as_of=DAY, refresh_service=MarketRefreshService(fx_provider=_Boom()))
    assert again == {"written": [], "missing": []}


def test_en_pruebas_sin_servicio_no_sale_a_la_red(db):
    assert fx_backfill.ensure_company_fx(db, _company(db, "TSM"), as_of=DAY)["skipped"].startswith("app_env=test")


# --------------------------------------------------------------------------------- (b) NAV de holdings
YEARS = [2023, 2024, 2025]


def _cite(v, year, metric, unit="GEL", source="YAHOO_FUNDAMENTALS"):
    return {"value": v, "unit": unit, "period": f"{year}-12-31:FY", "metric": metric, "source_type": source}


def _holding_annual():
    return {
        "total_equity": {y: _cite(v * 1e6, y, "total_equity") for y, v in zip(YEARS, (3378.5, 3609.0, 5194.5))},
        "net_income": {y: _cite(v * 1e6, y, "net_income") for y, v in zip(YEARS, (608.6, 362.3, 1892.6))},
        "shares_diluted": {y: _cite(v * 1e6, y, "shares_diluted", "shares") for y, v in zip(YEARS, (40.76, 38.96, 35.03))},
    }


OCR_READ = {
    "company_name": "GEORGIA CAPITAL PLC", "made_up_to": "2025-12-31",
    "document_url": "https://find-and-update.company-information.service.gov.uk/company/10852406/filing-history/x/document",
    "checks": {"balance": {"ok": True, "why": "activo 5198380 = pasivo 3853 + patrimonio 5194527"}},
    "figures": [{"metric": "net_assets", "label": "Total equity", "value": 5194527.0, "value_millions": 5194.527,
                 "currency": "GEL", "unit": "thousands of georgian lari", "scale": 1000, "period_end": "2025-12-31",
                 "page": 187, "line": "Total equity 5,194,527 3,609,013", "consolidated": False},
                {"metric": "cash", "value": 13495.0, "value_millions": 13.495, "currency": "GEL",
                 "period_end": "2025-12-31", "page": 187}],
}


def _holding(monkeypatch, *, company_type="holding_company", reads=(OCR_READ,), liabilities=3.853e6, assets=5198.38e6,
             annual=None):
    annual = annual or _holding_annual()
    point = {"cash_and_equivalents": _cite(13.495e6, 2025, "cash_and_equivalents")}
    monkeypatch.setattr(svc, "company_facts", lambda db, company: (annual, point))
    import app.services.scanned_accounts as sa
    import app.services.user_sotp_service as us

    monkeypatch.setattr(us, "_price", lambda db, company: (4585.0, "GBp", "2026-11-06"))
    monkeypatch.setattr(us, "convert_amount",
                        lambda db, amount, src, dst, as_of=None: (amount * 3.4764, f"{amount} {src} × 3,4764 {dst}/{src}"))
    monkeypatch.setattr(sa, "for_ticker", lambda ticker: list(reads))
    monkeypatch.setattr(svc, "_latest_fy_value", lambda db, company, metric, year: {
        "total_liabilities": liabilities, "total_assets": assets}.get(metric))
    company = SimpleNamespace(ticker="HOLD.L", currency="GBP", sector="Financial Services", industry="Unknown",
                              company_type=company_type, valuation_model="unassigned", factor_tags=[], special_risks=[],
                              sic_code=None)
    import app.valuation.engines.registry as reg

    monkeypatch.setattr(reg, "classification_engine_key",
                        lambda c: "holding_company" if c.company_type == "holding_company" else "standard_dcf")
    return svc.starting_point(None, company, today=DAY)  # type: ignore[arg-type]


def test_holding_sin_ingresos_se_valora_por_nav_del_filing(monkeypatch):
    # antes: ValueError «sin ingresos anuales» y CGEO.L sin TIR ni tesis
    sp, hist, warnings, cites = _holding(monkeypatch)
    assert cites["method"]["chosen"] == "tir_pb" and cites["method"]["kind"] == "holding"
    assert sp.basis == "pb" and sp.currency == "GEL"  # divisa de los informes, no la del listado
    assert sp.revenue == pytest.approx(5194.527)  # valor contable = NAV de las cuentas depositadas
    nav = cites["nav"]
    assert nav["nav_per_share"] == pytest.approx(5194.527 / 35.03)
    assert nav["source"]["source_type"] == "companies_house_ocr" and nav["source"]["page"] == 187
    assert nav["price"] == pytest.approx(45.85 * 3.4764)
    assert nav["discount"] == pytest.approx(45.85 * 3.4764 / (5194.527 / 35.03) - 1)
    assert nav["nav_per_share_listing"] == pytest.approx(5194.527 / 35.03 / 3.4764)
    # deuda 0 PROBADA por el balance cuadrado sin línea de préstamos, con su fuente; no supuesta
    assert sp.debt == 0.0 and cites["total_debt"]["source_type"] == "companies_house_ocr"
    assert any("se valora por su NAV" in w for w in warnings)
    assert hist.years == YEARS


def test_sin_ocr_el_nav_es_el_patrimonio_y_la_deuda_el_pasivo_como_cota(monkeypatch):
    sp, _hist, warnings, cites = _holding(monkeypatch, reads=())
    assert sp.revenue == pytest.approx(5194.5)
    assert cites["nav"]["source"]["metric"] == "total_equity"
    assert sp.debt == pytest.approx(3.853) and "cota superior" in cites["total_debt"]["formula"]
    assert any("todo el pasivo" in w for w in warnings)


def test_sin_deuda_ni_pasivo_sigue_siendo_nd(monkeypatch):
    with pytest.raises(ValueError, match="sin deuda"):
        _holding(monkeypatch, reads=(), liabilities=None)


def test_deteccion_por_estructura_del_filing_sin_clasificacion(monkeypatch):
    # sin ficha de holding: ningún ingreso, beneficio positivo y patrimonio ≥ 80 % del activo
    _sp, _h, _w, cites = _holding(monkeypatch, company_type="operating")
    assert cites["method"]["kind"] == "holding" and "sociedad de inversión" in cites["method"]["kind_reason"]


def test_sin_ingresos_y_con_deuda_alta_no_es_holding(monkeypatch):
    # patrimonio < 80 % del activo, pérdidas o ingresos operativos: la regla estructural no la convierte en holding
    company = SimpleNamespace(ticker="X")
    annual = _holding_annual()
    monkeypatch.setattr(svc, "_latest_fy_value", lambda db, c, metric, year: 12000e6)
    assert svc.investment_holding_reason(None, company, annual, "pre_revenue", "") is None  # type: ignore[arg-type]
    monkeypatch.setattr(svc, "_latest_fy_value", lambda db, c, metric, year: 5198.38e6)
    assert svc.investment_holding_reason(None, company, annual, "pre_revenue", "")  # type: ignore[arg-type]
    losses = {**annual, "net_income": {y: _cite(-50e6, y, "net_income") for y in YEARS}}
    assert svc.investment_holding_reason(None, company, losses, "pre_revenue", "") is None  # type: ignore[arg-type]
    operating = {**annual, "revenue": {2025: _cite(900e6, 2025, "revenue")}}
    assert svc.investment_holding_reason(None, company, operating, "holding", "ficha") is None  # type: ignore[arg-type]


def test_ocr_de_otro_ejercicio_o_divisa_no_se_usa(monkeypatch):
    other = {**OCR_READ, "figures": [{**OCR_READ["figures"][0], "period_end": "2024-12-31"}]}
    _sp, _h, _w, cites = _holding(monkeypatch, reads=(other,))
    assert cites["nav"]["source"]["metric"] == "total_equity"


def test_tesis_muestra_nav_por_accion_y_descuento(monkeypatch):
    from app.services.expert_team import thesis_v2 as T

    sp, hist, warnings, cites = _holding(monkeypatch)
    from dataclasses import asdict

    val = {"starting_point": {**asdict(sp), "market_cap": sp.market_cap, "net_debt": sp.net_debt,
                              "enterprise_value": sp.enterprise_value, "multiple": sp.multiple, "margin": sp.margin},
           "citations": cites, "method": cites["method"], "warnings": warnings, "status": "not_meaningful",
           "reason": "x", "as_of": DAY.isoformat()}
    ctx = T.ThesisContext("HOLD.L", "Holding", val, [], [], [], None, [])
    m = T.thesis_markers(ctx)
    assert m["punto.nav_accion"] != "N/D" and m["punto.nav_descuento"].endswith("%")
    assert "GBP" in m["punto.nav_accion_cotizacion"] or "£" in m["punto.nav_accion_cotizacion"]
    rows = {r[0]: r for r in T.tables(ctx)["partida"]["rows"]}
    assert "NAV por acción" in rows and rows["NAV por acción"][1] == m["punto.nav_accion"]
    assert "Prima (+) o descuento (−) sobre el NAV" in rows


def test_historial_de_la_holding_por_ejercicios_de_beneficio(monkeypatch):
    from app.services.expert_team import thesis_v2 as T

    _sp, _h, _w, cites = _holding(monkeypatch)
    points = {"total_equity": {y: v for y, v in zip(YEARS, (3378.5, 3609.0, 5194.5), strict=True)}}
    rows = T.history_rows(cites, "pb", points)
    # antes: sin línea de ingresos el historial salía vacío
    assert [r["year"] for r in rows] == YEARS
    assert rows[-1]["book"] == 5194.5 and rows[-1]["margin"] == pytest.approx(1892.6 / 5194.5)
