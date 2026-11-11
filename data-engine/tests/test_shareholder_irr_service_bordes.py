"""Bordes de app/services/shareholder_irr_service.py (zona levantada por Nico 9-nov-2026 18:43).

La suite existente cubre choose_method en el camino principal y el mapeo de adquisiciones. Aquí se
cubren los helpers puros, las rutas de decisión y las lecturas con dobles (sin red): los "modelos"
son SimpleNamespace de solo lectura, sin tenant_id ni company_id (regla gerarai-orm-fake-simplenamespace).

- _f/_cite/_share_cite/_end/_mill;
- choose_method (todas las ramas), _is_financial (SIC, palabras, sin pista);
- company_kind (clasificación de la ficha, primas, arrendamiento, < 50 M, quema dos años, operativa);
- _peer_multiples (servicio roto, comparable roto);
- _latest_fy_value, investment_holding_reason, nav_from_filing, nav_holding_debt (con scanned_accounts
  parcheado o ausente);
- runway (consumo, meses, dilución, N/D), guidance_growth, fingerprint;
- company_facts (segmentos y cuarentena fuera, mejor fuente, FY inválido, point por fecha);
- value_company (insufficient, caja_runway con preingresos roto, sotp, ok con CAPM roto, run_valuation roto);
- starting_point (sin ingresos, sin precio, sin tipo de cambio, subunidad GBp, sin acciones, sin caja,
  sin deuda).
"""

from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.services import shareholder_irr_service as svc
from app.valuation import shareholder_irr as engine
from app.valuation import shareholder_irr_rules as rules

TODAY = date(2026, 11, 9)
CO = SimpleNamespace(id=1, ticker="ASTS", industry="Satellite", currency="USD", exchange="NASDAQ")


class _Rows:
    def __init__(self, rows):
        self._rows = list(rows)

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None


class _DB:
    def __init__(self, queue=()):
        self._queue = list(queue)

    def scalars(self, _stmt):
        return _Rows(self._queue.pop(0))

    def execute(self, _stmt):
        # Etiquetas (period, fiscal_year) del emisor: sin filas, el desfase de etiqueta es 0.
        return _Rows([])


def _cite(metric, value, year=2025, unit="USD", source_type="sec", period=None):
    return {
        "metric": metric,
        "period": period or f"{year}-12-31:FY",
        "value": value,
        "unit": unit,
        "document": "10-K",
        "url": "u",
        "filed": "2026-02-01",
        "accession": None,
        "source_type": source_type,
    }


# --- helpers puros -------------------------------------------------------------


def test_f_cite_y_end():
    assert svc._f("x") is None and svc._f(None) is None and svc._f("1.5") == 1.5
    fact = SimpleNamespace(
        metric="revenue",
        period="2025-12-31:FY",
        value=Decimal("10"),
        unit="USD",
        source=None,
        source_url="http://x",
        filed=date(2026, 2, 1),
        source_type="sec",
    )
    cite = svc._cite(fact)
    assert cite["document"] is None and cite["url"] is None  # sin fuente: ni documento ni URL
    assert cite["filed"] == "2026-02-01" and cite["value"] == 10.0
    src = SimpleNamespace(title="10-K 2025")
    fact2 = SimpleNamespace(
        metric="revenue",
        period="2025-12-31:FY",
        value=Decimal("10"),
        unit="USD",
        source=src,
        source_url="http://x",
        filed=None,
        source_type="sec",
        accession_number="0001",
    )
    cite2 = svc._cite(fact2)
    assert cite2["document"] == "10-K 2025" and cite2["url"] == "http://x" and cite2["filed"] is None
    assert svc._end("2025-12-31:FY") == "2025-12-31" and svc._end(None) == ""
    assert (
        svc._mill({"value": 1_500_000}) == 1.5
        and svc._mill(None) is None
        and svc._mill({"value": "x"}) is None
    )


def test_share_cite_clases(monkeypatch):
    from app.valuation import current_shares as cs

    fact = SimpleNamespace(
        metric="shares_outstanding",
        period="2026-02-01",
        value=Decimal("5"),
        unit="shares",
        source=SimpleNamespace(title="10-K", metadata_={"m": 1}),
        source_url="u",
        filed=None,
        source_type="sec",
    )
    monkeypatch.setattr(cs, "is_class_sum", lambda meta, period: False)
    assert "class_sum" not in svc._share_cite(fact)
    monkeypatch.setattr(cs, "is_class_sum", lambda meta, period: True)
    monkeypatch.setattr(cs, "class_members", lambda meta, period: {"Class A": 5.0})
    out = svc._share_cite(fact)
    assert out["class_sum"] is True and out["class_members"] == {"Class A": 5.0}
    monkeypatch.setattr(cs, "class_members", lambda meta, period: None)
    out = svc._share_cite(fact)
    assert out["class_sum"] is True and "class_members" not in out
    # Sin fuente: meta None, no estalla:
    fact_sin = SimpleNamespace(
        metric="shares_outstanding",
        period="2026-02-01",
        value=Decimal("5"),
        unit="shares",
        source=None,
        source_url=None,
        filed=None,
        source_type="sec",
    )
    assert svc._share_cite(fact_sin)["metric"] == "shares_outstanding"


