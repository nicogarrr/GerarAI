"""Salud financiera (Piotroski/Altman) con el sector sin clasificar (r5-bugs, 11-nov-2026).

Antes: ``company.sector == "Unknown"`` devolvía «No evaluable: Sector sin clasificar» aunque la industria del
perfil («Technology») o la división SIC de la SEC (``sector_of_cik``) dijeran qué empresa es. La puerta existe para
no puntuar financieras/REIT/preingresos; con el sector vacío esa pregunta se responde con la industria y la SIC, y
cualquier señal financiera sigue excluyendo (fail-closed).
"""
from datetime import date

from app.services.financial_health import HealthFact, calculate_health

TODAY = date(2026, 10, 29)


def _facts():
    values = {
        2023: {"total_assets": 100},
        2024: {"total_assets": 110, "net_income": 5, "long_term_debt": 30,
               "current_assets": 50, "current_liabilities": 30, "gross_profit": 30, "revenue": 100},
        2025: {"total_assets": 120, "net_income": 12, "long_term_debt": 20,
               "operating_cash_flow": 15, "current_assets": 70, "current_liabilities": 30,
               "gross_profit": 44, "revenue": 130, "common_stock_issued": 0,
               "retained_earnings": 40, "income_before_tax": 16, "interest_expense": 2,
               "total_equity": 70, "total_liabilities": 50},
    }
    out = []
    for year, metrics in values.items():
        for metric, value in metrics.items():
            out.append(HealthFact(len(out) + 1, metric, year, value, "USD", date(year, 12, 31),
                                  "https://www.sec.gov/test", "SEC", 1))
    return out


def _calc(**kw):
    return calculate_health(_facts(), company_type=kw.pop("company_type", "operating"), today=TODAY, **kw)


def test_sector_desconocido_con_industria_conocida_se_evalua():
    out = _calc(sector="Unknown", industry="Technology")
    assert out.get("reason") != "Sector sin clasificar"
    assert out["piotroski"]["score"] == 9
    assert out["altman"]["score"] is not None


def test_sector_desconocido_con_division_sic_se_evalua():
    out = _calc(sector="Unknown", industry="Unknown", sic_sector="manufactura")
    assert out["piotroski"]["score"] == 9


def test_sector_desconocido_y_sic_financiera_sigue_excluida():
    out = _calc(sector="Unknown", industry=None, sic_sector="finanzas")
    assert out["status"] == "not_evaluable"
    assert out["reason"] == "Modelo no aplicable a financieras, REIT o empresas preingresos"
    assert out["piotroski"]["score"] is None


def test_industria_financiera_sigue_excluida():
    out = _calc(sector="Unknown", industry="Financial Services")
    assert out["reason"] == "Modelo no aplicable a financieras, REIT o empresas preingresos"


def test_sin_ninguna_clasificacion_sigue_sin_clasificar():
    for sector, industry, sic in (("Unknown", "Unknown", None), (None, None, "otros"), ("", "n/a", None)):
        out = _calc(sector=sector, industry=industry, sic_sector=sic)
        assert out["reason"] == "Sector sin clasificar"
        assert out["piotroski"]["score"] is None


def test_sector_conocido_no_cambia():
    # Con sector clasificado la industria no entra: el resultado es el de siempre.
    assert _calc(sector="Industrials")["piotroski"]["score"] == 9
    assert _calc(sector="Financials", industry="Technology")["reason"] == (
        "Modelo no aplicable a financieras, REIT o empresas preingresos")


def test_build_summaries_pasa_industria_y_sic(monkeypatch):
    """La llamada de valuation_summary entrega industria y división SIC a la salud."""
    import app.services.valuation_summary as vs

    seen = {}

    def fake(facts, **kw):
        seen.update(kw)
        return {"status": "not_evaluable", "reason": "x", "piotroski": {}, "altman": {}, "notice": ""}

    monkeypatch.setattr(vs, "calculate_health", fake)
    monkeypatch.setattr(vs, "resolve_fair_values", lambda db, companies, today=None: {c.id: {} for c in companies})
    monkeypatch.setattr(vs, "cash_burn_base_rate", lambda *a, **k: None)

    class _Result(list):
        def all(self):
            return list(self)

    class _DB:
        info = {}

        def scalars(self, *_a, **_k):
            return _Result()

    class _Co:
        id, ticker, sector, industry, company_type, cik = 1, "AAPL", "Unknown", "Technology", "operating", "0000320193"

    monkeypatch.setattr(vs, "tenant_filters", lambda *a, **k: [])
    vs.build_summaries(_DB(), [_Co()], today=TODAY)  # type: ignore[arg-type]
    assert seen["industry"] == "Technology"
    assert seen["sic_sector"] == "manufactura"
