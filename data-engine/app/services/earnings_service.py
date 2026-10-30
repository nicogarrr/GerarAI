import re
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.errors import redact_secrets
from app.models import (
    CallClaim,
    Company,
    Document,
    DocumentChunk,
    EarningsRun,
    FinancialFact,
    ThesisChange,
    ThesisVersion,
    Transcript,
)
from app.services.claim_intelligence_service import ClaimIntelligenceService
from app.services.review_alert_service import ReviewAlertService

# Do not let prose separators swallow a sign, currency marker, or an
# accounting parenthesis. Unsupported accounting notation is omitted rather
# than staged as a positive candidate. Commas must be complete thousands groups.
_NUMBER = r"(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]+)?(?![0-9,]|\.[0-9])"
_MONEY = rf"((?:[+−-]?\s*\$?\s*|\$\s*[+−-]?\s*){_NUMBER})"
_SCALE = r"\s*(billion|million|bn|m)?"
METRIC_PATTERNS = {
    metric: rf"\b{label}\b[^0-9.$+−\-()]{{0,80}}{_MONEY}{_SCALE}"
    for metric, label in {
        "revenue": r"(?:revenue|sales)",
        "operating_income": "operating income",
        "net_income": "net income",
        "free_cash_flow": "free cash flow",
    }.items()
}
METRIC_PATTERNS.update({
    metric: rf"\b{label}\b[^0-9+−\-()]{{0,40}}([+−-]?\s*{_NUMBER})\s*%"
    for metric, label in {
        "gross_margin": "gross margin",
        "operating_margin": "operating margin",
    }.items()
})

POSITIVE_TONE = {
    "confident",
    "strong",
    "accelerating",
    "record",
    "outperform",
    "raised",
    "improving",
}
NEGATIVE_TONE = {
    "challenging",
    "uncertain",
    "headwind",
    "delay",
    "miss",
    "lowered",
    "weak",
}


def _scaled_value(raw: str, scale: str | None, metric: str) -> Decimal:
    value = Decimal(re.sub(r"[,$\s]", "", raw).replace("−", "-"))
    if metric.endswith("margin"):
        return value / Decimal("100")
    if scale and scale.lower() in {"billion", "bn"}:
        return value * Decimal("1000000000")
    if scale and scale.lower() in {"million", "m"}:
        return value * Decimal("1000000")
    return value


