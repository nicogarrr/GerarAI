"""Handlers /image/preview, /image/review y /image/confirm: errores y sesion.

Cubre los caminos que el test del buscador de instrumentos no toca: la
sesion de cartera obligatoria en preview, el 422 de base64 invalido, el 503
cuando el OCR no esta disponible y los 422 con rollback de review/confirm.
"""
from __future__ import annotations

import asyncio
import base64

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.routes import portfolio_images
from app.api.routes.portfolio_images import (
    ConfirmInput,
    ImageInput,
    ReviewInput,
    confirm,
    preview,
    review,
)
from app.models.entities import Base


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with sessionmaker(engine)() as db:
        yield db
    engine.dispose()


def test_preview_exige_sesion_de_cartera(db):
    payload = ImageInput(image_base64=base64.b64encode(b"img").decode())
    with pytest.raises(HTTPException) as exc:
        preview(payload, db=db)
    assert exc.value.status_code == 403


def test_preview_base64_invalido_es_422(db):
    db.info["tenant_id"] = 1
    # min_length=1 pasa la validacion pydantic pero no es base64.
    payload = ImageInput.model_construct(image_base64="!!!")
    with pytest.raises(HTTPException) as exc:
        preview(payload, db=db)
    assert exc.value.status_code == 422


def test_preview_devuelve_la_extraccion(db, monkeypatch):
    db.info["tenant_id"] = 1
    monkeypatch.setattr(
        portfolio_images, "extract_image", lambda data: {"image_hash": "h", "bytes": len(data)}
    )
    payload = ImageInput(image_base64=base64.b64encode(b"img").decode())
    assert preview(payload, db=db) == {"image_hash": "h", "bytes": 3}


def test_preview_ocr_caido_es_503(db, monkeypatch):
    db.info["tenant_id"] = 1

    def boom(data):
        raise RuntimeError("OCR no disponible")

    monkeypatch.setattr(portfolio_images, "extract_image", boom)
    payload = ImageInput(image_base64=base64.b64encode(b"img").decode())
    with pytest.raises(HTTPException) as exc:
        preview(payload, db=db)
    assert exc.value.status_code == 503


def test_review_error_es_422_con_rollback(db, monkeypatch):
    rolled_back = []
    monkeypatch.setattr(db, "rollback", lambda: rolled_back.append(True))

    async def boom(db_, image_hash, rows):
        raise ValueError("hash desconocido")

    monkeypatch.setattr(portfolio_images, "review_rows", boom)
    payload = ReviewInput.model_construct(image_hash="a" * 64, rows=[{"ticker": "X"}])
    with pytest.raises(HTTPException) as exc:
        asyncio.run(review(payload, db=db))
    assert exc.value.status_code == 422
    assert rolled_back == [True]


def test_confirm_error_es_422_con_rollback(db, monkeypatch):
    rolled_back = []
    monkeypatch.setattr(db, "rollback", lambda: rolled_back.append(True))

    def boom(db_, review_id, confirmed):
        raise ValueError("revision expirada")

    monkeypatch.setattr(portfolio_images, "confirm_review", boom)
    with pytest.raises(HTTPException) as exc:
        confirm(ConfirmInput(review_id=1, confirmed=True), db=db)
    assert exc.value.status_code == 422
    assert rolled_back == [True]


def test_confirm_ok_devuelve_resultado(db, monkeypatch):
    monkeypatch.setattr(
        portfolio_images,
        "confirm_review",
        lambda db_, review_id, confirmed: {"imported": 2, "review_id": review_id},
    )
    assert confirm(ConfirmInput(review_id=5, confirmed=True), db=db) == {
        "imported": 2,
        "review_id": 5,
    }
