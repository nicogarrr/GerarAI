"""Conservative, source-citable annual accounting screens, not investment ratings."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from math import isfinite
from typing import Any

PIOTROSKI_SOURCE = "https://www.ivey.uwo.ca/media/3775523/value_investing_the_use_of_historical_financial_statement_information.pdf"
ALTMAN_SOURCE = "https://w4.stern.nyu.edu/finance/docs/WP/2002/pdf/wpa02052.pdf"


@dataclass(frozen=True)
class HealthFact:
    id: int
    metric: str
    year: int
    value: float
    unit: str
    period_end: date
    source_url: str
    source_type: str
    document_id: int | None = None

    def evidence(self) -> dict[str, Any]:
        return {"fact_id": self.id, "metric": self.metric, "value": self.value,
                "unit": self.unit, "period_end": self.period_end.isoformat(),
                "source_url": self.source_url, "source_type": self.source_type,
                "document_id": self.document_id}


class MissingInput(ValueError):
    pass


def calculate_health(facts: list[HealthFact], *, sector: str, company_type: str,
                     today: date | None = None) -> dict[str, Any]:
    """Use three consecutive FY anchors. Unknown is never scored as zero.

    ROA/turnover use beginning assets; leverage uses average assets, following
    Piotroski (2000). Equity issuance must be explicit, not a shares proxy.
    Altman Z'' excludes turnover and uses book equity (no +3.25 EM intercept).
    """
    today = today or date.today()
    out: dict[str, Any] = {"status": "not_evaluable", "piotroski": {
        "score": None, "evaluated": 0, "total": 9, "signals": [],
        "methodology_url": PIOTROSKI_SOURCE}, "altman": {
        "variant": "Z_double_prime", "score": None, "status": "not_evaluable",
        "methodology_url": ALTMAN_SOURCE},
        "notice": "Indicadores contables, no recomendación ni probabilidad de quiebra."}
    kind = f"{sector} {company_type}".lower()
    if not sector or sector.lower() in {"unknown", "other", "n/a"}:
        out["reason"] = "Sector sin clasificar"
        return out
    if any(word in kind for word in ("financ", "bank", "insurance", "reit", "real estate", "pre_revenue", "pre-revenue", "etf", "fund", "fondo")):
        out["reason"] = "Modelo no aplicable a financieras, REIT o empresas preingresos"
        return out
    usable = [f for f in facts if isfinite(f.value) and f.source_url.startswith("https://")
              and f.period_end <= today and f.unit and f.source_type not in {"seed", "manual", "inferred"}]
    by_key = {(f.metric, f.year): f for f in usable}
    # Latest observed FY is authoritative even if its inputs are incomplete.
    year = max((f.year for f in usable), default=None)
    if year is None:
        out["reason"] = "Sin ejercicios anuales con fuente"
        return out
    ends = {f.period_end for f in usable if f.year == year}
    out["fiscal_year"] = year
    if len(ends) != 1 or (today - max(ends)).days > 550:
        out["reason"] = "Ejercicio desactualizado o fechas incoherentes"
        return out
    current_end = next(iter(ends))
    out["period_end"] = current_end.isoformat()
    used: list[HealthFact] = []

    def v(metric: str, offset: int = 0) -> float:
        f = by_key.get((metric, year - offset))
        if f is None:
            raise MissingInput(f"{metric}:FY{year-offset}")
        # Reject mixed currencies and shifted reporting calendars, not just years.
        expected_days = (current_end - f.period_end).days
        if not 330 * offset <= expected_days <= 400 * offset:
            raise MissingInput("periodos no comparables")
        used.append(f)
        if len({x.unit.upper() for x in used}) > 1:
            raise MissingInput("divisas no comparables")
        return f.value

    def ratio(numerator: float, denominator: float) -> float:
        if denominator <= 0:
            raise MissingInput("denominador no positivo")
        return numerator / denominator

    def roa(offset: int = 0) -> float:
        return ratio(v("net_income", offset), v("total_assets", offset + 1))

    def leverage(offset: int = 0) -> float:
        return ratio(v("long_term_debt", offset),
                     (v("total_assets", offset) + v("total_assets", offset + 1)) / 2)

    specs = [
        ("roa", "Beneficio sobre activos positivo", "Beneficio neto(t) / Activos(t-1) > 0", lambda: roa() > 0),
        ("cfo", "Flujo operativo positivo", "Flujo operativo(t) / Activos(t-1) > 0", lambda: ratio(v("operating_cash_flow"), v("total_assets", 1)) > 0),
        ("delta_roa", "Rentabilidad sobre activos mejora", "ROA(t) > ROA(t-1)  (ROA = Beneficio neto / Activos del año anterior)", lambda: roa() > roa(1)),
        ("accrual", "Caja operativa superior al beneficio", "Flujo operativo(t) / Activos(t-1) > ROA(t)", lambda: ratio(v("operating_cash_flow"), v("total_assets", 1)) > roa()),
        ("leverage", "Apalancamiento a largo plazo baja", "Deuda a largo plazo(t) / Activos medios(t) < Deuda a largo plazo(t-1) / Activos medios(t-1)", lambda: leverage() < leverage(1)),
        ("liquidity", "Liquidez corriente mejora", "Activo corriente(t) / Pasivo corriente(t) > Activo corriente(t-1) / Pasivo corriente(t-1)", lambda: ratio(v("current_assets"), v("current_liabilities")) > ratio(v("current_assets", 1), v("current_liabilities", 1))),
        ("issuance", "Sin emisión de capital común", "Emisión de acciones ordinarias(t) = 0 (dato explícito)", lambda: v("common_stock_issued") == 0),
        ("margin", "Margen bruto mejora", "Beneficio bruto(t) / Ventas(t) > Beneficio bruto(t-1) / Ventas(t-1)", lambda: ratio(v("gross_profit"), v("revenue")) > ratio(v("gross_profit", 1), v("revenue", 1))),
        ("turnover", "Rotación de activos mejora", "Ventas(t) / Activos(t-1) > Ventas(t-1) / Activos(t-2)", lambda: ratio(v("revenue"), v("total_assets", 1)) > ratio(v("revenue", 1), v("total_assets", 2))),
    ]
    signals = out["piotroski"]["signals"]
    for key, label, formula, evaluate in specs:
        used = []
        missing = None
        try:
            passed = bool(evaluate())
        except MissingInput as exc:
            passed, missing = None, str(exc)
        signals.append({"id": key, "label": label, "formula": formula,
                        "point": int(passed) if passed is not None else None,
                        "missing_input": missing,
                        "evidence": [f.evidence() for f in dict.fromkeys(used)]})
    evaluated = sum(s["point"] is not None for s in signals)
    out["piotroski"]["evaluated"] = evaluated
    if evaluated == 9:
        out["piotroski"]["score"] = sum(s["point"] for s in signals)
        out["status"] = "ok"
    else:
        out["reason"] = "Faltan puntos verificables; no se publica un F-score parcial"
    used = []
    try:
        assets = v("total_assets")
        x1 = ratio(v("current_assets") - v("current_liabilities"), assets)
        x2 = ratio(v("retained_earnings"), assets)
        # EBIT is not operating income: include non-operating pre-tax earnings.
        x3 = ratio(v("income_before_tax") + v("interest_expense"), assets)
        x4 = ratio(v("total_equity"), v("total_liabilities"))
        z = 6.56 * x1 + 3.26 * x2 + 6.72 * x3 + 1.05 * x4
        out["altman"].update({"status": "ok", "score": round(z, 4),
            "formula": "6,56 × Fondo de maniobra/Activos + 3,26 × Reservas/Activos + 6,72 × EBIT/Activos + 1,05 × Patrimonio neto contable/Pasivos",
            "evidence": [f.evidence() for f in dict.fromkeys(used)]})
    except MissingInput as exc:
        out["altman"]["reason"] = str(exc)
    return out
