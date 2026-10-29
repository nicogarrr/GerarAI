from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, NamedTuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import batch_refresh
from app.core.tenancy import tenant_filters
from app.llm import LLMRequest, Message, ResponseFormat, parse_json_response
from app.llm.base import LLMProvider
from app.llm.factory import create_llm_provider
from app.models import (
    Company,
    CompanyKPI,
    Document,
    DocumentChunk,
    FactRevision,
    FinancialFact,
    KPIExtractionCandidate,
)
from app.services.budget import BudgetController, BudgetExceededError
from app.services.company_framework import resolve_company_framework
from app.services.langfuse_client import LangfuseTracer
from app.services.number_parsing import (
    find_number_tokens,
    find_number_tokens_with_units,
    parse_localized_number,
)
from app.services.prompt_registry import get_prompt

PROMPT_VERSION = get_prompt("company_kpi_extraction", allow_remote=False).version

# Magnitude words, most specific first, in the two locales the sources use.
# The Spanish plural is not a nicety here: "millones" is how a CNMV/ESEF filing
# writes it, and the previous English-only pattern matched none of it, so
# "3.456,7 millones" was stored as 3.456.700 and the model was shown a number
# a thousand times below reality. "billón" is the Spanish long scale (1e12),
# never 1e9, so guessing it the other way would be a 1000x error in reverse.
_UNIT_SCALES: tuple[tuple[re.Pattern[str], Decimal], ...] = (
    (
        re.compile(r"\b(bill[oó]n(?:es)?|trill[oó]n(?:es)?|trillion(?:s)?)\b"),
        Decimal("1e12"),
    ),
    (re.compile(r"\b(billion(?:s)?|bn|b|mil millones)\b"), Decimal("1e9")),
    (re.compile(r"\b(mill[oó]n(?:es)?|million(?:s)?|mm|mn|m)\b"), Decimal("1e6")),
    (re.compile(r"\b(thousand(?:s)?|mil(?:es)?|k)\b"), Decimal("1e3")),
)
# Percentages arrive as "%" or, in a Spanish filing, "por ciento"/"%".
_PERCENT_UNITS = re.compile(r"%|percent|por\s+ciento|pct")



class _QuoteFigure(NamedTuple):
    """One figure a quote states, tied to its own sign and explicit unit.

    The grounding check used to flatten every number in the quote to its
    absolute value and then accept any ratio in 1e-9..1e9, so "Ingresos
    FY2025: 100 millones" vouched for 2.025.000.000 (the year, at a tolerated
    scale) and for -100.000.000 (the sign, dropped). A figure can only vouch
    for the value its own unit produces: "100 millones" supports 100.000.000
    and nothing else.
    """

    value: Decimal
    scale: Decimal
    percent: bool
    year_like: bool


def _value_token(raw_value: str) -> str | None:
    """The figure of a raw value, ignoring any label text around it.

    A raw value is not always a bare number: it can be "Ingresos FY24: 1.234,5
    M€" or "margen del 12,5%". Taking the first digits would publish the fiscal
    year as the KPI, so the token with the most significant digits wins and
    ties keep the leftmost figure. A wrong guess is no longer silent: whatever
    is picked must still be grounded in the quote, so it degrades to
    ``needs_review`` instead of reaching a canonical fact.
    """
    best: tuple[int, int, str] | None = None
    for index, token in enumerate(find_number_tokens(raw_value)):
        digits = sum(1 for char in token if char.isdigit())
        if not digits:
            continue
        if best is None or digits > best[0]:
            best = (digits, -index, token)
    return best[2] if best else None

RATE_KEYS = {
    "penetration", "revenue_share", "utilization", "take_rate", "churn",
    "retention", "backlog_conversion", "fee_rate", "cash_yield", "occupancy",
    "royalty_rate", "premium_growth", "return_on_tangible_equity", "roe",
    "combined_ratio", "net_interest_margin", "cet1_ratio", "organic_growth",
}
COUNT_MARKERS = (
    "accounts", "subscribers", "customers", "seats", "launches", "satellites",
    "units", "agreements", "trips",
)
MONEY_KEYS = {
    "revenue", "tpv", "arr", "aum", "backlog", "asset_value", "nav",
    "holdco_debt", "earned_premiums", "investment_income", "net_operating_income",
    "tangible_book_value", "book_value",
}