def test_choose_method_todas_las_ramas():
    m = svc.choose_method(
        revenue=None, ebitda_years=[1.0, 2.0], net_income=5.0, financial=False, segment_ebitda=False
    )
    assert m["chosen"] == "sotp" and "sin ingresos" in m["discarded"]["tir_ev_ebitda"]
    assert "sotp" not in m["discarded"]  # elegida: no se descarta a sí misma
    m = svc.choose_method(
        revenue=100.0, ebitda_years=[1.0, 2.0], net_income=5.0, financial=True, segment_ebitda=False
    )
    assert m["chosen"] == "tir_per" and "filiales" in m["discarded"]["tir_ev_ebitda"]
    m = svc.choose_method(
        revenue=100.0, ebitda_years=[1.0, 2.0, 3.0], net_income=5.0, financial=False, segment_ebitda=True
    )
    assert m["chosen"] == "tir_ev_ebitda" and "sumadas encima" in m["discarded"]["sotp"]
    m = svc.choose_method(
        revenue=100.0, ebitda_years=[None, -1.0], net_income=5.0, financial=False, segment_ebitda=False
    )
    assert (
        m["chosen"] == "tir_per" and "sin EBITDA positivo en al menos dos" in m["discarded"]["tir_ev_ebitda"]
    )
    m = svc.choose_method(
        revenue=100.0, ebitda_years=[None], net_income=None, financial=False, segment_ebitda=False
    )
    assert m["chosen"] == "sotp" and m["discarded"]["tir_per"] == "sin beneficio positivo"
    for m in (
        svc.choose_method(
            revenue=100.0, ebitda_years=[1.0, 2.0], net_income=1.0, financial=False, segment_ebitda=False
        ),
    ):
        assert "muy sensible" in m["discarded"]["dcf"]


def test_is_financial_ramas():
    assert svc._is_financial(SimpleNamespace(sic_code=6300, sector="", industry="", company_type="")) is True
    assert svc._is_financial(SimpleNamespace(sic=6021, sector="", industry="", company_type="")) is True
    assert (
        svc._is_financial(SimpleNamespace(sic_code=7370, sector="Health Care", industry="", company_type=""))
        is False
    )
    assert svc._is_financial(SimpleNamespace(sector="", industry="Banca", company_type="")) is True
    assert (
        svc._is_financial(SimpleNamespace(sector="Tech", industry="Software", company_type="operating"))
        is False
    )


# --- company_kind ----------------------------------------------------------------


def _kind(monkeypatch, key, annual=None, company=None):
    from app.valuation.engines import registry

    monkeypatch.setattr(registry, "classification_engine_key", lambda c: key)
    return svc.company_kind(company or CO, annual or {})


def test_company_kind_por_ficha(monkeypatch):
    assert _kind(monkeypatch, "insurer")[0] == "insurer"
    assert "banco" in _kind(monkeypatch, "bank")[1]
    assert _kind(monkeypatch, "holding_company")[0] == "holding"
    assert _kind(monkeypatch, "reit")[0] == "real_estate"
    # pre_revenue por la ficha (con ingresos >= 50 M la razón es la ficha, no el importe):
    con_ingresos = {"revenue": {2025: _cite("revenue", 900e6)}}
    assert (
        _kind(monkeypatch, "pre_revenue", con_ingresos)[1] == "preingresos según la clasificación de la ficha"
    )


def test_company_kind_registro_roto_cae_a_hechos(monkeypatch):
    from app.valuation.engines import registry

    def roto(c):
        raise RuntimeError("sin registro")

    monkeypatch.setattr(registry, "classification_engine_key", roto)
    kind, _ = svc.company_kind(CO, {"revenue": {2025: _cite("revenue", 900e6)}})
    assert kind == "operating"


def test_company_kind_primas_y_arrendamiento(monkeypatch):
    annual = {
        "revenue": {2025: _cite("revenue", 100e6)},
        "earned_premiums": {2025: _cite("earned_premiums", 60e6)},
    }
    kind, why = _kind(monkeypatch, "standard_dcf", annual, SimpleNamespace(ticker="X", industry="Unknown"))
    assert kind == "insurer" and "60%" in why
    # industria conocida no aseguradora: no se reclasifica
    kind, _ = _kind(monkeypatch, "standard_dcf", annual, SimpleNamespace(ticker="X", industry="Health Care"))
    assert kind != "insurer"
    annual = {"revenue": {2025: _cite("revenue", 100e6)}, "lease_income": {2025: _cite("lease_income", 80e6)}}
    kind, why = _kind(monkeypatch, "standard_dcf", annual, SimpleNamespace(ticker="X", industry="Unknown"))
    assert kind == "real_estate"


def test_company_kind_preingresos_por_ingresos_y_quema(monkeypatch):
    annual = {"revenue": {2025: _cite("revenue", 10e6)}}  # < 50 M
    kind, why = _kind(monkeypatch, "standard_dcf", annual)
    assert kind == "pre_revenue" and "por debajo de 50 M" in why
    burning = {
        "revenue": {2024: _cite("revenue", 900e6, 2024), 2025: _cite("revenue", 900e6)},
        "net_income": {2024: _cite("net_income", -5e6, 2024), 2025: _cite("net_income", -5e6)},
        "ebitda": {2024: _cite("ebitda", -1e6, 2024), 2025: _cite("ebitda", -1e6)},
        "operating_cash_flow": {
            2024: _cite("operating_cash_flow", -2e6, 2024),
            2025: _cite("operating_cash_flow", -2e6),
        },
        "capital_expenditure": {
            2024: _cite("capital_expenditure", 1e6, 2024),
            2025: _cite("capital_expenditure", 1e6),
        },
    }
    kind, why = _kind(monkeypatch, "standard_dcf", burning)
    assert kind == "pre_revenue" and "quema caja" in why
    # Un solo año quemando no basta:
    un_ano = {k: {2025: v[2025]} for k, v in burning.items()}
    assert _kind(monkeypatch, "standard_dcf", un_ano)[0] == "operating"


