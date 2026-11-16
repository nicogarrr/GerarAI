"""«Punto óptimo» de las estimaciones de analistas: agregado, revisiones y precisión por firma.

Encargo de Nico (8-nov-2026): con todas las notas recopiladas, el código agrega
y mide; los expertos eligen bajo/mediana/alto con razón. Este módulo NO elige:
da a los expertos, por métrica y año, cada estimación vigente por firma (con
fecha y URL), su mediana, mínimo y máximo, las revisiones de cada firma y, si
hay histórico suficiente, el peso de cada firma según su precisión pasada.

Regla de ponderación PRERREGISTRADA (fijada aquí antes de ver resultados; se
cambia solo con un PR nuevo y su backtest, nunca a ojo):

- Muestra de una firma = cada (año fiscal ya reportado) para el que la firma
  publicó una estimación ANTES del cierre de ese año; se usa la última publicada
  antes del cierre. Error = |estimación − real| / |real| (ingresos anuales SEC).
- Peso = 1 / max(mediana del error, ``ERROR_FLOOR``), solo con al menos
  ``MIN_SAMPLES_PER_FIRM`` muestras; una firma sin muestras suficientes pesa lo
  mismo que la mediana de los pesos de las que sí tienen (o todas 1 si ninguna).
- El agregado ponderado solo se ofrece si el backtest (dejando fuera un año
  cada vez) tiene al menos ``MIN_BACKTEST_YEARS`` años y su error mediano es
  menor que el de la mediana simple; si no, ``weighting.status`` lo dice y el
  agregado es la mediana simple.

Las cifras de «Consenso (prensa)» (frases de prensa sin firma) se muestran
aparte y no cuentan como firma.
"""

from __future__ import annotations

import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

MIN_SAMPLES_PER_FIRM = 3
MIN_BACKTEST_YEARS = 3
ERROR_FLOOR = 0.02
RULE_ID = "precision_inversa_mediana_v1 (prerregistrada 8-nov-2026)"
CONSENSUS_FIRM = "Consenso (prensa)"
# Frescura de la mediana vigente: una estimacion mas vieja que la ventana no
# entra en low/median/high de un año aun sin reportar; se lista aparte como
# caducada. Misma ventana que el consenso de precios objetivo
# (analyst_history_service.CONSENSUS_WINDOW_DAYS) para no tener dos varas de
# medir la frescura de analistas.
ESTIMATE_WINDOW_DAYS = 365


@dataclass(frozen=True)
class FirmEstimate:
    firm: str
    metric: str
    year: int
    value: float  # millones
    as_of: date
    url: str | None


def _median(values: Sequence[float]) -> float | None:
    return float(statistics.median(values)) if values else None


def _close_of(year: int, year_ends: Mapping[int, date] | None) -> date:
    """Cierre real del año fiscal; 31-dic solo cuando no se conoce el cierre."""
    return (year_ends or {}).get(year) or date(year, 12, 31)


def firm_errors(history: Sequence[FirmEstimate], actuals: Mapping[int, float], *,
                metric: str = "revenue",
                year_ends: Mapping[int, date] | None = None) -> dict[str, list[tuple[int, float]]]:
    """Errores relativos por firma: la última estimación publicada antes del cierre de cada año.

    El cierre es el real del año fiscal (``year_ends``, de los hechos SEC/ESEF
    que alimentan ``actuals``): con el 31-dic a secas, una firma que estima
    DESPUÉS del cierre real de un ejercicio no natural (MSFT jun, WMT/NVDA
    ene) colaba una estimación a toro pasado como «previsión» y maquillaba su
    precisión (Lote 2, hallazgo 1 del carril de auditoría).
    """
    best: dict[tuple[str, int], FirmEstimate] = {}
    for est in history:
        if est.metric != metric or est.firm == CONSENSUS_FIRM or est.year not in actuals:
            continue
        if est.as_of > _close_of(est.year, year_ends):
            continue  # publicada después del cierre: no es una previsión
        key = (est.firm, est.year)
        if key not in best or est.as_of > best[key].as_of:
            best[key] = est
    out: dict[str, list[tuple[int, float]]] = {}
    for (firm, year), est in best.items():
        real = actuals[year]
        if real:
            out.setdefault(firm, []).append((year, abs(est.value - real) / abs(real)))
    return out


