"""Ramas residuales de shareholder_irr_service tras la batería de bordes (#5185): empates de fuente,
FFO del último año N/D, portada Up-C, arrendamientos IFRS, híbridos, ADR por acción, NAV del filing,
banco sin NAV y value_company con base P/VC. Archivo autocontenido (main no tiene el de bordes)."""

from datetime import date
from types import SimpleNamespace

from app.services import shareholder_irr_service as svc
from app.valuation import shareholder_irr as engine
from app.valuation import shareholder_irr_rules as rules

CO = SimpleNamespace(
    id=1,
    ticker="ASTS",
    name="AST SpaceMobile",
    currency="USD",
    country="US",
    industry="Satellite",
    factor_tags=None,
)
TODAY = date(2026, 11, 9)


class _Sc:
    def __init__(self, rows):
        self._rows = rows

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return list(self._rows)


class _DB:
    def __init__(self, results=()):
        self._it = iter(results)

    def scalars(self, _stmt):
        return _Sc(next(self._it, []))

    def execute(self, _stmt):
        return _Sc(next(self._it, []))


def _cite(metric, value, year=2025, *, unit="USD", period=None, source="f", source_type="sec"):
    return {
        "metric": metric,
        "value": value,
        "unit": unit,
        "period": period or f"{year}-12-31:FY",
        "source": source,
        "source_type": source_type,
        "filed": None,
        "source_url": "u",
        "accession_number": None,
    }


def _patch_base(monkeypatch, annual, point, price=(10.0, "USD", "2026-11-08")):
    monkeypatch.setattr(svc, "company_facts", lambda db, c: (annual, point))
    from app.services import user_sotp_service as sotp

    monkeypatch.setattr(sotp, "_price", lambda db, c: price)
    monkeypatch.setattr(sotp, "convert_amount", lambda db, v, u, cc, t: (v, "par guardado"))


def _operativa():
    return {
        "revenue": {2024: _cite("revenue", 800e6, 2024), 2025: _cite("revenue", 900e6)},
        "net_income": {2024: _cite("net_income", 40e6, 2024), 2025: _cite("net_income", 50e6)},
        "shares_diluted": {2025: _cite("shares_diluted", 100e6, unit="shares")},
    }


def _punto():
    return {
        "cash_and_equivalents": _cite("cash_and_equivalents", 50e6, period="2025-12-31:FY"),
        "total_debt": _cite("total_debt", 30e6, period="2025-12-31:FY"),
    }


# --- company_facts: empates de fecha y rango -------------------------------------


def test_empates_no_reemplazan_a_la_mejor_fuente(monkeypatch):
    def fila(metric, value, source_type, period="2025-12-31:FY"):
        return SimpleNamespace(
            metric=metric,
            value=value,
            unit="USD",
            period=period,
            source=None,
            source_url="u",
            filed=None,
            source_type=source_type,
            accession_number=None,
            created_at=None,
        )

    rows = [
        [
            fila("total_debt", 280e6, "SEC"),  # gana la primera (mejor fuente)
            fila("total_debt", 999e6, "FMP"),  # misma fecha, peor fuente: no reemplaza
            fila("revenue", 800e6, "SEC"),
            fila("revenue", 999e6, "FMP"),  # mismo año, peor fuente: no reemplaza
        ]
    ]
    # Los hechos llegan por ``_read_fact_rows`` (columnas sueltas, r5-perf2); la reducción es la misma.
    monkeypatch.setattr(svc, "_read_fact_rows", lambda db, ids: {i: list(rows[0]) for i in ids})
    annual, point = svc.company_facts(_DB(), CO)
    assert point["total_debt"]["value"] == 280e6 and annual["revenue"][2025]["value"] == 800e6


# --- real_estate: lease_income y FFO del último año N/D -----------------------------


def test_reit_lease_income_manda_sobre_revenue(monkeypatch):
    annual = _operativa()
    annual["lease_income"] = {2025: _cite("lease_income", 950e6)}
    annual["depreciation_amortization"] = {
        2024: _cite("depreciation_amortization", 10e6, 2024),
        2025: _cite("depreciation_amortization", 12e6),
    }
    annual["gain_on_sale_real_estate"] = {
        2024: _cite("gain_on_sale_real_estate", 2e6, 2024),
        2025: _cite("gain_on_sale_real_estate", 3e6),
    }
    _patch_base(monkeypatch, annual, _punto())
    monkeypatch.setattr(svc, "company_kind", lambda c, a: ("real_estate", "REIT"))
    sp, _, _, _ = svc.starting_point(_DB(), CO, today=TODAY)
    assert sp.revenue == 950.0  # el alquiler etiquetado supera al «Revenues» genérico