# --- comparables y lecturas pequeñas ----------------------------------------------


def test_peer_multiples_roto_y_comparable_roto(monkeypatch):
    from app.services.peer_comparison_service import PeerComparisonService

    def roto(self, db, company, n):
        raise RuntimeError("sin comparables")

    monkeypatch.setattr(PeerComparisonService, "_find_peers", roto)
    assert svc._peer_multiples(_DB(), CO, "ev_ebitda", TODAY) == []

    monkeypatch.setattr(
        PeerComparisonService,
        "_find_peers",
        lambda self, db, company, n: ([SimpleNamespace(ticker="P1", name="Peer")], "sector", {}),
    )
    monkeypatch.setattr(
        svc, "starting_point", lambda db, peer, today, basis: (_ for _ in ()).throw(ValueError("x"))
    )
    out = svc._peer_multiples(_DB(), CO, "ev_ebitda", TODAY)
    assert out == [{"ticker": "P1", "name": "Peer", "selection": "sector", "multiple": None}]


def test_latest_fy_value():
    fact = SimpleNamespace(value=Decimal("42"))
    assert svc._latest_fy_value(_DB([[fact]]), CO, "total_assets", 2025) == 42.0
    assert svc._latest_fy_value(_DB([[]]), CO, "total_assets", 2025) is None
    assert svc._latest_fy_value(_DB([[SimpleNamespace(value=None)]]), CO, "total_assets", 2025) is None


def test_investment_holding_reason_ramas():
    annual_con_ingresos = {"revenue": {2025: _cite("revenue", 1e6)}}
    assert svc.investment_holding_reason(_DB(), CO, annual_con_ingresos, "operating", "") is None
    assert svc.investment_holding_reason(_DB(), CO, {}, "operating", "") is None  # sin ejercicios
    annual = {
        "total_equity": {2025: _cite("total_equity", 900e6)},
        "net_income": {2025: _cite("net_income", 50e6)},
    }
    out = svc.investment_holding_reason(_DB(), CO, annual, "holding", "holding por la ficha")
    assert out.startswith("holding por la ficha; sin ingresos operativos")
    # Sin total_assets: None
    assert svc.investment_holding_reason(_DB([[]]), CO, annual, "operating", "") is None
    # Patrimonio < 80% del activo: None
    db = _DB([[SimpleNamespace(value=Decimal("2_000_000_000".replace("_", "")))]])
    assert svc.investment_holding_reason(db, CO, annual, "operating", "") is None
    # Balance de sociedad de inversión:
    db = _DB([[SimpleNamespace(value=Decimal("1_000_000_000".replace("_", "")))]])
    out = svc.investment_holding_reason(db, CO, annual, "operating", "")
    assert "sociedad de inversión" in out and "90%" in out


def test_nav_from_filing_ramas(monkeypatch):
    import app.services.scanned_accounts as sa

    monkeypatch.setattr(sa, "for_ticker", lambda ticker: [])
    assert svc.nav_from_filing(CO, 2025, "GBP", None, []) is None
    reads = [
        {
            "company_name": "Holding PLC",
            "document_url": "http://doc",
            "made_up_to": "2025-12-31",
            "figures": [
                {
                    "metric": "net_assets",
                    "value_millions": 100.0,
                    "period_end": "2025-12-31",
                    "currency": "GBP",
                    "page": 3,
                    "consolidated": True,
                },
                {
                    "metric": "net_assets",
                    "value_millions": 90.0,
                    "period_end": "2025-12-31",
                    "currency": "GBP",
                    "page": 5,
                    "consolidated": False,
                },  # matriz: gana
                {
                    "metric": "net_assets",
                    "value_millions": 50.0,
                    "period_end": "2024-12-31",
                    "currency": "GBP",
                    "page": 1,
                    "consolidated": False,
                },  # otro año: fuera
                {
                    "metric": "borrowings",
                    "value_millions": 1.0,
                    "period_end": "2025-12-31",
                    "currency": "GBP",
                },
                {
                    "metric": "net_assets",
                    "value_millions": 80.0,
                    "period_end": "2025-12-31",
                    "currency": "USD",
                },
            ],
        },
    ]
    monkeypatch.setattr(sa, "for_ticker", lambda ticker: reads)
    monkeypatch.setattr(sa, "page_url", lambda doc, page: f"{doc}#p{page}")
    warnings = []
    out = svc.nav_from_filing(CO, 2025, "GBP", 90.5, warnings)  # difiere < 1 %: sin aviso
    assert out["value_millions"] == 90.0 and out["url"] == "http://doc#p5" and warnings == []
    warnings = []
    out = svc.nav_from_filing(CO, 2025, "GBP", 50.0, warnings)  # difiere > 1 %: avisa y manda el filing
    assert out["value_millions"] == 90.0 and "manda el filing" in warnings[0]


