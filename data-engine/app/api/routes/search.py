from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.pagination import PaginatedResponse
from app.services.universal_search_service import UniversalSearchService

router = APIRouter()


class UniversalSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    ticker: str | None = Field(default=None, max_length=20)
    entity_types: set[str] = Field(default_factory=set, max_length=20)
    source_types: set[str] = Field(default_factory=set, max_length=30)
    collection_id: int | None = None
    statuses: set[str] = Field(default_factory=set, max_length=20)
    date_from: date | None = None
    date_to: date | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)
    include_vector: bool = True


@router.post("")
def universal_search(
    payload: UniversalSearchRequest,
    db: Session = Depends(get_db),
) -> dict:
    try:
        result = UniversalSearchService().search(
            db,
            payload.query,
            ticker=payload.ticker,
            entity_types=payload.entity_types or None,
            source_types=payload.source_types or None,
            collection_id=payload.collection_id,
            statuses=payload.statuses or None,
            date_from=payload.date_from,
            date_to=payload.date_to,
            limit=payload.page_size,
            include_vector=payload.include_vector,
        )
        # Wrap in paginated response: search doesn't do SQL pagination,
        # it returns top N results after ranking
        paginated = PaginatedResponse.create(
            items=result["results"],
            total=result["total"],
            page=payload.page,
            page_size=payload.page_size,
        ).model_dump()
        # Preserve original search metadata
        paginated["query"] = result["query"]
        paginated["filters"] = result["filters"]
        paginated["retrieval"] = result["retrieval"]
        return paginated
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