class EarningsWorkflowService:
    prompt_version = "earnings-workflow-v1"

    def run(
        self,
        db: Session,
        company: Company,
        *,
        fiscal_year: int,
        fiscal_quarter: str,
        document_ids: list[int] | None = None,
        force_new_thesis: bool = False,
    ) -> EarningsRun:
        run = EarningsRun(
            company_id=company.id,
            fiscal_year=fiscal_year,
            fiscal_quarter=fiscal_quarter,
            status="running",
            document_ids=document_ids or [],
            trace={
                "prompt_version": self.prompt_version,
                "started_at": datetime.now(UTC).isoformat(),
                "facts_are_staged": True,
            },
        )
        db.add(run)
        db.flush()
        try:
            documents = self._documents(
                db, company, fiscal_year, fiscal_quarter, document_ids or []
            )
            run.document_ids = [document.id for document in documents]
            text_by_document = self._document_text(db, documents)
            full_text = "\n\n".join(text_by_document.values())

            run.extracted_metrics = self._extract_metrics(
                full_text, text_by_document
            )
            run.comparisons = self._comparisons(
                db, company, fiscal_year, fiscal_quarter
            )
            statements = ClaimIntelligenceService().extract_statements(
                full_text, limit=40
            )
            run.guidance_changes = [
                {
                    "statement": item.text,
                    "confidence": item.confidence,
                    "source": "earnings_package",
                }
                for item in statements
                if any(
                    marker in item.text.lower()
                    for marker in (
                        "guidance",
                        "expects",
                        "forecast",
                        "outlook",
                        "target",
                    )
                )
            ][:12]
            run.management_tone = self._tone(full_text)
            run.promise_tracking = self._promise_tracking(
                db, company, full_text
            )
            run.risk_updates = [
                {"statement": item.text, "confidence": item.confidence}
                for item in statements
                if any(
                    marker in item.text.lower()
                    for marker in (
                        "risk",
                        "headwind",
                        "delay",
                        "uncertain",
                        "shortage",
                        "litigation",
                    )
                )
            ][:10]
            run.catalyst_updates = [
                {"statement": item.text, "confidence": item.confidence}
                for item in statements
                if any(
                    marker in item.text.lower()
                    for marker in (
                        "launch",
                        "approval",
                        "milestone",
                        "contract",
                        "rollout",
                        "commercial",
                    )
                )
            ][:10]

            claim_results = []
            intelligence = ClaimIntelligenceService()
            for document in documents:
                claim_results.append(
                    intelligence.scan_document(
                        db, document, auto_apply=True
                    )
                )
            run.claim_changes = claim_results

            latest_thesis = db.scalar(
                select(ThesisVersion)
                .where(ThesisVersion.company_id == company.id)
                .order_by(desc(ThesisVersion.version))
                .limit(1)
            )
            affected_claim_ids = sorted(
                {
                    suggestion_id
                    for result in claim_results
                    for suggestion_id in result.get("affected_claim_ids", [])
                }
            )
            materiality = min(
                10,
                5
                + int(bool(run.guidance_changes))
                + int(bool(run.risk_updates))
                + int(bool(run.extracted_metrics)),
            )
            change = ThesisChange(
                company_id=company.id,
                from_version_id=latest_thesis.id if latest_thesis else None,
                to_version_id=latest_thesis.id if latest_thesis else None,
                change_type="earnings_update",
                impact_direction=self._impact_direction(run),
                materiality_score=materiality,
                summary=(
                    f"{company.ticker} {fiscal_year} {fiscal_quarter}: resultados "
                    f"procesados con {len(run.extracted_metrics)} métricas candidatas, "
                    f"{len(run.guidance_changes)} comentarios sobre previsiones y "
                    f"{len(run.risk_updates)} actualizaciones de riesgos."
                ),
                affected_claim_ids=affected_claim_ids,
                affected_metrics=[
                    item["metric"] for item in run.extracted_metrics
                ],
                requires_review=True,
            )
            db.add(change)
            db.flush()
            run.thesis_change_id = change.id
            ReviewAlertService().create_from_change(
                db,
                change,
                metadata={
                    "earnings_run_id": run.id,
                    "document_ids": run.document_ids,
                },
            )

            valuation_trace: dict = {}
            try:
                from app.services.valuation_service import ValuationService

                valuation = ValuationService().value_company(db, company)
                model = ValuationService().persist_output(db, company, valuation)
                valuation_trace = {
                    "status": valuation.get("status"),
                    "publishable": valuation.get("publishable"),
                    "valuation_model_id": model.id if model else None,
                }
            except Exception as exc:
                valuation_trace = {
                    "status": "failed",
                    "error": redact_secrets(str(exc)),
                }

            new_thesis_id = None
            if force_new_thesis:
                try:
                    from app.services.thesis_service import ThesisService

                    thesis = ThesisService().generate(
                        db, company.ticker, force_new_version=True
                    )
                    new_thesis_id = thesis.id
                    change.to_version_id = thesis.id
                except Exception as exc:
                    run.trace = {
                        **run.trace,
                        "thesis_generation_error": redact_secrets(str(exc)),
                    }

            run.status = "completed"
            run.trace = {
                **run.trace,
                "completed_at": datetime.now(UTC).isoformat(),
                "documents": [
                    {
                        "id": document.id,
                        "source_type": document.source_type,
                        "published_at": (
                            document.published_at.isoformat()
                            if document.published_at
                            else None
                        ),
                    }
                    for document in documents
                ],
                "valuation": valuation_trace,
                "new_thesis_id": new_thesis_id,
                "extraction_policy": (
                    "Extracted metrics are candidates only; FinancialFact is not "
                    "updated until SEC/FMP/company-release reconciliation."
                ),
            }
            db.commit()
            db.refresh(run)
            return run
        except Exception as exc:
            run.status = "failed"
            run.error = redact_secrets(str(exc))
            run.trace = {
                **(run.trace or {}),
                "failed_at": datetime.now(UTC).isoformat(),
            }
            db.commit()
            db.refresh(run)
            return run

    def _documents(
        self,
        db: Session,
        company: Company,
        fiscal_year: int,
        fiscal_quarter: str,
        document_ids: list[int],
    ) -> list[Document]:
        if document_ids:
            documents = list(
                db.scalars(
                    select(Document).where(
                        Document.company_id == company.id,
                        Document.id.in_(document_ids),
                    )
                ).all()
            )
            if len(documents) != len(set(document_ids)):
                raise ValueError(
                    "One or more earnings documents were not found for this company"
                )
            return documents
        source_types = {
            "earnings_release",
            "earnings_deck",
            "earnings_call",
            "transcript",
            "manual_transcript",
            "10-q",
            "10-k",
        }
        candidates = db.scalars(
            select(Document)
            .where(
                Document.company_id == company.id,
                Document.source_type.in_(source_types),
            )
            .order_by(desc(Document.published_at))
            .limit(20)
        ).all()
        # Automatic selection must establish the whole requested period. A
        # matching year OR quarter includes other quarters/years and stages
        # their figures as if they belonged to the requested earnings run.
        matched = []
        for document in candidates:
            metadata = document.metadata_ or {}
            year = metadata.get("fiscal_year")
            quarter = metadata.get("fiscal_quarter")
            title = document.title or ""
            year_matches = (
                str(year) == str(fiscal_year) if year is not None
                else bool(re.search(rf"\b{re.escape(str(fiscal_year))}\b", title, re.IGNORECASE))
            )
            quarter_matches = (
                str(quarter).upper() == fiscal_quarter.upper() if quarter is not None
                else bool(re.search(rf"\b{re.escape(fiscal_quarter)}\b", title, re.IGNORECASE))
            )
            matches = year_matches and quarter_matches
            if matches:
                matched.append(document)
        if not matched:
            raise ValueError("No earnings documents confirmed for the requested fiscal period")
        return matched

    def _document_text(
        self, db: Session, documents: list[Document]
    ) -> dict[int, str]:
        result: dict[int, str] = {}
        for document in documents:
            chunks = db.scalars(
                select(DocumentChunk)
                .where(DocumentChunk.document_id == document.id)
                .order_by(DocumentChunk.chunk_index)
            ).all()
            result[document.id] = "\n".join(chunk.text for chunk in chunks)
        return result

    def _extract_metrics(
        self, full_text: str, text_by_document: dict[int, str]
    ) -> list[dict]:
        metrics: list[dict] = []
        for metric, pattern in METRIC_PATTERNS.items():
            for match in re.finditer(pattern, full_text, flags=re.IGNORECASE):
                value = _scaled_value(
                    match.group(1),
                    match.group(2) if match.lastindex and match.lastindex >= 2 else None,
                    metric,
                )
                source_id = next(
                    (
                        document_id
                        for document_id, text in text_by_document.items()
                        if match.group(0) in text
                    ),
                    None,
                )
                metrics.append(
                    {
                        "metric": metric,
                        "value": str(value),
                        "unit": "decimal" if metric.endswith("margin") else "USD",
                        "source_document_id": source_id,
                        "quote": match.group(0)[:300],
                        "status": "candidate_pending_reconciliation",
                    }
                )
                break
        return metrics

    def _comparisons(
        self,
        db: Session,
        company: Company,
        fiscal_year: int,
        fiscal_quarter: str,
    ) -> dict:
        facts = db.scalars(
            select(FinancialFact)
            .where(
                FinancialFact.company_id == company.id,
                FinancialFact.fiscal_year.in_([fiscal_year, fiscal_year - 1]),
            )
            .order_by(
                FinancialFact.metric,
                desc(FinancialFact.fiscal_year),
                desc(FinancialFact.created_at),
            )
        ).all()
        latest: dict[tuple[str, int, str | None], FinancialFact] = {}
        for fact in facts:
            latest.setdefault(
                (fact.metric, fact.fiscal_year or 0, fact.fiscal_quarter),
                fact,
            )
        comparisons: dict[str, dict] = {}
        for metric in {fact.metric for fact in facts}:
            current = latest.get((metric, fiscal_year, fiscal_quarter))
            yoy = latest.get((metric, fiscal_year - 1, fiscal_quarter))
            if not current:
                continue
            yoy_change = None
            if yoy and yoy.value != 0:
                yoy_change = (current.value - yoy.value) / abs(yoy.value)
            comparisons[metric] = {
                "current": str(current.value),
                "prior_year": str(yoy.value) if yoy else None,
                "yoy_change": str(yoy_change) if yoy_change is not None else None,
                "current_fact_id": current.id,
                "prior_year_fact_id": yoy.id if yoy else None,
            }
        return comparisons

    def _tone(self, text: str) -> dict:
        lowered = text.lower()
        positive = sum(lowered.count(term) for term in POSITIVE_TONE)
        negative = sum(lowered.count(term) for term in NEGATIVE_TONE)
        total = positive + negative
        score = (positive - negative) / total if total else 0
        return {
            "label": (
                "positive"
                if score > 0.2
                else "negative"
                if score < -0.2
                else "neutral"
            ),
            "score": round(score, 4),
            "positive_markers": positive,
            "negative_markers": negative,
            "method": "lexical_tone_v1",
        }

    def _promise_tracking(
        self, db: Session, company: Company, text: str
    ) -> list[dict]:
        claims = db.scalars(
            select(CallClaim)
            .join(Transcript, CallClaim.transcript_id == Transcript.id)
            .where(
                Transcript.company_id == company.id,
                CallClaim.follow_up_required.is_(True),
            )
            .order_by(desc(CallClaim.created_at))
            .limit(50)
        ).all()
        results = []
        for claim in claims:
            overlap = len(
                set(re.findall(r"[a-z0-9]+", claim.claim.lower()))
                & set(re.findall(r"[a-z0-9]+", text.lower()))
            )
            results.append(
                {
                    "call_claim_id": claim.id,
                    "promise": claim.claim,
                    "status": "possible_update" if overlap >= 3 else "unresolved",
                    "lexical_overlap": overlap,
                    "later_verified": claim.later_verified,
                }
            )
        return results

    def _impact_direction(self, run: EarningsRun) -> str:
        tone = (run.management_tone or {}).get("score", 0)
        if tone > 0.25 and not run.risk_updates:
            return "positive"
        if tone < -0.25 or len(run.risk_updates) >= 3:
            return "negative"
        return "mixed"