def test_nav_holding_debt_ramas(monkeypatch):
    import app.services.scanned_accounts as sa

    # Balance cuadrado sin préstamos: deuda 0 probada:
    reads = [
        {
            "company_name": "Holding PLC",
            "document_url": "http://doc",
            "checks": {"balance": {"ok": True, "why": "activo = pasivo + patrimonio"}},
            "figures": [
                {
                    "metric": "net_assets",
                    "value_millions": 90.0,
                    "period_end": "2025-12-31",
                    "currency": "GBP",
                    "page": 5,
                }
            ],
        }
    ]
    monkeypatch.setattr(sa, "for_ticker", lambda ticker: reads)
    monkeypatch.setattr(sa, "page_url", lambda doc, page: f"{doc}#p{page}")
    debt, cite = svc.nav_holding_debt(_DB(), CO, 2025, [])
    assert debt == 0.0 and "deuda financiera 0" in cite["formula"]
    # Con préstamos en las cuentas: se salta el filing y se usa el pasivo total como cota:
    reads[0]["figures"].append({"metric": "borrowings", "value_millions": 4.0})
    warnings = []
    db = _DB([[SimpleNamespace(value=Decimal("10_000_000".replace("_", "")))]])
    debt, cite = svc.nav_holding_debt(db, CO, 2025, warnings)
    assert debt == 10.0 and "cota superior" in cite["formula"] and "cota superior" in warnings[0]
    # Sin nada: (None, None)
    monkeypatch.setattr(sa, "for_ticker", lambda ticker: [])
    assert svc.nav_holding_debt(_DB([[]]), CO, 2025, []) == (None, None)


def test_runway_ramas():
    sp = engine.StartingPoint(price=1.0, shares_diluted=100.0, revenue=0.0, ebitda=None, cash=60.0, debt=5.0)
    hist = rules.History(
        years=[2024, 2025],
        revenue=[0.0, 0.0],
        earnings=[-10.0, -10.0],
        operating_cash_flow=[-20.0, -30.0],
        capex=[6.0, 6.0],
    )
    cites = {
        "annual": {
            "shares_diluted": {
                "2023": _cite("shares_diluted", 80e6, 2023),
                "2024": _cite("shares_diluted", 90e6, 2024),
                "2025": _cite("shares_diluted", 100e6),
            }
        }
    }
    out = svc.runway(sp, hist, cites)
    assert out["burn"] == 36.0 and out["months"] == pytest.approx(60.0 / 36.0 * 12.0)
    assert out["dilution_cagr"] == pytest.approx((100.0 / 80.0) ** 0.5 - 1)
    assert out["missing"] is None and out["ev_to_cash"] is not None and out["ev_to_revenue"] is None
    # Sin flujo operativo: N/D con motivo
    hist_nd = rules.History(
        years=[2025], revenue=[0.0], earnings=[-1.0], operating_cash_flow=[None], capex=[1.0]
    )
    out = svc.runway(sp, hist_nd, {"annual": {}})
    assert out["burn"] is None and out["months"] is None and out["missing"] == "sin flujo de caja operativo"
    # Genera caja: consumo 0 → meses None (no se agota)
    hist_gen = rules.History(
        years=[2025], revenue=[0.0], earnings=[1.0], operating_cash_flow=[10.0], capex=[1.0]
    )
    out = svc.runway(sp, hist_gen, {"annual": {}})
    assert out["burn"] == 0.0 and out["months"] is None
    # Caja 0: ev_to_cash None
    sp0 = engine.StartingPoint(price=1.0, shares_diluted=1.0, revenue=0.0, ebitda=None, cash=0.0, debt=0.0)
    assert svc.runway(sp0, hist, cites)["ev_to_cash"] is None


def test_guidance_growth_ramas():
    assert svc.guidance_growth(_DB(), CO, 2025, None) == (None, None)
    assert svc.guidance_growth(_DB([[]]), CO, 2025, 100.0) == (None, None)  # sin fila
    row = SimpleNamespace(
        input_key="guidance.revenue.fy2026",
        base=None,
        low=None,
        high=None,
        source_url="u",
        source_quote="q",
        as_of=None,
    )
    assert svc.guidance_growth(_DB([[row]]), CO, 2025, 100.0) == (None, None)  # base None
    row = SimpleNamespace(
        input_key="guidance.revenue.fy2026",
        base=Decimal("300_000_000".replace("_", "")),
        low=None,
        high=None,
        source_url="u",
        source_quote="q",
        as_of=None,
    )
    assert svc.guidance_growth(_DB([[row]]), CO, 2025, 100.0) == (None, None)  # +200 %: fuera de rango
    row = SimpleNamespace(
        input_key="guidance.revenue.fy2026",
        base=Decimal("110_000_000".replace("_", "")),
        low=Decimal("108e6"),
        high=Decimal("112e6"),
        source_url="u",
        source_quote="q",
        as_of=datetime(2026, 10, 1, tzinfo=UTC),
    )
    growth, cite = svc.guidance_growth(_DB([[row]]), CO, 2025, 100.0)
    assert (
        growth == pytest.approx(0.10, rel=1e-9)
        and cite["as_of"] == "2026-10-01T00:00:00+00:00"
        and cite["low"] == 108e6
    )