def _key(value: str) -> str:
    return (
        value.strip().lower().replace("&", "and").replace("/", "_")
        .replace("-", "_").replace(" ", "_")
    )


class CompanyKPIRegistryService:
    def sync(
        self, db: Session, company: Company, *, commit: bool = True
    ) -> list[CompanyKPI]:
        framework = resolve_company_framework(company)
        revenue = {_key(item) for item in framework.revenue_drivers}
        required = {_key(item) for item in framework.required_fact_metrics}
        labels = list(
            dict.fromkeys(
                framework.revenue_drivers
                + framework.kpis
                + framework.required_fact_metrics
            )
        )
        rows: list[CompanyKPI] = []
        active_keys: set[str] = set()
        for label in labels:
            metric_key = _key(label)
            # Dos etiquetas del marco pueden normalizar a la misma clave
            # («ARR» y «arr»): una sola fila por clave. Sin esto la segunda
            # creaba otra CompanyKPI pendiente (sin autoflush la búsqueda no
            # ve la primera) y el flush rompía el UNIQUE con un 500.
            if metric_key in active_keys:
                continue
            active_keys.add(metric_key)
            row = db.scalar(
                select(CompanyKPI).where(
                    CompanyKPI.company_id == company.id,
                    CompanyKPI.metric_key == metric_key,
                )
            )
            if row is None:
                row = CompanyKPI(company_id=company.id, metric_key=metric_key)
                db.add(row)
            row.display_name = label.replace("_", " ").strip().title()
            row.aliases = list(
                dict.fromkeys(
                    [label, label.replace("_", " "), metric_key, metric_key.upper()]
                )
            )
            row.canonical_unit = self._unit(metric_key, company.currency)
            row.driver_type = "revenue_driver" if metric_key in revenue else "kpi"
            row.required = metric_key in required
            row.active = True
            row.registry_version = f"{framework.key}-v1"
            row.metadata_ = {
                "framework": framework.key,
                "formula_role": row.driver_type,
                "approval_policy": "human_approval_required",
            }
            rows.append(row)
        existing = db.scalars(
            select(CompanyKPI).where(CompanyKPI.company_id == company.id)
        ).all()
        for row in existing:
            if row.metric_key not in active_keys:
                row.active = False
        db.flush()
        if commit:
            db.commit()
            batch_refresh(db, rows)
        return rows

    @staticmethod
    def _unit(metric: str, currency: str) -> str:
        if metric in RATE_KEYS or metric.endswith(("_margin", "_rate", "_ratio")):
            return "decimal"
        if metric in MONEY_KEYS:
            return currency
        if any(marker in metric for marker in COUNT_MARKERS):
            return "count"
        if metric.startswith("price") or metric.endswith(("_price", "_arpu")):
            return f"{currency}_per_unit"
        return "unknown"