def weights_from(errors: Mapping[str, Sequence[tuple[int, float]]], firms: Sequence[str],
                 *, exclude_year: int | None = None) -> dict[str, float]:
    measured: dict[str, float] = {}
    for firm, samples in errors.items():
        values = [e for y, e in samples if y != exclude_year]
        if len(values) >= MIN_SAMPLES_PER_FIRM:
            measured[firm] = 1.0 / max(float(statistics.median(values)), ERROR_FLOOR)
    default = float(statistics.median(measured.values())) if measured else 1.0
    return {f: measured.get(f, default) for f in firms}


def _weighted_median(pairs: Sequence[tuple[float, float]]) -> float | None:
    pairs = sorted(pairs)
    total = sum(w for _, w in pairs)
    if not pairs or total <= 0:
        return None
    acc = 0.0
    for value, weight in pairs:
        acc += weight
        if acc >= total / 2:
            return value
    return pairs[-1][0]


def backtest(history: Sequence[FirmEstimate], actuals: Mapping[int, float], *, metric: str = "revenue",
             year_ends: Mapping[int, date] | None = None) -> dict[str, Any]:
    """Mediana simple frente a la ponderada por precisión, dejando fuera cada año evaluado."""
    errors = firm_errors(history, actuals, metric=metric, year_ends=year_ends)
    years = sorted({y for samples in errors.values() for y, _ in samples})
    rows: list[dict[str, Any]] = []
    for year in years:
        latest: dict[str, FirmEstimate] = {}
        for est in history:
            if (est.metric == metric and est.year == year and est.firm != CONSENSUS_FIRM
                    and est.as_of <= _close_of(year, year_ends)
                    and (est.firm not in latest or est.as_of > latest[est.firm].as_of)):
                latest[est.firm] = est
        if len(latest) < 2:
            continue
        w = weights_from(errors, list(latest), exclude_year=year)
        simple = _median([e.value for e in latest.values()])
        weighted = _weighted_median([(e.value, w[f]) for f, e in latest.items()])
        real = actuals[year]
        if simple is None or weighted is None or not real:
            continue
        rows.append({"year": year, "firms": len(latest), "real": real,
                     "simple_error": abs(simple - real) / abs(real), "weighted_error": abs(weighted - real) / abs(real)})
    if len(rows) < MIN_BACKTEST_YEARS:
        return {"status": "insufficient_history", "rule": RULE_ID, "years": len(rows),
                "needed_years": MIN_BACKTEST_YEARS, "rows": rows,
                "message": (f"Solo {len(rows)} año(s) con dos o más firmas y dato real: hacen falta "
                            f"{MIN_BACKTEST_YEARS}. Se usa la mediana simple; la recogida diaria sigue acumulando.")}
    simple_err = float(statistics.median(r["simple_error"] for r in rows))
    weighted_err = float(statistics.median(r["weighted_error"] for r in rows))
    return {"status": "validated" if weighted_err < simple_err else "rejected", "rule": RULE_ID, "years": len(rows),
            "simple_median_error": simple_err, "weighted_median_error": weighted_err, "rows": rows}


def aggregate(history: Sequence[FirmEstimate], actuals: Mapping[int, float] | None = None, *,
              year_ends: Mapping[int, date] | None = None,
              today: date | None = None) -> list[dict[str, Any]]:
    """Por (métrica, año): estimación vigente de cada firma, agregados, revisiones y ponderación.

    Para años AÚN sin reportar y con ``today`` informado, la mediana solo
    cuenta estimaciones frescas (``ESTIMATE_WINDOW_DAYS``): la última de cada
    firma entraba en la mediana sin importar su edad y una cifra fosilizada se
    publicaba como consenso vigente (Lote 2, hallazgo 2). Las caducadas se
    listan en ``stale_firms`` con su fecha, fuera del agregado. Años ya
    reportados: histórico completo, sin filtro.
    """
    actuals = actuals or {}
    errors = firm_errors(history, actuals, year_ends=year_ends)
    check = backtest(history, actuals, year_ends=year_ends)
    out: list[dict[str, Any]] = []
    keys = sorted({(e.metric, e.year) for e in history})
    for metric, year in keys:
        rows = sorted((e for e in history if e.metric == metric and e.year == year), key=lambda e: e.as_of)
        latest: dict[str, FirmEstimate] = {}
        revisions: list[dict[str, Any]] = []
        for est in rows:
            prev = latest.get(est.firm)
            if prev is not None and abs(prev.value - est.value) > 1e-9:
                revisions.append({"firm": est.firm, "from": prev.value, "to": est.value,
                                  "from_date": prev.as_of.isoformat(), "to_date": est.as_of.isoformat()})
            latest[est.firm] = est
        firms = {f: e for f, e in latest.items() if f != CONSENSUS_FIRM}
        stale: dict[str, FirmEstimate] = {}
        if today is not None and year not in actuals:
            cutoff = today - timedelta(days=ESTIMATE_WINDOW_DAYS)
            stale = {f: e for f, e in firms.items() if e.as_of < cutoff}
            firms = {f: e for f, e in firms.items() if e.as_of >= cutoff}
        values = [e.value for e in firms.values()]
        item: dict[str, Any] = {
            "metric": metric, "year": year, "firms": [
                {"firm": f, "value_millions": e.value, "as_of": e.as_of.isoformat(), "url": e.url}
                for f, e in sorted(firms.items(), key=lambda kv: kv[1].value)],
            "stale_firms": [
                {"firm": f, "value_millions": e.value, "as_of": e.as_of.isoformat(), "url": e.url}
                for f, e in sorted(stale.items(), key=lambda kv: kv[1].value)],
            "n_firms": len(values), "low": min(values) if values else None, "median": _median(values),
            "high": max(values) if values else None, "revisions": revisions,
            "press_consensus": ({"value_millions": latest[CONSENSUS_FIRM].value,
                                 "as_of": latest[CONSENSUS_FIRM].as_of.isoformat(), "url": latest[CONSENSUS_FIRM].url}
                                if CONSENSUS_FIRM in latest else None),
            "weighting": {"status": check["status"], "rule": RULE_ID},
        }
        if check["status"] == "validated" and metric == "revenue" and firms:
            w = weights_from(errors, list(firms))
            item["weighted_median"] = _weighted_median([(e.value, w[f]) for f, e in firms.items()])
            item["weights"] = w
        out.append(item)
    return out


