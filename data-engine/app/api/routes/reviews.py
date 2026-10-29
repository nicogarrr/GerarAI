from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import (
    Document,
    NewsEvent,
    ResearchReview,
)
from app.schemas import (
    ContradictionScanRequest,
    ResearchReviewOut,
    ResearchReviewUpdate,
)
from app.services.claim_intelligence_service import ClaimIntelligenceService
from app.services.company_resolver import resolve_company
from app.services.review_alert_service import ReviewAlertService

router = APIRouter()


@router.get("", response_model=list[ResearchReviewOut])
def list_reviews(
    ticker: str | None = None,
    status: str | None = "open",
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[ResearchReview]:
    statement = select(ResearchReview)
    if ticker:
        company = resolve_company(db, ticker)
        if not company:
            raise HTTPException(status_code=404, detail="Company not found")
        statement = statement.where(ResearchReview.company_id == company.id)
    if status:
        statement = statement.where(ResearchReview.status == status)
    return list(
        db.scalars(
            statement.order_by(
                desc(ResearchReview.created_at)
            ).limit(limit)
        ).all()
    )


@router.patch("/{review_id}", response_model=ResearchReviewOut)
def update_review(
    review_id: int,
    payload: ResearchReviewUpdate,
    db: Session = Depends(get_db),
) -> ResearchReview:
    review = db.get(ResearchReview, review_id)
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")
    ReviewAlertService().transition_review(
        review,
        status=payload.status,
        resolution_notes=payload.resolution_notes,
    )
    db.commit()
    db.refresh(review)
    return review


@router.post("/contradictions/scan")
def scan_contradictions(
    payload: ContradictionScanRequest,
    db: Session = Depends(get_db),
) -> dict:
    company = resolve_company(db, payload.ticker)
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    intelligence = ClaimIntelligenceService()
    if payload.document_id is not None:
        document = db.scalar(
            select(Document).where(
                Document.id == payload.document_id,
                Document.company_id == company.id,
            )
        )
        if not document:
            raise HTTPException(status_code=404, detail="Document not found")
        return intelligence.scan_document(
            db, document, auto_apply=payload.create_reviews
        )
    if payload.news_event_id is not None:
        news = db.scalar(
            select(NewsEvent).where(
                NewsEvent.id == payload.news_event_id,
                NewsEvent.company_id == company.id,
            )
        )
        if not news:
            raise HTTPException(status_code=404, detail="News event not found")
        return intelligence.scan_text(
            db,
            company=company,
            text=f"{news.title}. {news.summary}",
            source_type=news.source,
            source_url=news.url,
            source_reference={"type": "news_event", "id": news.id},
            auto_apply=payload.create_reviews,
        )
    return intelligence.scan_stale_claims(db, company)