def test_fingerprint_determinista():
    sp = engine.StartingPoint(price=1.0, shares_diluted=1.0, revenue=1.0, ebitda=1.0)
    hist = rules.History(years=[2025], revenue=[1.0], earnings=[1.0])
    assert svc.fingerprint(sp, hist, [], None) == svc.fingerprint(sp, hist, [], None)
    assert svc.fingerprint(sp, hist, [], None) != svc.fingerprint(sp, hist, [], 0.1)


# --- company_facts ------------------------------------------------------------


def _fact_row(
    metric,
    value,
    year=2025,
    *,
    source_type="SEC",
    unit="USD",
    period=None,
    source=None,
    created_at=None,
    quarter=None,
):
    return SimpleNamespace(
        metric=metric,
        value=value,
        unit=unit,
        period=period or f"{year}-12-31:{quarter or 'FY'}",
        source=source,
        source_url="u",
        filed=None,
        source_type=source_type,
        accession_number=None,
        created_at=created_at,
    )


def _facts_seam(monkeypatch, rows):
    """Los hechos llegan por ``_read_fact_rows`` (columnas sueltas, r5-perf2); la reducción es la misma."""
    monkeypatch.setattr(svc, "_read_fact_rows", lambda db, ids: {i: list(rows) for i in ids})


def test_company_facts_ramas(monkeypatch):
    seg = SimpleNamespace(metadata_={"segment": "Iberia"})
    rows = [
        _fact_row("revenue", 900e6, source_type="FMP"),  # peor fuente: la gana la SEC
        _fact_row("revenue", 800e6, source_type="SEC"),
        _fact_row("revenue", 1e9, period="abc-12-31:FY"),  # año inválido: fuera
        _fact_row("revenue", None),  # sin valor: fuera
        _fact_row("revenue", 700e6, source=seg),  # segmento: fuera
        _fact_row("revenue", 600e6, quarter="Q3"),  # trimestre: no es anual
        _fact_row("net_income", 50e6),
        _fact_row("total_equity", 400e6),  # POINT_ANNUAL: anual y point
        _fact_row("total_debt", 300e6, period="2025-06-30:Q2"),  # point: el más reciente gana
        _fact_row("total_debt", 280e6, period="2025-12-31:FY"),
        _fact_row("shares_outstanding", 100e6, period="2026-02-01"),
    ]
    _facts_seam(monkeypatch, rows)
    annual, point = svc.company_facts(_DB(), CO)
    assert annual["revenue"][2025]["value"] == 800e6  # SEC (prio 0) gana a FMP (10)
    assert annual["net_income"][2025]["value"] == 50e6
    assert annual["total_equity"][2025]["value"] == 400e6  # saldo anotado por ejercicio
    assert point["total_equity"]["value"] == 400e6
    assert point["total_debt"]["value"] == 280e6  # el cierre más reciente
    assert point["shares_outstanding"]["value"] == 100e6  # pasa por _share_cite sin fuente
    assert "shares_outstanding" not in annual


def test_company_facts_empate_fecha_gana_mejor_fuente(monkeypatch):
    rows = [
        _fact_row("total_debt", 300e6, source_type="FMP", period="2025-12-31:FY"),
        _fact_row("total_debt", 280e6, source_type="SEC", period="2025-12-31:FY"),
    ]
    _facts_seam(monkeypatch, rows)
    _, point = svc.company_facts(_DB(), CO)
    assert point["total_debt"]["value"] == 280e6


# --- value_company ---------------------------------------------------------------


def _sp_pe():
    return engine.StartingPoint(
        price=10.0,
        shares_diluted=100.0,
        revenue=500.0,
        ebitda=50.0,
        net_income=30.0,
        cash=10.0,
        debt=20.0,
        currency="USD",
        basis="pe",
    )


def _hist():
    return rules.History(
        years=[2025], revenue=[500.0], earnings=[30.0], operating_cash_flow=[40.0], capex=[5.0]
    )


def _cites(chosen, kind_reason="razón"):
    return {
        "method": {
            "chosen": chosen,
            "kind": "operating",
            "kind_reason": kind_reason,
            "kind_method": "m",
            "discarded": {},
        },
        "annual": {"revenue": {"2025": _cite("revenue", 500e6)}},
    }


def test_value_company_insufficient(monkeypatch):
    def roto(db, company, *, today):
        raise ValueError("sin precio")

    monkeypatch.setattr(svc, "starting_point", roto)
    out = svc.value_company(_DB(), CO, today=TODAY)
    assert out == {"status": "insufficient", "reason": "sin precio", "ticker": "ASTS"}


def test_value_company_sotp_not_applicable(monkeypatch):
    monkeypatch.setattr(
        svc, "starting_point", lambda db, company, *, today: (_sp_pe(), _hist(), ["w"], _cites("sotp"))
    )
    out = svc.value_company(_DB(), CO, today=TODAY)
    assert (
        out["status"] == "not_applicable" and out["warnings"] == ["w"] and out["method"]["chosen"] == "sotp"
    )


def test_value_company_caja_runway_con_preingresos_roto(monkeypatch):
    monkeypatch.setattr(
        svc,
        "starting_point",
        lambda db, company, *, today: (_sp_pe(), _hist(), ["w"], _cites("caja_runway", "quema")),
    )
    from app.services import pre_revenue_valuation as prv

    def roto(db, company, **kw):
        raise RuntimeError("ruta de preingresos rota")

    monkeypatch.setattr(prv, "value_pre_revenue", roto)
    out = svc.value_company(_DB(), CO, today=TODAY)
    assert out["status"] == "not_meaningful" and "quema" in out["reason"]
    assert out["pre_revenue"]["error"].startswith("RuntimeError") and out["runway"]["year"] == "2025"
    assert out["fingerprint"] and out["peers"] == []