def test_reit_ffo_ultimo_anno_nd(monkeypatch):
    annual = _operativa()
    annual["depreciation_amortization"] = {2024: _cite("depreciation_amortization", 10e6, 2024)}
    annual["gain_on_sale_real_estate"] = {2024: _cite("gain_on_sale_real_estate", 2e6, 2024)}
    _patch_base(monkeypatch, annual, _punto())
    monkeypatch.setattr(svc, "company_kind", lambda c, a: ("real_estate", "REIT"))
    _, _, warnings, cites = svc.starting_point(_DB(), CO, today=TODAY)
    assert any("FFO 2025 N/D" in w and "método general" in w for w in warnings)
    assert cites["method"]["chosen"] != "tir_ffo"


# --- portada Up-C ---------------------------------------------------------------------


def _punto_upc():
    point = _punto()
    cover = _cite("shares_outstanding", 100e6, unit="shares", period="2026-02-01:Q1")
    cover["class_members"] = {"ASTS.A": 80e6, "ASTS.B": 20e6}
    point["shares_outstanding"] = cover
    point["minority_interest"] = _cite("minority_interest", 20e6, period="2025-12-31:FY")
    point["total_equity"] = _cite("total_equity", 100e6, period="2025-12-31:FY")
    return point


def test_portada_upc_base_beneficio(monkeypatch):
    annual = _operativa()
    annual["total_equity"] = {2025: _cite("total_equity", 100e6)}
    _patch_base(monkeypatch, annual, _punto_upc())
    sp, _, warnings, cites = svc.starting_point(_DB(), CO, today=TODAY)
    assert "shares_up_c" in cites and cites["shares_up_c"]["basis"] == "pe"
    assert sp.shares_diluted == 80.0  # clase listada; las emparejadas van con minoritarios
    assert any("Up-C: beneficio atribuible por acción" in w for w in warnings)
    assert any("suma de todas las clases" in w for w in warnings)


def test_portada_upc_base_ev_no_resta_minoritarios(monkeypatch):
    annual = _operativa()
    annual["operating_income"] = {
        2024: _cite("operating_income", 60e6, 2024),
        2025: _cite("operating_income", 70e6),
    }
    annual["depreciation_amortization"] = {
        2024: _cite("depreciation_amortization", 20e6, 2024),
        2025: _cite("depreciation_amortization", 22e6),
    }
    _patch_base(monkeypatch, annual, _punto_upc())
    sp, _, warnings, cites = svc.starting_point(_DB(), CO, today=TODAY, basis="ev_ebitda")
    assert cites["shares_up_c"]["basis"] == "ev_ebitda"
    assert sp.minorities == 0.0  # ya están dentro de las acciones (todas las clases)
    assert any("unidades canjeables" in w for w in warnings)


def test_portada_por_debajo_de_la_media(monkeypatch):
    point = _punto()
    point["shares_outstanding"] = _cite("shares_outstanding", 90e6, unit="shares", period="2026-02-01:Q1")
    _patch_base(monkeypatch, _operativa(), point)
    _, _, warnings, _ = svc.starting_point(_DB(), CO, today=TODAY)
    assert any("por debajo de la media diluida" in w for w in warnings)


# --- arrendamientos IFRS, híbridos y acciones propias ------------------------------------


def test_arrendamientos_ifrs_corriente_mas_no_corriente(monkeypatch):
    point = _punto()
    point["lease_liabilities_current"] = _cite("lease_liabilities_current", 5e6, period="2025-12-31:FY")
    point["lease_liabilities_noncurrent"] = _cite(
        "lease_liabilities_noncurrent", 10e6, period="2025-12-31:FY"
    )
    point["hybrid_capital"] = _cite("hybrid_capital", 8e6, period="2025-12-31:FY")
    _patch_base(monkeypatch, _operativa(), point)
    sp, _, warnings, cites = svc.starting_point(_DB(), CO, today=TODAY)
    assert sp.leases == 15.0 and sp.hybrids == 8.0
    assert cites["lease_liabilities_current"]["value"] == 5e6
    assert not any("capital híbrido: sin dato" in w for w in warnings)