class KPIExtractionService:
    def __init__(self, provider: LLMProvider | None = None) -> None:
        self.provider = provider or create_llm_provider()

    async def extract_document(
        self,
        db: Session,
        document: Document,
        *,
        commit: bool = True,
    ) -> list[KPIExtractionCandidate]:
        if document.company_id is None:
            raise ValueError("KPI extraction requires a company-specific document")
        company = db.get(Company, document.company_id)
        if company is None:
            raise ValueError("Document company no longer exists")
        registry = CompanyKPIRegistryService().sync(db, company, commit=False)
        chunks = list(
            db.scalars(
                select(DocumentChunk)
                .where(DocumentChunk.document_id == document.id)
                .order_by(DocumentChunk.chunk_index)
                .limit(30)
            ).all()
        )
        if not chunks:
            return []
        try:
            from app.services.jev_gates import kpi_chunk_keep_flags

            keep_flags = await kpi_chunk_keep_flags([chunk.text for chunk in chunks])
        except Exception:  # noqa: BLE001 — Jev best-effort: sin filtro, como hoy
            keep_flags = None
        if keep_flags is not None:
            chunks = [
                chunk for chunk, keep in zip(chunks, keep_flags) if keep
            ]
            if not chunks:
                # Jev no ve senal KPI en ningun chunk: se ahorra la llamada LLM.
                return []
        chunk_map = {chunk.id: chunk for chunk in chunks}
        source_text = "\n\n".join(
            f"[chunk:{chunk.id}]\n{chunk.text}" for chunk in chunks
        )[:30000]
        metric_keys = [row.metric_key for row in registry if row.active]
        schema = self._schema(metric_keys)
        budget = BudgetController()
        if not budget.can_spend(db, 0.02):
            raise BudgetExceededError("LLM budget exhausted")
        request = LLMRequest(
                messages=[
                    Message(
                        "system",
                        get_prompt("company_kpi_extraction").text,
                    ),
                    Message(
                        "user",
                        json.dumps(
                            {
                                "company": {"ticker": company.ticker, "name": company.name},
                                "registry": [
                                    {
                                        "metric_key": row.metric_key,
                                        "aliases": row.aliases,
                                        "canonical_unit": row.canonical_unit,
                                        "required": row.required,
                                    }
                                    for row in registry
                                ],
                                "document": {
                                    "id": document.id,
                                    "title": document.title,
                                    "source_type": document.source_type,
                                },
                                "chunks": source_text,
                            },
                            ensure_ascii=False,
                        ),
                    ),
                ],
                task="kpi_extraction",
                temperature=0,
                max_tokens=4000,
                reasoning_effort=get_settings().reasoning_effort_for("extraccion"),
                response_format=ResponseFormat.json_schema(
                    schema, name="company_kpi_observations", strict=True
                ),
                metadata={"prompt_version": PROMPT_VERSION},
            )
        with LangfuseTracer().workflow(
            "CompanyKPIExtraction",
            {
                "workflow": "company_kpi_extraction",
                "prompt_version": PROMPT_VERSION,
                "retrieval_set": [f"document_chunk:{chunk.id}" for chunk in chunks],
                "tools": [],
                "escalation": False,
            },
        ) as llm_trace:
            try:
                response = await self.provider.complete(request)
                payload = parse_json_response(response.text)
                cost = budget.estimate_cost_eur(
                    response.model,
                    response.usage.input_tokens,
                    response.usage.output_tokens,
                )
                budget.record(
                    db,
                    response.model,
                    "company_kpi_extraction",
                    cost,
                    response.usage.total_tokens,
                    commit=False,
                )
                if not isinstance(payload, dict) or not isinstance(payload.get("observations"), list):
                    raise ValueError("Invalid KPI extraction response")
                confidence_values = [
                    float(item.get("confidence") or 0)
                    for item in payload["observations"]
                    if isinstance(item, dict)
                ]
                llm_trace.update(
                    model=response.model,
                    provider=response.provider,
                    input_tokens=response.usage.input_tokens,
                    output_tokens=response.usage.output_tokens,
                    cache_read_tokens=response.usage.cache_read_tokens,
                    cache_write_tokens=response.usage.cache_write_tokens,
                    cost=cost,
                    citations=len(payload["observations"]),
                    json_validity=True,
                    fallback=False,
                    evaluation_score=(
                        sum(confidence_values) / len(confidence_values)
                        if confidence_values
                        else 1.0
                    ),
                )
                llm_trace.output = {
                    "observations": len(payload["observations"]),
                    "json_validity": True,
                }
            except Exception as exc:
                llm_trace.update(
                    provider=getattr(self.provider, "name", "unknown"),
                    json_validity=False,
                    fallback=False,
                    error=type(exc).__name__,
                )
                raise
        registry_by_key = {row.metric_key: row for row in registry}
        created: list[KPIExtractionCandidate] = []
        for observation in payload["observations"]:
            if not isinstance(observation, dict):
                continue
            metric_key = str(observation.get("metric_key") or "")
            kpi = registry_by_key.get(metric_key)
            chunk_id = self._integer(observation.get("chunk_id"))
            chunk = chunk_map.get(chunk_id)
            if kpi is None or chunk is None:
                continue
            quote = str(observation.get("quote") or "").strip()
            locator_valid = bool(quote) and self._contains_quote(chunk.text, quote)
            raw_value = str(observation.get("raw_value") or "").strip()
            raw_unit = str(observation.get("raw_unit") or "unknown").strip()
            normalized, normalization_trace = self._normalize(
                raw_value, raw_unit, kpi.canonical_unit
            )
            fiscal_year = self._integer(observation.get("fiscal_year"))
            fiscal_quarter = str(observation.get("fiscal_quarter") or "FY").upper()
            period = str(observation.get("period") or "").strip() or (
                f"{fiscal_quarter}{fiscal_year}" if fiscal_year else "unknown"
            )
            period_valid = fiscal_quarter in {"Q1", "Q2", "Q3", "Q4", "FY"} and fiscal_year is not None
            # The value must be grounded in the quote, not just alongside it.
            # `locator_valid` only proved the SENTENCE was in the chunk, so a
            # model could return a verbatim quote and an unrelated number, and
            # `approve()` then wrote that number as a canonical reported fact.
            figures = self._quote_figures(quote)
            grounded = {figure.value for figure in figures}
            value_in_quote = bool(figures)
            value_matches_quote = (
                normalized is not None
                and bool(figures)
                and self._value_supported(normalized, figures, kpi.canonical_unit)
            )
            reconciliation = (
                "reconciled"
                if locator_valid and value_matches_quote and value_in_quote and period_valid
                else "needs_review"
            )
            status = "pending_approval" if reconciliation == "reconciled" else "needs_review"
            existing = db.scalar(
                select(KPIExtractionCandidate).where(
                    KPIExtractionCandidate.document_id == document.id,
                    KPIExtractionCandidate.document_chunk_id == chunk.id,
                    KPIExtractionCandidate.metric_key == metric_key,
                    KPIExtractionCandidate.period == period,
                    KPIExtractionCandidate.raw_value == raw_value,
                )
            )
            if existing is not None:
                created.append(existing)
                continue
            confidence = max(0.0, min(1.0, float(observation.get("confidence") or 0)))
            candidate = KPIExtractionCandidate(
                company_id=company.id,
                company_kpi_id=kpi.id,
                document_id=document.id,
                document_chunk_id=chunk.id,
                metric_key=metric_key,
                raw_label=str(observation.get("raw_label") or metric_key)[:240],
                raw_value=raw_value[:160],
                raw_unit=raw_unit[:80],
                normalized_value=normalized,
                canonical_unit=kpi.canonical_unit,
                period=period[:40],
                fiscal_year=fiscal_year,
                fiscal_quarter=fiscal_quarter if period_valid else None,
                source_locator={"chunk_id": chunk.id, "quote": quote},
                reconciliation_status=reconciliation,
                status=status,
                confidence=Decimal(str(confidence)),
                extraction_model=response.model,
                prompt_version=PROMPT_VERSION,
                trace={
                    "provider": response.provider,
                    "request_id": response.request_id,
                    "locator_verified": locator_valid,
                    "value_grounded": value_matches_quote,
                    "figures_in_quote": sorted(str(value) for value in grounded),
                    "period_valid": period_valid,
                    "normalization": normalization_trace,
                    "input_tokens": response.usage.input_tokens,
                    "output_tokens": response.usage.output_tokens,
                },
            )
            db.add(candidate)
            created.append(candidate)
        db.flush()
        if commit:
            db.commit()
            batch_refresh(db, created)
        return created

    def approve(
        self,
        db: Session,
        candidate: KPIExtractionCandidate,
        *,
        actor: str,
    ) -> FinancialFact:
        if candidate.status != "pending_approval" or candidate.normalized_value is None:
            raise ValueError("Only reconciled pending candidates can be approved")
        document = db.get(Document, candidate.document_id)
        if document is None:
            raise ValueError("Source document no longer exists")
        fact = db.scalar(
            select(FinancialFact)
            .where(
                FinancialFact.company_id == candidate.company_id,
                FinancialFact.metric == candidate.metric_key,
                FinancialFact.period == candidate.period,
            )
            .order_by(FinancialFact.id.desc())
        )
        if fact is None:
            fact = FinancialFact(
                company_id=candidate.company_id,
                metric=candidate.metric_key,
                value=candidate.normalized_value,
                unit=candidate.canonical_unit,
                period=candidate.period,
                fiscal_year=candidate.fiscal_year,
                fiscal_quarter=candidate.fiscal_quarter,
                source_id=candidate.document_id,
                source_type=document.source_type,
                is_reported=True,
                is_adjusted=False,
                confidence=candidate.confidence,
            )
            db.add(fact)
            db.flush()
        elif fact.value != candidate.normalized_value:
            previous_value = fact.value
            latest_version = db.scalar(
                select(func.max(FactRevision.canonical_version)).where(
                    FactRevision.financial_fact_id == fact.id,
                    *tenant_filters(db, FactRevision),
                )
            )
            revision = FactRevision(
                financial_fact_id=fact.id,
                candidate_id=candidate.id,
                previous_value=previous_value,
                new_value=candidate.normalized_value,
                reason="Approved KPI candidate contradicts the current canonical fact",
                source={
                    "document_id": candidate.document_id,
                    "document_chunk_id": candidate.document_chunk_id,
                    "document_source_type": document.source_type,
                    "source_locator": candidate.source_locator,
                    "candidate_id": candidate.id,
                },
                approved_by=actor,
                superseded_at=datetime.now(UTC),
                canonical_version=int(latest_version or 0) + 1,
                status="approved",
            )
            db.add(revision)
            fact.value = candidate.normalized_value
            fact.unit = candidate.canonical_unit
            fact.fiscal_year = candidate.fiscal_year
            fact.fiscal_quarter = candidate.fiscal_quarter
            fact.source_id = candidate.document_id
            fact.source_type = document.source_type
            fact.confidence = candidate.confidence
        candidate.status = "approved"
        candidate.approved_by = actor
        candidate.approved_at = datetime.now(UTC)
        candidate.canonical_fact_id = fact.id
        db.commit()
        db.refresh(fact)
        return fact

    @staticmethod
    def reject(db: Session, candidate: KPIExtractionCandidate, *, actor: str) -> None:
        if candidate.status == "approved":
            raise ValueError("Approved observations cannot be rejected")
        candidate.status = "rejected"
        candidate.approved_by = actor
        candidate.approved_at = datetime.now(UTC)
        db.commit()

    @staticmethod
    def _normalize(
        raw_value: str, raw_unit: str, canonical_unit: str
    ) -> tuple[Decimal | None, dict[str, Any]]:
        """Parse a KPI value and scale it to the canonical unit.

        Three defects lived here:

        * ``replace(",", "")`` destroyed the Spanish decimal comma, so
          "3.456,7" became 3.4567 and, with a "millones" unit, 3.456.700
          instead of 3.456.700.000: a 1000x error that ``_contains_quote``
          happily accepted, because the quote WAS verbatim in the chunk.
        * The scale multiplier was searched in ``raw_value + raw_unit``, so a
          bare "b" or "m" inside the value text triggered 1e9 / 1e6.
        * Nothing tied the number to the quote at all, so a verbatim sentence
          could vouch for an unrelated figure. The value is now verified against
          the figures the quote states (see :meth:`_quote_figures`).
        """
        # Extract the numeric token first: the raw value routinely carries a
        # unit suffix ("12.5%", "3.456,7 M€") that is not part of the number.
        # The token is then parsed with the locale-aware parser, so "3.456,7"
        # keeps its meaning instead of collapsing to 3.4567.
        token = _value_token(raw_value)
        if not token:
            return None, {"status": "invalid_number", "raw_value": raw_value}
        parsed = parse_localized_number(token)
        if parsed is None:
            return None, {"status": "invalid_number", "raw_value": raw_value}
        value, negative = parsed
        if negative:
            value = -abs(value)

        # The scale comes from the UNIT only. Reading it from the value text
        # meant "4,2 B" became 42 billion and any stray letter changed the
        # magnitude by a factor of a million.
        unit_text = (raw_unit or "").strip().lower()
        multiplier = Decimal("1")
        for pattern, scale in _UNIT_SCALES:
            if pattern.search(unit_text):
                multiplier = scale
                break
        value *= multiplier
        percent = bool(_PERCENT_UNITS.search(unit_text))
        if canonical_unit == "decimal" and percent:
            value /= Decimal("100")
        return value, {
            "status": "normalized",
            "unit_text": unit_text,
            "multiplier": str(multiplier),
            "percent_to_decimal": canonical_unit == "decimal" and percent,
            "scale_source": "unit_only",
        }

    @staticmethod
    def _contains_quote(text: str, quote: str) -> bool:
        normalize = lambda value: " ".join(value.lower().split())
        return normalize(quote) in normalize(text)

    @staticmethod
    def _quote_figures(quote: str) -> list[_QuoteFigure]:
        """Every figure the quote states, with its own sign and unit attached.

        A quote of "los ingresos del ejercicio" carries no figure, so it cannot
        vouch for any number. A quote that does carry figures vouches only for
        what those figures say: each token keeps its sign (accounting
        parentheses included), picks up the scale of the unit written right
        after it ("100 millones" -> 100 x 1e6, "12,5%" -> a rate), and a bare
        calendar year is marked ``year_like`` so "FY2025" can never stand in
        for the KPI of the sentence.
        """
        if not quote:
            return []
        figures: list[_QuoteFigure] = []
        for token, context in find_number_tokens_with_units(quote):
            parsed = parse_localized_number(token)
            if parsed is None:
                continue
            value, negative = parsed
            if negative:
                value = -abs(value)
            unit_text = context.lower()
            scale = Decimal("1")
            for pattern, candidate in _UNIT_SCALES:
                if pattern.search(unit_text):
                    scale = candidate
                    break
            percent = bool(_PERCENT_UNITS.search(unit_text))
            year_like = (
                scale == 1
                and not percent
                and value == value.to_integral_value()
                and Decimal("1900") <= abs(value) <= Decimal("2099")
            )
            figures.append(
                _QuoteFigure(value=value, scale=scale, percent=percent, year_like=year_like)
            )
        return figures

    @staticmethod
    def _value_supported(
        reported: Decimal, figures: list[_QuoteFigure], canonical_unit: str
    ) -> bool:
        """Whether the reported value matches a figure the quote states.

        The match is exact against the value the figure's own unit produces,
        never against a global ladder of tolerated scales: "1.234,5 millones"
        supports 1.234.500.000 because the quote says "millones". The sign
        must agree, so "(100) millones" supports -100.000.000 and never
        +100.000.000, and a ``year_like`` figure supports nothing.

        A percentage figure follows the canonical unit of the KPI, because a
        rate is stored as a fraction: with canonical unit "decimal", "12,5%"
        supports 0.125 and ONLY 0.125 - accepting the points as written
        vouched a reported 12,5 (1250%) for a rate the document stated at
        12,5%, a 100x error that reached pending_approval when the raw unit
        arrived as "unknown". The tolerance only covers rounding in the last
        digit the quote carries.
        """
        for figure in figures:
            if figure.year_like:
                continue
            if figure.value == 0:
                if reported == 0:
                    return True
                continue
            if (reported < 0) != (figure.value < 0):
                continue
            magnitude = abs(figure.value)
            if figure.percent:
                expected = (
                    {magnitude / Decimal("100")}
                    if canonical_unit == "decimal"
                    else {magnitude}
                )
            else:
                expected = {magnitude * figure.scale}
            for candidate in expected:
                if candidate == 0:
                    continue
                if abs(abs(reported) / candidate - Decimal(1)) <= Decimal("0.001"):
                    return True
        return False

    @staticmethod
    def _integer(value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _schema(metric_keys: list[str]) -> dict[str, Any]:
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "observations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "metric_key": {"type": "string", "enum": metric_keys},
                            "raw_label": {"type": "string"},
                            "raw_value": {"type": "string"},
                            "raw_unit": {"type": "string"},
                            "period": {"type": "string"},
                            "fiscal_year": {"type": "integer"},
                            "fiscal_quarter": {"type": "string", "enum": ["Q1", "Q2", "Q3", "Q4", "FY"]},
                            "chunk_id": {"type": "integer"},
                            "quote": {"type": "string"},
                            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                        },
                        "required": [
                            "metric_key", "raw_label", "raw_value", "raw_unit",
                            "period", "fiscal_year", "fiscal_quarter", "chunk_id",
                            "quote", "confidence",
                        ],
                    },
                }
            },
            "required": ["observations"],
        }