def test_value_company_caja_runway_ok(monkeypatch):
    monkeypatch.setattr(
        svc, "starting_point", lambda db, company, *, today: (_sp_pe(), _hist(), [], _cites("caja_runway"))
    )
    from app.services import pre_revenue_valuation as prv

    monkeypatch.setattr(
        prv,
        "value_pre_revenue",
        lambda db, company, **kw: {
            "peers": [{"ticker": "P", "name": "N", "multiple": 3.0}],
            "peer_layer": "sic",
        },
    )
    out = svc.value_company(_DB(), CO, today=TODAY)
    assert out["peers"] == [
        {"ticker": "P", "name": "N", "selection": "sic", "multiple": 3.0, "multiple_basis": "ev_sales"}
    ]


def test_value_company_ok_y_run_valuation_roto(monkeypatch):
    monkeypatch.setattr(
        svc,
        "starting_point",
        lambda db, company, *, today: (_sp_pe(), _hist(), ["w1"], _cites("tir_ev_ebitda")),
    )
    monkeypatch.setattr(
        svc,
        "_peer_multiples",
        lambda db, c, basis, today: [{"ticker": "P", "name": "N", "selection": "s", "multiple": 9.0}],
    )
    monkeypatch.setattr(svc, "guidance_growth", lambda db, c, y, rev: (0.05, {"input_key": "g"}))
    from app.services.expert_team import sotp_valuer as sotpv

    monkeypatch.setattr(sotpv, "_capm_cost_of_equity", lambda db, c: (0.09, "CAPM guardado"))
    monkeypatch.setattr(
        svc, "run_valuation", lambda sp, hist, **kw: {"warnings": ["w2"], "base_irr_10": 0.12}
    )
    out = svc.value_company(_DB(), CO, today=TODAY)
    assert out["status"] == "ok" and out["discount_rate_source"] == "CAPM guardado"
    assert out["warnings"] == ["w1", "w2"] and out["guidance_growth"] == 0.05 and out["fingerprint"]
    assert out["peers"][0]["multiple"] == 9.0 and out["citations"]["guidance"] == {"input_key": "g"}

    def roto(sp, hist, **kw):
        raise ValueError("escenarios sin sentido")

    monkeypatch.setattr(svc, "run_valuation", roto)
    out = svc.value_company(_DB(), CO, today=TODAY)
    assert out["status"] == "not_meaningful" and out["reason"] == "escenarios sin sentido"
    assert out["starting_point"]["market_cap"] == 1000.0


def test_value_company_capm_roto_sigue_sin_tasa(monkeypatch):
    monkeypatch.setattr(
        svc, "starting_point", lambda db, company, *, today: (_sp_pe(), _hist(), [], _cites("tir_ev_ebitda"))
    )
    monkeypatch.setattr(svc, "_peer_multiples", lambda db, c, basis, today: [])
    monkeypatch.setattr(svc, "guidance_growth", lambda db, c, y, rev: (None, None))
    from app.services.expert_team import sotp_valuer as sotpv

    def roto(db, c):
        raise RuntimeError("sin CAPM")

    monkeypatch.setattr(sotpv, "_capm_cost_of_equity", roto)
    monkeypatch.setattr(svc, "run_valuation", lambda sp, hist, **kw: {"warnings": [], "base_irr_10": 0.1})
    out = svc.value_company(_DB(), CO, today=TODAY)
    assert out["status"] == "ok" and out["discount_rate_source"] is None


# --- starting_point: errores y camino feliz ----------------------------------------


def _annual_operativa():
    return {
        "revenue": {2024: _cite("revenue", 800e6, 2024), 2025: _cite("revenue", 900e6)},
        "net_income": {2024: _cite("net_income", 40e6, 2024), 2025: _cite("net_income", 50e6)},
        "shares_diluted": {2025: _cite("shares_diluted", 100e6, unit="shares")},
    }


def _point_basico():
    return {
        "cash_and_equivalents": _cite("cash_and_equivalents", 50e6, period="2025-12-31:FY"),
        "total_debt": _cite("total_debt", 30e6, period="2025-12-31:FY"),
    }


def _patch_base(monkeypatch, annual, point, price=(10.0, "USD", "2026-11-08")):
    monkeypatch.setattr(svc, "company_facts", lambda db, c: (annual, point))
    from app.services import user_sotp_service as sotp

    monkeypatch.setattr(sotp, "_price", lambda db, c: price)
    monkeypatch.setattr(sotp, "convert_amount", lambda db, v, u, cc, t: (v, "par guardado"))


def test_starting_point_sin_ingresos(monkeypatch):
    _patch_base(monkeypatch, {}, {})
    with pytest.raises(ValueError, match="sin ingresos anuales"):
        svc.starting_point(_DB(), CO, today=TODAY)


def test_starting_point_sin_precio(monkeypatch):
    _patch_base(monkeypatch, _annual_operativa(), _point_basico(), price=(None, None, None))
    with pytest.raises(ValueError, match="sin precio"):
        svc.starting_point(_DB(), CO, today=TODAY)