def history_for(db: Any, company: Any, tenant_id: int) -> list[FirmEstimate]:
    """Todas las estimaciones por firma y año guardadas (notas de analista con ``estimates``)."""
    from sqlalchemy import select

    from app.models import AnalystNote

    out: list[FirmEstimate] = []
    notes = db.scalars(select(AnalystNote).where(AnalystNote.tenant_id == tenant_id,
                                                 AnalystNote.ticker == company.ticker)).all()
    for note in notes:
        for metric, by_year in (note.estimates or {}).items():
            if not isinstance(by_year, dict):
                continue
            for year, value in by_year.items():
                try:
                    out.append(FirmEstimate(note.firm, str(metric), int(year), float(value), note.note_date,
                                            note.source_url))
                except (TypeError, ValueError):
                    continue
    from app.models.declared_input_value import DeclaredInputValue

    for row in db.scalars(select(DeclaredInputValue).where(
            DeclaredInputValue.tenant_id == tenant_id, DeclaredInputValue.company_id == company.id,
            DeclaredInputValue.method == "analyst", DeclaredInputValue.analyst_firm == CONSENSUS_FIRM)).all():
        meta = row.metadata_ or {}
        if row.as_of and meta.get("metric") and meta.get("year") and row.base is not None:
            out.append(FirmEstimate(CONSENSUS_FIRM, str(meta["metric"]), int(meta["year"]),
                                    float(row.base) / 1e6, row.as_of, row.source_url))
    return out


def reported_revenue(db: Any, company: Any) -> dict[int, float]:
    """Ingresos anuales reportados (SEC/ESEF), en millones, por año fiscal."""
    return {year: value for year, (value, _end) in _revenue_facts(db, company).items()}


def revenue_year_ends(db: Any, company: Any) -> dict[int, date]:
    """Fecha real de cierre de cada año fiscal con ingresos reportados.

    La etiqueta del año fiscal no dice cuándo cierra: FY2025 de MSFT cierra el
    30-jun-2025. El periodo de los hechos (``<cierre>:FY``) sí lo dice.
    """
    return {year: end for year, (_value, end) in _revenue_facts(db, company).items()}


def _revenue_facts(db: Any, company: Any) -> dict[int, tuple[float, date]]:
    """year fiscal -> (ingresos en millones, cierre real) desde los hechos SEC/ESEF."""
    from sqlalchemy import select

    from app.models import FinancialFact

    out: dict[int, tuple[float, date]] = {}
    for row in db.scalars(select(FinancialFact).where(FinancialFact.company_id == company.id,
                                                      FinancialFact.metric == "revenue",
                                                      FinancialFact.period.like("%:FY"))).all():
        year = row.fiscal_year or int(str(row.period)[:4])
        try:
            end = date.fromisoformat(str(row.period).split(":")[0])
        except ValueError:
            end = date(int(year), 12, 31)
        if row.value is not None:
            out[int(year)] = (float(row.value) / 1e6, end)
    return out
