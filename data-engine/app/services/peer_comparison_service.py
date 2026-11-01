from datetime import date
from decimal import Decimal

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.core.tenancy import tenant_filters
from app.models import Company, FinancialFact, PeerRelationship
from app.services.metric_calculation_service import METRIC_DEFINITIONS, MetricCalculationService, MetricResult
from app.valuation.currency import resolve_fx

DEFAULT_PEER_METRICS = [
    "gross_margin",
    "operating_margin",
    "net_margin",
    "fcf_margin",
    "roe",
    "roa",
    "roic",
    "fcf_conversion",
    "net_debt_to_ebitda",
]


def _decimal_string(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


MIN_PEER_SAMPLE = 3


class PeerComparisonService:
    def __init__(self) -> None:
        self.metric_service = MetricCalculationService()

    def compare(
        self,
        db: Session,
        company: Company,
        limit: int = 8,
        metrics: list[str] | None = None,
        refresh: bool = False,
    ) -> dict:
        metric_names = [metric for metric in (metrics or DEFAULT_PEER_METRICS) if metric in METRIC_DEFINITIONS]
        peers, basis, selection_trace = self._find_peers(db, company, limit)
        participants = [company, *peers]
        rows = [self._company_row(db, participant, metric_names, participant.id == company.id, refresh) for participant in participants]

        # F26: un comparable sin ninguna metrica calculada (status ok) no es
        # muestra. peer_count solo cuenta los que aportan dato; el resto se
        # lista aparte para que la ausencia sea visible, nunca un 0.
        peer_rows = [row for row in rows if not row["is_target"]]
        with_data = [row for row in peer_rows if self._has_data(row)]
        without_data = [row["ticker"] for row in peer_rows if not self._has_data(row)]
        return {
            "ticker": company.ticker,
            "basis": basis,
            "selection_trace": selection_trace,
            "peer_count": len(with_data),
            "peer_count_selected": len(peers),
            "peers_without_data": without_data,
            "min_peer_sample": MIN_PEER_SAMPLE,
            "metrics": metric_names,
            "benchmarks": self._benchmarks(rows, metric_names),
            "companies": rows,
        }

    def _find_peers(
        self, db: Session, company: Company, limit: int
    ) -> tuple[list[Company], str, dict]:
        manual_rows = list(
            db.scalars(
                select(PeerRelationship)
                .where(
                    PeerRelationship.company_id == company.id,
                    PeerRelationship.selected.is_(True),
                )
                .order_by(desc(PeerRelationship.score))
            ).all()
        )
        manual_ids = [row.peer_company_id for row in manual_rows]
        manual_companies = (
            {
                peer.id: peer
                for peer in db.scalars(
                    select(Company).where(Company.id.in_(manual_ids))
                ).all()
            }
            if manual_ids
            else {}
        )
        selected: list[Company] = [
            manual_companies[peer_id]
            for peer_id in manual_ids
            if peer_id in manual_companies
        ][:limit]
        selected_ids = {peer.id for peer in selected} | {company.id}

        candidates = list(
            db.scalars(
                select(Company).where(Company.id != company.id)
            ).all()
        )
        # Una sola query de market cap para el target y TODOS los candidatos:
        # antes era una por compania del universo (maestro + stubs + IBKR) y
        # el coste de /peers crecia con el tamano de la tabla companies.
        market_caps = self._latest_market_caps_usd(
            db, [company.id, *(candidate.id for candidate in candidates)]
        )
        target_market_cap = market_caps.get(company.id)
        scored: list[tuple[float, Company, list[str], dict]] = []
        for candidate in candidates:
            if candidate.id in selected_ids:
                continue
            score, rationale, dimensions = self._peer_score(
                db,
                company,
                candidate,
                target_market_cap,
                candidate_market_cap=market_caps.get(candidate.id),
            )
            if score <= 0:
                continue
            scored.append((score, candidate, rationale, dimensions))
        scored.sort(key=lambda item: (-item[0], item[1].ticker))
        selected.extend(
            candidate
            for _, candidate, _, _ in scored[: max(0, limit - len(selected))]
        )
        selected_ids = {peer.id for peer in selected}
        trace_rows = [
            {
                "ticker": candidate.ticker,
                "score": round(score, 4),
                "selected": candidate.id in selected_ids,
                "rationale": rationale,
                "dimensions": dimensions,
            }
            for score, candidate, rationale, dimensions in scored
        ]
        for row in manual_rows:
            peer = manual_companies.get(row.peer_company_id)
            if peer:
                trace_rows.insert(
                    0,
                    {
                        "ticker": peer.ticker,
                        "score": float(row.score),
                        "selected": True,
                        "rationale": row.rationale or ["manual peer override"],
                        "dimensions": row.selection_trace or {},
                    },
                )
        basis = (
            "manual_then_multifactor"
            if manual_rows
            else "multifactor_business_model_stage_size"
        )
        return selected, basis, {
            "method": "PEER_SELECTION_V2",
            "target_market_cap": (
                str(target_market_cap) if target_market_cap is not None else None
            ),
            "candidates": trace_rows,
        }

    def _peer_score(
        self,
        db: Session,
        target: Company,
        candidate: Company,
        target_market_cap: Decimal | None,
        *,
        candidate_market_cap: Decimal | None = None,
    ) -> tuple[float, list[str], dict]:
        score = 0.0
        rationale: list[str] = []
        dimensions: dict[str, float] = {}
        if target.industry != "Unknown" and candidate.industry == target.industry:
            score += 0.30
            dimensions["industry"] = 1.0
            rationale.append("same industry")
        elif target.sector != "Unknown" and candidate.sector == target.sector:
            score += 0.14
            dimensions["sector"] = 1.0
            rationale.append("same sector")
        if candidate.company_type == target.company_type:
            score += 0.16
            dimensions["business_model"] = 1.0
            rationale.append("same company type")
        if candidate.valuation_model == target.valuation_model:
            score += 0.10
            dimensions["capital_profile"] = 1.0
            rationale.append("same valuation/capital profile")
        target_tags = set(target.factor_tags or [])
        candidate_tags = set(candidate.factor_tags or [])
        tag_union = target_tags | candidate_tags
        tag_similarity = (
            len(target_tags & candidate_tags) / len(tag_union)
            if tag_union
            else 0
        )
        score += 0.20 * tag_similarity
        dimensions["factor_tags"] = round(tag_similarity, 4)
        if tag_similarity:
            rationale.append(
                f"shared factors: {', '.join(sorted(target_tags & candidate_tags))}"
            )
        if candidate.currency == target.currency:
            score += 0.04
            dimensions["currency"] = 1.0
        if candidate.exchange == target.exchange:
            score += 0.03
            dimensions["exchange"] = 1.0

        if (
            target_market_cap is not None
            and target_market_cap > 0
            and candidate_market_cap is not None
            and candidate_market_cap > 0
        ):
            ratio = max(target_market_cap, candidate_market_cap) / min(
                target_market_cap, candidate_market_cap
            )
            size_score = max(0.0, 1.0 - min(float(ratio), 10.0) / 10.0)
            score += 0.17 * size_score
            dimensions["market_cap"] = round(size_score, 4)
            rationale.append(f"market-cap ratio {float(ratio):.2f}x")
        return score, rationale, dimensions

    def _latest_market_caps_usd(
        self, db: Session, company_ids: list[int]
    ) -> dict[int, Decimal]:
        """Ultimo market cap por compania pasado a USD para comparar tamaños.

        Cada hecho guarda su divisa (Finnhub en USD, el derivado en la de la
        empresa: JPY, EUR, GBX...). Comparar los valores tal cual ponia a
        Toyota (45 billones de JPY) 150 veces por encima de una empresa de
        300.000 M USD. Sin tipo de cambio valido, sin market cap (N/D).
        """
        today = date.today()
        rates: dict[str, Decimal | None] = {}
        out: dict[int, Decimal] = {}
        for fact in self._latest_market_cap_facts(db, company_ids):
            company_id, value = fact.company_id, fact.value
            code = _cap_currency(fact.unit)
            if not code:
                out[company_id] = value  # sin divisa: comportamiento previo
                continue
            if code not in rates:
                fx = resolve_fx(db, code, "USD", today)
                rates[code] = None if fx is None else Decimal(str(fx.rate))
            rate = rates[code]
            if rate is not None:
                out[company_id] = value * rate
        return out

    def _latest_market_caps(
        self, db: Session, company_ids: list[int]
    ) -> dict[int, Decimal]:
        """Ultimo market cap por compania (valor tal cual, ver ``_latest_market_cap_facts``)."""
        return {fact.company_id: fact.value for fact in self._latest_market_cap_facts(db, company_ids)}

    def _latest_market_cap_facts(
        self, db: Session, company_ids: list[int]
    ) -> list[FinancialFact]:
        """Ultimo market cap por compania en UNA query (sin N+1).

        Mismo criterio que ``_latest_market_cap``: ejercicio mas reciente
        (NULL al final) y, a igualdad, el hecho creado mas tarde. El ranking
        es una consulta de columnas, asi que lleva el filtro de tenant
        explicito (``tenant_filters``): un hecho de otro tenant no puede
        ocupar el puesto 1 y dejar a la compania sin valor.
        """
        if not company_ids:
            return []
        ranked = (
            select(
                FinancialFact.id,
                func.row_number()
                .over(
                    partition_by=FinancialFact.company_id,
                    order_by=(
                        FinancialFact.fiscal_year.desc().nullslast(),
                        desc(FinancialFact.created_at),
                        desc(FinancialFact.id),
                    ),
                )
                .label("rank"),
            )
            .where(
                FinancialFact.company_id.in_(set(company_ids)),
                FinancialFact.metric == "market_cap",
                *tenant_filters(db, FinancialFact),
            )
            .subquery()
        )
        return list(db.scalars(
            select(FinancialFact)
            .join(ranked, FinancialFact.id == ranked.c.id)
            .where(ranked.c.rank == 1)
        ).all())

    def _latest_market_cap(
        self, db: Session, company_id: int
    ) -> Decimal | None:
        fact = db.scalar(
            select(FinancialFact)
            .where(
                FinancialFact.company_id == company_id,
                FinancialFact.metric == "market_cap",
            )
            .order_by(
                FinancialFact.fiscal_year.desc().nullslast(),
                desc(FinancialFact.created_at),
            )
            .limit(1)
        )
        return fact.value if fact else None

    def _company_row(
        self,
        db: Session,
        company: Company,
        metric_names: list[str],
        is_target: bool,
        refresh: bool,
    ) -> dict:
        results = {
            result.metric: result
            for result in self.metric_service.calculate_all(db, company, persist=refresh)
            if result.metric in metric_names
        }
        return {
            "ticker": company.ticker,
            "name": company.name,
            "sector": company.sector,
            "industry": company.industry,
            "is_target": is_target,
            "metrics": {metric: self._metric_payload(results.get(metric)) for metric in metric_names},
        }

    def _metric_payload(self, result: MetricResult | None) -> dict:
        if result is None:
            return {
                "value": None,
                "status": "unavailable",
                "unit": "unknown",
                "period": "unknown",
                "confidence": "0.00",
                "source_fact_ids": [],
                "atypical": None,
            }
        # F153: la etiqueta de atipico y la traza viajan con el valor - un
        # margen real del 200% no puede presentarse como benchmark normal
        # sin advertencia ni numerador/denominador verificables.
        trace = result.calculation_trace or {}
        return {
            "value": _decimal_string(result.value),
            "status": result.status,
            "unit": result.unit,
            "period": result.period,
            "confidence": _decimal_string(result.confidence),
            "source_fact_ids": result.source_fact_ids,
            "atypical": trace.get("atypical"),
            "numerator": _decimal_string(result.numerator),
            "denominator": _decimal_string(result.denominator),
            "calculation_trace": trace,
        }

    @staticmethod
    def _has_data(row: dict) -> bool:
        return any(
            payload["status"] == "ok" and payload["value"] is not None
            for payload in row["metrics"].values()
        )

    def _benchmarks(self, rows: list[dict], metric_names: list[str]) -> dict:
        target = next((row for row in rows if row["is_target"]), None)
        benchmarks = {}
        for metric in metric_names:
            # F153: un valor atipico (etiquetado por el motor de metricas)
            # queda visible con su etiqueta pero NO entra en la
            # mediana/promedio - un margen real del 200% no distorsiona el
            # benchmark ni se presenta como lectura normal.
            peer_ok = [
                (row["ticker"], Decimal(payload["value"]), payload.get("atypical"))
                for row in rows
                if not row["is_target"]
                for payload in [row["metrics"][metric]]
                if payload["status"] == "ok" and payload["value"] is not None
            ]
            peer_values = [value for _, value, atypical in peer_ok if not atypical]
            excluded_atypical = [
                {"ticker": ticker, "value": _decimal_string(value), "atypical": atypical}
                for ticker, value, atypical in peer_ok
                if atypical
            ]
            target_payload = target["metrics"][metric] if target else None
            target_value = (
                Decimal(target_payload["value"])
                if target_payload and target_payload["status"] == "ok" and target_payload["value"] is not None
                else None
            )
            # F26: con n<3 una mediana es un unico comparable disfrazado de
            # estadistico. Se omite; el valor del target sigue visible.
            insufficient = len(peer_values) < MIN_PEER_SAMPLE
            peer_median = None if insufficient else self._median(peer_values)
            benchmarks[metric] = {
                "peer_median": _decimal_string(peer_median),
                "peer_average": None
                if insufficient
                else _decimal_string(sum(peer_values) / len(peer_values)),
                "peer_sample_size": len(peer_values),
                "insufficient_sample": insufficient,
                "note": f"muestra insuficiente (n<{MIN_PEER_SAMPLE})" if insufficient else None,
                "excluded_atypical": excluded_atypical,
                "target_value": _decimal_string(target_value),
                "target_atypical": (target_payload or {}).get("atypical"),
                "target_vs_peer_median": _decimal_string(target_value - peer_median)
                if target_value is not None and peer_median is not None
                else None,
            }
        return benchmarks

    def _median(self, values: list[Decimal]) -> Decimal | None:
        if not values:
            return None
        sorted_values = sorted(values)
        midpoint = len(sorted_values) // 2
        if len(sorted_values) % 2:
            return sorted_values[midpoint]
        return (sorted_values[midpoint - 1] + sorted_values[midpoint]) / Decimal("2")


def _cap_currency(unit: str | None) -> str:
    """«USD», «iso4217:JPY», «GBX» -> codigo de divisa (sin perder la subunidad)."""
    text = (unit or "").strip()
    if text.lower().startswith("iso4217:"):
        text = text[len("iso4217:"):]
    return text.split("/", 1)[0].strip()