def test_starting_point_sin_tipo_de_cambio(monkeypatch):
    _patch_base(monkeypatch, _annual_operativa(), _point_basico(), price=(9500.0, "GBp", "2026-11-08"))
    from app.services import user_sotp_service as sotp

    monkeypatch.setattr(sotp, "convert_amount", lambda db, v, u, cc, t: None)
    with pytest.raises(ValueError, match="sin tipo de cambio"):
        svc.starting_point(_DB(), CO, today=TODAY)


def test_starting_point_sin_acciones_ni_caja_ni_deuda(monkeypatch):
    annual = _annual_operativa()
    del annual["shares_diluted"]
    _patch_base(monkeypatch, annual, _point_basico())
    with pytest.raises(ValueError, match="sin acciones diluidas"):
        svc.starting_point(_DB(), CO, today=TODAY)
    point_sin_caja = {"total_debt": _cite("total_debt", 30e6, period="2025-12-31:FY")}
    _patch_base(monkeypatch, _annual_operativa(), point_sin_caja)
    with pytest.raises(ValueError, match="sin caja"):
        svc.starting_point(_DB(), CO, today=TODAY)
    point_sin_deuda = {"cash_and_equivalents": _cite("cash_and_equivalents", 50e6, period="2025-12-31:FY")}
    _patch_base(monkeypatch, _annual_operativa(), point_sin_deuda)
    with pytest.raises(ValueError, match="sin deuda"):
        svc.starting_point(_DB(), CO, today=TODAY)


def test_starting_point_camino_feliz_pe(monkeypatch):
    _patch_base(monkeypatch, _annual_operativa(), _point_basico())
    sp, hist, warnings, cites = svc.starting_point(_DB(), CO, today=TODAY)
    assert sp.basis == "pe" and sp.shares_diluted == 100.0 and sp.revenue == 900.0
    assert sp.cash == 50.0 and sp.debt == 30.0 and sp.currency == "USD"
    assert cites["method"]["chosen"] == "tir_per"  # sin EBITDA etiquetado: el beneficio manda
    assert any("media diluida del ejercicio 2025" in w for w in warnings)
    assert any("capital híbrido: sin dato" in w for w in warnings)
    assert any("adquisiciones sin dato" in w for w in warnings)
    assert hist.years == [2024, 2025] and hist.earnings == [40.0, 50.0]
    assert cites["price"]["value"] == 10.0


def test_starting_point_subunidad_gbp(monkeypatch):
    _patch_base(monkeypatch, _annual_operativa(), _point_basico(), price=(9500.0, "GBp", "2026-11-08"))
    sp, hist, warnings, cites = svc.starting_point(_DB(), CO, today=TODAY)
    assert "subunidad" in cites["price"]["fx"] and "par guardado" in cites["price"]["fx"]
    assert cites["price"]["currency"] == "USD"  # convertido a la divisa de los informes
    assert cites["price"]["value"] == 95.0  # 9500 peniques / 100; el parche del par devuelve el valor tal cual


# --- starting_point: FFO, preingresos, holding, BPA, portada, ADR -----------------


def test_starting_point_real_estate_ffo(monkeypatch):
    annual = _annual_operativa()
    annual["depreciation_amortization"] = {
        2024: _cite("depreciation_amortization", 10e6, 2024),
        2025: _cite("depreciation_amortization", 12e6),
    }
    annual["gain_on_sale_real_estate"] = {
        2024: _cite("gain_on_sale_real_estate", 2e6, 2024),
        2025: _cite("gain_on_sale_real_estate", 3e6),
    }
    _patch_base(monkeypatch, annual, _point_basico())
    monkeypatch.setattr(svc, "company_kind", lambda c, annual: ("real_estate", "REIT listado"))
    sp, hist, warnings, cites = svc.starting_point(_DB(), CO, today=TODAY)
    assert cites["method"]["chosen"] == "tir_ffo" and cites["method"]["kind"] == "real_estate"
    assert cites["ffo"]["formula"].startswith("beneficio neto + amortizaciones")
    assert hist.earnings[-1] == 50.0 + 12.0 - 3.0  # FFO = beneficio + amortización − plusvalías
    assert sp.earnings_label == "FFO"


def test_starting_point_real_estate_ffo_parcial(monkeypatch):
    annual = _annual_operativa()
    annual["depreciation_amortization"] = {
        2024: _cite("depreciation_amortization", 10e6, 2024),
        2025: _cite("depreciation_amortization", 12e6),
    }
    annual["gain_on_sale_real_estate"] = {2025: _cite("gain_on_sale_real_estate", 3e6)}  # 2024 sin dato
    _patch_base(monkeypatch, annual, _point_basico())
    monkeypatch.setattr(svc, "company_kind", lambda c, annual: ("real_estate", "REIT listado"))
    _, _, warnings, _ = svc.starting_point(_DB(), CO, today=TODAY)
    assert any("FFO N/D en 2024 (sin plusvalías por ventas de inmuebles)" in w for w in warnings)


def test_starting_point_pre_ingresos(monkeypatch):
    _patch_base(monkeypatch, _annual_operativa(), _point_basico())
    monkeypatch.setattr(svc, "company_kind", lambda c, annual: ("pre_revenue", "quema de caja"))
    _, _, _, cites = svc.starting_point(_DB(), CO, today=TODAY)
    assert cites["method"]["chosen"] == "caja_runway" and cites["method"]["kind_method"]


