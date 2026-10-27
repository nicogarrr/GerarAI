from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import Company
from app.services.portfolio_image_import import ConfirmedImageRow, confirm_review, review_rows
from app.services.portfolio_image_ocr import extract_image

router = APIRouter()


class ImageInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # Base64 bounded before decode; keeps existing authenticated JSON transport.
    image_base64: str = Field(min_length=1, max_length=2_796_204)


class ReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    image_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    rows: list[ConfirmedImageRow] = Field(min_length=1, max_length=60)


class ConfirmInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    review_id: int = Field(gt=0)
    confirmed: bool


@router.post("/image/preview")
def preview(payload: ImageInput, db: Session = Depends(get_db)) -> dict:
    import base64
    import binascii

    if not db.info.get("tenant_id"):
        raise HTTPException(403, "Falta la sesión de cartera")
    try:
        data = base64.b64decode(payload.image_base64, validate=True)
        return extract_image(data)
    except (ValueError, binascii.Error) as exc:
        raise HTTPException(422, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc


@router.get("/image/instruments")
def instruments(q: str = Query(min_length=1, max_length=80), db: Session = Depends(get_db)) -> list[dict]:
    escaped = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    rows = db.scalars(select(Company).where(or_(Company.ticker.ilike(f"%{escaped}%", escape="\\"), Company.name.ilike(f"%{escaped}%", escape="\\")), Company.exchange != "UNKNOWN").order_by(Company.ticker).limit(12)).all()
    return [{"ticker": c.ticker, "name": c.name, "exchange": c.exchange, "currency": c.currency} for c in rows]


@router.post("/image/review")
async def review(payload: ReviewInput, db: Session = Depends(get_db)) -> dict:
    try:
        return await review_rows(db, payload.image_hash, payload.rows)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(422, str(exc)) from exc


@router.post("/image/confirm")
def confirm(payload: ConfirmInput, db: Session = Depends(get_db)) -> dict:
    try:
        return confirm_review(db, payload.review_id, payload.confirmed)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(422, str(exc)) from exc
