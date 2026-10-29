"""Ten-year source-aware financial terminal projection."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.tenancy import tenant_filters
from app.models import CalculatedMetric, Company, Document, FinancialFact
from app.services.financial_ingestion_service import SOURCE_PRIORITY, _is_bank_like
from app.services.metric_calculation_service import METRIC_DEFINITIONS

DEFAULT_TERMINAL_METRICS = (
    "revenue",
    "eps",
    "free_cash_flow",
    "fcf_per_share",
    "roic",
    "roce",
    "incremental_roic",
    "shares_diluted",
    "stock_based_compensation",
    "working_capital",
    "capital_expenditure",
    "owner_earnings",
    "gross_margin",
    "operating_margin",
    "net_margin",
    "total_assets",
    "total_debt",
    "total_equity",
    "cash_and_equivalents",
)


METRIC_DEFINITIONS_TEXT = {
    "revenue": "Reported consolidated or segment revenue.",
    "eps": "Diluted earnings per share reported for the period.",
    "free_cash_flow": "Operating cash flow less capital expenditure.",
    "fcf_per_share": "Free cash flow divided by diluted shares.",
    "roic": "After-tax operating profit divided by invested capital.",
    "roce": "Operating profit divided by capital employed.",
    "incremental_roic": "Change in operating profit after tax divided by change in invested capital.",
    "shares_diluted": "Weighted-average diluted shares for the period.",
    "stock_based_compensation": "Stock-based compensation expense.",
    "working_capital": "Operating current assets less operating current liabilities.",
    "capital_expenditure": "Cash investment in property, plant and equipment.",
    "owner_earnings": "Buffett owner earnings (Berkshire Hathaway 1986 letter): net income + D&A + change in working capital (cash-flow sign: negative when working capital absorbs cash) - maintenance capex (estimated as min(|capex|, D&A) when not reported).",
}


class FinancialTerminalService:
    def build(
        self,
        db: Session,
        company: Company,
        *,
        metrics: list[str] | None = None,
        years: int = 10,
        periodicity: str = "all",
    ) -> dict[str, Any]:
        requested = list(dict.fromkeys(metrics or DEFAULT_TERMINAL_METRICS))
        years = max(1, min(years, 20))
        if periodicity not in {"all", "annual", "quarterly"}:
            raise ValueError("periodicity must be all, annual or quarterly")
        facts = list(
            db.scalars(
                select(FinancialFact)
                .where(
                    FinancialFact.company_id == company.id,
                    FinancialFact.metric.in_(requested),
                )
                .order_by(
                    FinancialFact.metric,
                    desc(FinancialFact.fiscal_year),
                    desc(FinancialFact.created_at),
                )
            ).all()
        )
        calculated = list(
            db.scalars(
                select(CalculatedMetric)
                .where(
                    CalculatedMetric.company_id == company.id,
                    CalculatedMetric.metric.in_(requested),
                )
                .order_by(
                    CalculatedMetric.metric,
                    desc(CalculatedMetric.fiscal_year),
                    desc(CalculatedMetric.created_at),
                )
            ).all()
        )
        document_ids = {fact.source_id for fact in facts if fact.source_id}
        documents = {
            document.id: document
            for document in db.scalars(
                select(Document).where(Document.id.in_(document_ids))
            ).all()
        } if document_ids else {}
        latest_year = max(
            [row.fiscal_year for row in [*facts, *calculated] if row.fiscal_year],
            default=date.today().year,
        )
        earliest_year = latest_year - years + 1
        series: dict[str, list[dict[str, Any]]] = defaultdict(list)
        # Deduplicacion con criterio explicito: un (metrica, periodo, segmento)
        # tenia DOS filas cuando convivian el dato del filing (reported) y la
        # refundicion del proveedor (normalized) — MSFT/V mostraban dos
        # «Deuda total» distintas para el mismo FY. Gana la fuente con mejor
        # SOURCE_PRIORITY (filing regulador > vendor > manual), y a empate la
        # ingesta mas reciente. El segmento sigue en la identidad: una fila
        # por segmento, no por proveedor.
        best_fact: dict[tuple[str, str, str, str], tuple[float, ...]] = {}
        last_fact_id: dict[tuple[str, str, str, str], int] = {}
        for fact in facts:
            if fact.fiscal_year and fact.fiscal_year < earliest_year:
                continue
            frequency = self._frequency(fact.fiscal_quarter, fact.period)
            if periodicity != "all" and frequency != periodicity:
                continue
            document = documents.get(fact.source_id)
            segment = str((document.metadata_ or {}).get("segment") or "consolidated") if document else "consolidated"
            key = (fact.metric, fact.period, segment, frequency)
            rank = (
                SOURCE_PRIORITY.get(fact.source_type or "", 50),
                -(fact.created_at.timestamp() if fact.created_at else 0.0),
            )
            if key in best_fact and best_fact[key] <= rank:
                continue
            if key in best_fact:
                series[fact.metric] = [
                    row for row in series[fact.metric] if row["id"] != last_fact_id[key]
                ]
            best_fact[key] = rank
            last_fact_id[key] = fact.id
            series[fact.metric].append(
                {
                    "id": fact.id,
                    "period": fact.period,
                    "fiscal_year": fact.fiscal_year,
                    "fiscal_quarter": fact.fiscal_quarter,
                    "frequency": frequency,
                    "segment": segment,
                    "value": fact.value,
                    "unit": fact.unit,
                    "reported": fact.is_reported,
                    "adjusted": fact.is_adjusted,
                    "source": {
                        "type": fact.source_type,
                        "document_id": fact.source_id,
                        "title": document.title if document else None,
                        "url": document.source_url if document else None,
                    },
                    "confidence": fact.confidence,
                    "status": "reported" if fact.is_reported else "calculated",  # no-reportado = cifra derivada/calculada (FCF, margenes, acciones
                    # derivadas): la UI la marca "Calculado", nunca como publicada
                    "formula": None,
                    "definition_version": None,
                }
            )
        seen: set[tuple[str, str, str, str]] = set()
        for metric in calculated:
            if metric.fiscal_year and metric.fiscal_year < earliest_year:
                continue
            frequency = self._frequency(metric.fiscal_quarter, metric.period)
            if periodicity != "all" and frequency != periodicity:
                continue
            key = (metric.metric, metric.period, "consolidated", "calculated")
            if key in seen:
                continue
            seen.add(key)
            series[metric.metric].append(
                {
                    "id": metric.id,
                    "period": metric.period,
                    "fiscal_year": metric.fiscal_year,
                    "fiscal_quarter": metric.fiscal_quarter,
                    "frequency": frequency,
                    "segment": "consolidated",
                    "value": metric.value,
                    "unit": metric.unit,
                    "reported": False,
                    "adjusted": False,
                    "source": {
                        "type": "calculated_metric",
                        "source_fact_ids": metric.source_fact_ids,
                    },
                    "confidence": metric.confidence,
                    "status": metric.status,
                    "formula": metric.formula,
                    "definition_version": metric.definition_version,
                    "calculation_trace": metric.calculation_trace,
                }
            )
        # El motivo «FCF sin capex» necesita saber si hay CFO AUNQUE no se
        # haya pedido esa serie: consulta minima, solo cuando falta el FCF.
        ocf_available = False
        if "free_cash_flow" in requested and not series.get("free_cash_flow"):
            ocf_available = bool(
                db.scalar(
                    select(FinancialFact.id)
                    .where(
                        FinancialFact.company_id == company.id,
                        FinancialFact.metric == "operating_cash_flow",
                        *tenant_filters(db, FinancialFact),
                    )
                    .limit(1)
                )
            )
        available_metrics = {
            metric for metric in requested if series.get(metric)
        }
        metric_payloads = []
        for metric in requested:
            points = sorted(
                series.get(metric, []),
                key=lambda row: (
                    row["fiscal_year"] or 0,
                    self._quarter_order(row["fiscal_quarter"]),
                    row["period"],
                ),
            )
            # Solo es observación una fila con valor real. Una métrica
            # calculada sin entradas persiste su fila de trazabilidad
            # (value=None, a menudo period="unknown") para constar los
            # missing_inputs, pero NO es un dato: si cuenta, la tarjeta dice
            # «disponible / 1 periodo» sobre un cuerpo «Sin observaciones»
            # (ROIC de ASTS en prod) y los márgenes salen «disponible» con
            # único valor N/D. Status y periods se derivan de observaciones
            # válidas; la fila de trazabilidad sigue en BD.
            points = [row for row in points if row["value"] is not None]
            formula_spec = METRIC_DEFINITIONS.get(metric)
            metric_payloads.append(
                {
                    "metric": metric,
                    "definition": METRIC_DEFINITIONS_TEXT.get(
                        metric, metric.replace("_", " ").title()
                    ),
                    "canonical_formula": formula_spec[1] if formula_spec else None,
                    "definition_version": formula_spec[0] if formula_spec else None,
                    "status": "available" if points else "missing",
                    "missing_reason": self._missing_reason(
                        metric,
                        available=bool(points),
                        available_metrics=available_metrics,
                        ocf_available=ocf_available,
                        bank_like=_is_bank_like(company),
                    ),
                    "periods": len(points),
                    "segments": sorted({row["segment"] for row in points}),
                    "series": points,
                    "chart": {
                        "x": [row["period"] for row in points],
                        "y": [row["value"] for row in points],
                        "unit": next((row["unit"] for row in reversed(points)), None),
                    },
                }
            )
        available = sum(item["status"] == "available" for item in metric_payloads)
        return {
            "ticker": company.ticker,
            "company": company.name,
            "periodicity": periodicity,
            "years": years,
            "range": {"from_fiscal_year": earliest_year, "to_fiscal_year": latest_year},
            "metrics": metric_payloads,
            "coverage": {
                "requested": len(requested),
                "available": available,
                "percent": round(100 * available / len(requested), 1) if requested else 100,
                "missing": [
                    item["metric"] for item in metric_payloads if item["status"] == "missing"
                ],
            },
        }

    @staticmethod
    def _missing_reason(
        metric: str,
        *,
        available: bool,
        available_metrics: set[str],
        ocf_available: bool,
        bank_like: bool,
    ) -> str | None:
        """Por que falta una metrica, cuando se sabe decir sin inventar.

        QA datos (hallazgo 7): GOOGL/AMZN/JPM sin capex ni FCF aunque hay
        CFO. Dos casos distinguibles: FCF sin capex (no se deriva, no se
        sustituye por cero) y bancos sin capex desglosado en XBRL (JPM no
        lleva ningun tag de capex en companyfacts). Lo demas queda en la
        explicacion generica de «sin observaciones».
        """
        if available:
            return None
        if metric == "free_cash_flow" and ocf_available:
            return "Sin capex reportado: el FCF no se deriva sin capex (no se sustituye por cero)."
        if metric == "capital_expenditure" and bank_like:
            return "Los bancos no reportan capex desglosado en XBRL."
        return None

    @staticmethod
    def _frequency(quarter: str | None, period: str) -> str:
        return (
            "quarterly"
            if (quarter or "").upper().startswith("Q") or period.upper().startswith("Q")
            else "annual"
        )

    @staticmethod
    def _quarter_order(quarter: str | None) -> int:
        return {"Q1": 1, "Q2": 2, "Q3": 3, "Q4": 4, "FY": 5}.get(
            (quarter or "FY").upper(), 5
        )