def _annual_holding():
    return {
        "net_income": {2025: _cite("net_income", 30e6)},
        "total_equity": {2025: _cite("total_equity", 400e6)},
        "shares_diluted": {2025: _cite("shares_diluted", 100e6, unit="shares")},
    }


def test_starting_point_holding_pb_y_nav(monkeypatch):
    _patch_base(monkeypatch, _annual_holding(), _point_basico())
    monkeypatch.setattr(svc, "company_kind", lambda c, annual: ("standard_dcf", "estándar"))
    monkeypatch.setattr(
        svc, "investment_holding_reason", lambda db, c, annual, kind, reason: "NAV de la cartera"
    )
    sp, _, _, cites = svc.starting_point(_DB(), CO, today=TODAY)
    assert cites["method"]["chosen"] == "tir_pb" and cites["method"]["kind"] == "holding" and sp.basis == "pb"
    assert cites["book_value"]["formula"].startswith("NAV = patrimonio de la sociedad de inversión")
    assert cites["nav"]["nav"] == 400.0 and cites["nav"]["nav_per_share"] == 4.0


def test_starting_point_base_pb_sin_valor_contable(monkeypatch):
    _patch_base(monkeypatch, _annual_operativa(), _point_basico())  # operativa sin patrimonio etiquetado
    with pytest.raises(ValueError, match="sin valor contable"):
        svc.starting_point(_DB(), CO, today=TODAY, basis="pb")


def test_starting_point_acciones_derivadas_del_bpa(monkeypatch):
    annual = _annual_operativa()
    del annual["shares_diluted"]
    annual["eps_diluted"] = {2025: _cite("eps_diluted", 0.5, unit="USD/share")}
    _patch_base(monkeypatch, annual, _point_basico())
    sp, _, warnings, cites = svc.starting_point(_DB(), CO, today=TODAY)
    assert sp.shares_diluted == 100.0  # 50 M de beneficio / 0.5 de BPA
    assert cites["shares"]["formula"].startswith("beneficio neto / BPA diluido")
    assert any("derivadas como beneficio / BPA" in w for w in warnings)


def test_starting_point_portada_posterior_al_cierre(monkeypatch):
    point = _point_basico()
    point["shares_outstanding"] = _cite("shares_outstanding", 102e6, unit="shares", period="2026-02-01:Q1")
    _patch_base(monkeypatch, _annual_operativa(), point)
    sp, _, warnings, cites = svc.starting_point(_DB(), CO, today=TODAY)
    assert sp.shares_diluted == 102.0 and cites["shares"]["value"] == 102e6


def test_starting_point_adr_convierte_a_ads(monkeypatch):
    import app.valuation.engines.base as vbase
    import app.valuation.share_units as vsu

    monkeypatch.setattr(vbase, "adr_ratio", lambda company: 2.0)
    monkeypatch.setattr(vsu, "count_basis", lambda value, ref, ratio: "ordinary")
    _patch_base(monkeypatch, _annual_operativa(), _point_basico())
    _, _, warnings, cites = svc.starting_point(_DB(), CO, today=TODAY)
    assert cites["adr_share_basis"]["ordinary_per_ads"] == 2.0
    assert cites["adr_share_basis"]["converted"] and not cites["adr_share_basis"]["unresolved"]
    assert any("ADR: acciones y BPA en ADS" in w for w in warnings)


def test_starting_point_adr_recuento_sin_resolver(monkeypatch):
    import app.valuation.engines.base as vbase
    import app.valuation.share_units as vsu

    monkeypatch.setattr(vbase, "adr_ratio", lambda company: 2.0)
    monkeypatch.setattr(vsu, "count_basis", lambda value, ref, ratio: None)
    annual = _annual_operativa()
    for by_year in annual.values():  # fuentes de agregador: ni filing ni cuadre -> sin resolver
        for c in by_year.values():
            c["source_type"] = "yahoo"
    _patch_base(monkeypatch, annual, _point_basico())
    _, _, warnings, cites = svc.starting_point(_DB(), CO, today=TODAY)
    assert cites["adr_share_basis"]["unresolved"] and not cites["adr_share_basis"]["converted"]
    assert any("sin convertir" in w for w in warnings)


def test_starting_point_minoritarios_escala_flujos(monkeypatch):
    annual = _annual_operativa()
    annual["net_income_total"] = {
        2024: _cite("net_income_total", 45e6, 2024),
        2025: _cite("net_income_total", 55e6),
    }
    annual["net_income_minority"] = {
        2024: _cite("net_income_minority", 5e6, 2024),
        2025: _cite("net_income_minority", 5e6),
    }
    annual["operating_cash_flow"] = {
        2024: _cite("operating_cash_flow", 60e6, 2024),
        2025: _cite("operating_cash_flow", 70e6),
    }
    point = _point_basico()
    point["minority_interest"] = _cite("minority_interest", 20e6, period="2025-12-31:FY")
    _patch_base(monkeypatch, annual, point)
    _, hist, warnings, cites = svc.starting_point(_DB(), CO, today=TODAY)
    assert "attributable_share" in cites
    assert any("minoritarios: flujo de caja" in w for w in warnings)
    assert hist.operating_cash_flow[-1] < 70.0  # escalado a la parte del accionista