def test_ifrs_forzado_sin_pasivos_por_arrendamiento(monkeypatch):
    _patch_base(monkeypatch, _operativa(), _punto())
    sp, _, warnings, _ = svc.starting_point(_DB(), CO, today=TODAY, include_leases=True)
    assert sp.leases == 0.0
    assert any("EBITDA bajo IFRS 16" in w and "EV queda corto" in w for w in warnings)


# --- ADR: BPA por acción y portada sin año -------------------------------------------------


def test_adr_bpa_por_accion_y_portada_sin_anno(monkeypatch):
    import app.valuation.engines.base as vbase
    import app.valuation.share_units as vsu

    monkeypatch.setattr(vbase, "adr_ratio", lambda company: 2.0)
    monkeypatch.setattr(vsu, "count_basis", lambda value, ref, ratio: "ads")
    annual = _operativa()
    annual["eps_diluted"] = {2025: _cite("eps_diluted", 0.5, unit="USD/share")}
    point = _punto()
    point["shares_outstanding"] = _cite("shares_outstanding", 102e6, unit="shares", period="sin-fecha")
    _patch_base(monkeypatch, annual, point)
    _, _, warnings, cites = svc.starting_point(_DB(), CO, today=TODAY)
    assert cites["adr_share_basis"]["ordinary_per_ads"] == 2.0
    assert any("ADR" in w for w in warnings)


# --- NAV del filing y banco sin NAV --------------------------------------------------------


def _holding_annual():
    return {
        "net_income": {2025: _cite("net_income", 30e6)},
        "total_equity": {2025: _cite("total_equity", 400e6)},
        "shares_diluted": {2025: _cite("shares_diluted", 100e6, unit="shares")},
    }


def test_holding_nav_del_filing_manda(monkeypatch):
    _patch_base(monkeypatch, _holding_annual(), _punto())
    monkeypatch.setattr(svc, "company_kind", lambda c, a: ("standard_dcf", "estándar"))
    monkeypatch.setattr(svc, "investment_holding_reason", lambda db, c, a, k, r: "NAV de la cartera")
    monkeypatch.setattr(
        svc, "nav_from_filing", lambda company, year, ccy, agg, warnings: {"value_millions": 420.0, "page": 3}
    )
    sp, _, _, cites = svc.starting_point(_DB(), CO, today=TODAY)
    assert cites["nav"]["nav"] == 420.0  # el filing corrige al agregador
    assert cites["book_value"]["inputs"][0] == {"value_millions": 420.0, "page": 3}


def test_banco_por_valor_contable_sin_nav(monkeypatch):
    annual = _operativa()
    annual["total_equity"] = {2025: _cite("total_equity", 400e6)}
    _patch_base(monkeypatch, annual, _punto())
    monkeypatch.setattr(svc, "company_kind", lambda c, a: ("bank", "banco"))
    sp, _, _, cites = svc.starting_point(_DB(), CO, today=TODAY)
    assert cites["method"]["chosen"] == "tir_pb" and sp.basis == "pb"
    assert cites["book_value"]["formula"].startswith("patrimonio atribuible a la matriz")


# --- value_company con base P/VC: sin guidance ------------------------------------------------


def test_value_company_base_pb_sin_guidance(monkeypatch):
    sp = engine.StartingPoint(
        price=10.0,
        shares_diluted=100.0,
        revenue=400.0,
        ebitda=None,
        net_income=30.0,
        cash=10.0,
        debt=20.0,
        currency="USD",
        basis="pb",
    )
    hist = rules.History(
        years=[2025], revenue=[400.0], earnings=[30.0], operating_cash_flow=[None], capex=[None]
    )
    cites = {
        "method": {
            "chosen": "tir_pb",
            "kind": "bank",
            "kind_reason": "banco",
            "kind_method": "m",
            "discarded": {},
        },
        "annual": {"total_equity": {"2025": _cite("total_equity", 400e6)}},
    }
    monkeypatch.setattr(svc, "starting_point", lambda db, c, *, today: (sp, hist, [], cites))
    monkeypatch.setattr(svc, "_peer_multiples", lambda db, c, basis, today: [])
    monkeypatch.setattr(svc, "run_valuation", lambda sp, hist, **kw: {"warnings": [], "base_irr_10": 0.08})
    out = svc.value_company(_DB(), CO, today=TODAY)
    assert out["status"] == "ok" and out["guidance_growth"] is None and "fingerprint" in out
