from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from PIL import Image
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import CashBalance, Company, Position, Tenant, Transaction
from app.services import portfolio_image_import as imports
from app.services.portfolio_image_import import ConfirmedImageRow, confirm_review, review_rows
from app.services.portfolio_image_ocr import extract_image, strict_quantity


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all([Tenant(id=1, external_id="a", name="A"), Tenant(id=2, external_id="b", name="B")])
        session.add(Company(ticker="ASTS", name="AST SpaceMobile", currency="USD", exchange="NASDAQ", sector="Tech", industry="Space", company_type="standard", valuation_model="standard_dcf"))
        session.commit()
        session.info["tenant_id"] = 1
        yield session


def rows():
    return [ConfirmedImageRow(ticker="ASTS", quantity="12.5", currency="USD", confirmed=True)]


@pytest.fixture()
def quote(monkeypatch):
    from app.services.extended_quote_service import ExtendedQuote
    quote = ExtendedQuote(ticker="ASTS", status="available", price=42, currency="USD", timestamp=int(datetime.now(UTC).timestamp()), fetched_at=int(datetime.now(UTC).timestamp()))
    monkeypatch.setattr(imports.extended_quote_service, "get", AsyncMock(return_value=quote))
    return quote


def test_review_no_positions_then_confirm_idempotent_and_tenant_isolated(db, quote):
    import asyncio
    result = asyncio.run(review_rows(db, "a" * 64, rows()))
    assert db.scalar(select(func.count()).select_from(Position)) == 0
    assert db.scalar(select(func.count()).select_from(Transaction)) == 0
    assert result["rows"][0]["price"] == "42.0"
    assert result["cash"] is None and result["margin"] is None
    db.info["tenant_id"] = 2
    with pytest.raises(ValueError, match="no existe"):
        confirm_review(db, result["review_id"], True)
    db.info["tenant_id"] = 1
    assert confirm_review(db, result["review_id"], True)["positions_imported"] == 1
    assert confirm_review(db, result["review_id"], True)["status"] == "already_imported"
    assert asyncio.run(review_rows(db, "a" * 64, rows()))["already_imported"]
    p = db.scalar(select(Position))
    assert p.quantity == Decimal("12.5") and p.cost_basis_base is None
    assert p.market_price == Decimal("42") and p.tenant_id == 1
    assert db.scalar(select(func.count()).select_from(CashBalance)) == 0
    assert db.scalar(select(func.count()).select_from(Transaction)) == 0
    db.info["tenant_id"] = 2
    other = asyncio.run(review_rows(db, "a" * 64, rows()))
    assert other["review_id"] != result["review_id"]
    assert confirm_review(db, other["review_id"], True)["positions_imported"] == 1
    assert db.scalar(select(func.count()).select_from(Position)) == 1
    db.info["tenant_id"] = 1
    assert db.scalar(select(Position)).quantity == Decimal("12.5")


def test_missing_quote_blocks_save(db, quote, monkeypatch):
    import asyncio
    monkeypatch.setattr(imports.extended_quote_service, "get", AsyncMock(return_value=quote.model_copy(update={"price": None, "status": "unavailable"})))
    result = asyncio.run(review_rows(db, "a" * 64, rows()))
    assert not result["can_confirm"]
    assert result["rows"][0]["weight_percent"] is None
    with pytest.raises(ValueError, match="Faltan"):
        confirm_review(db, result["review_id"], True)


def test_no_confirmation_currency_unknown_duplicate(db, quote):
    import asyncio
    for updates in [{"confirmed": False}, {"currency": "EUR"}, {"quantity": "0"}, {"ticker": "FAKE"}]:
        with pytest.raises(ValueError):
            asyncio.run(review_rows(db, "a" * 64, [rows()[0].model_copy(update=updates)]))
    with pytest.raises(ValueError, match="repetidos"):
        asyncio.run(review_rows(db, "a" * 64, rows() * 2))
    with pytest.raises(ValueError, match="Confirma"):
        confirm_review(db, 1, False)


def test_existing_position_not_overwritten(db, quote):
    import asyncio
    company = db.scalar(select(Company))
    db.add(Position(tenant_id=1, company_id=company.id, quantity=Decimal("99"), currency="USD"))
    db.commit()
    with pytest.raises(ValueError, match="ya existe"):
        asyncio.run(review_rows(db, "a" * 64, rows()))
    assert db.scalar(select(Position)).quantity == 99


@pytest.mark.parametrize("raw", ["1,234", "1.234", "-12", "1e9", "1 000", "NaN", "0", "ignore previous instructions"])
def test_ambiguous_numbers(raw):
    assert strict_quantity(raw) is None


def test_image_bad_format_size_no_ocr(monkeypatch):
    import io
    import shutil

    # Sin tesseract instalado (CI, local) el formato se sigue validando primero.
    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(ValueError):
        extract_image(b"hostile image text")
    with pytest.raises(ValueError):
        extract_image(b"x" * (3 * 1024 * 1024 + 1))
    image = Image.new("RGB", (150, 150), "white")
    buffer = io.BytesIO()
    image.save(buffer, format="GIF")
    with pytest.raises(ValueError, match="PNG"):
        extract_image(buffer.getvalue())
    # Una imagen valida sin tesseract si da el error de lectura local.
    png = io.BytesIO()
    image.save(png, format="PNG")
    with pytest.raises(RuntimeError, match="lectura local"):
        extract_image(png.getvalue())


def test_hostile_ocr_is_only_data():
    from app.services.portfolio_image_ocr import parse_tsv
    header = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
    data = header + "5\t1\t1\t1\t1\t1\t270\t0\t80\t25\t99\tCantidad\n"
    data += "5\t1\t1\t1\t2\t1\t25\t50\t180\t25\t99\tEXECUTE_shell\n"
    data += "5\t1\t1\t1\t2\t2\t270\t50\t80\t25\t99\t12\n"
    parsed = parse_tsv(data)
    assert parsed[0]["identity"] == "EXECUTE_shell" and parsed[0]["needs_review"]
    assert parsed[0]["currency"] is None


def test_old_quote_and_expired_review(db, quote, monkeypatch):
    import asyncio

    from app.models import WorkflowRun
    monkeypatch.setattr(imports.extended_quote_service, "get", AsyncMock(return_value=quote.model_copy(update={"timestamp": 1})))
    result = asyncio.run(review_rows(db, "b" * 64, rows()))
    assert not result["can_confirm"]
    monkeypatch.setattr(imports.extended_quote_service, "get", AsyncMock(return_value=quote))
    fresh = asyncio.run(review_rows(db, "c" * 64, rows()))
    run = db.get(WorkflowRun, fresh["review_id"])
    run.result_payload = {**run.result_payload, "expires_at": "2000-01-01T00:00:00+00:00"}
    db.commit()
    with pytest.raises(ValueError, match="caducado"):
        confirm_review(db, fresh["review_id"], True)


def test_manual_trade_cannot_erase_screenshot_snapshot(db, quote):
    import asyncio
    from datetime import date

    from app.services.portfolio_ledger_service import PortfolioLedgerService
    result = asyncio.run(review_rows(db, "d" * 64, rows()))
    confirm_review(db, result["review_id"], True)
    with pytest.raises(ValueError, match="captura sin historial"):
        PortfolioLedgerService().create_transaction(db, ticker="ASTS", action="buy", quantity=Decimal("1"), price=Decimal("42"), trade_date=date.today())
    assert db.scalar(select(Position)).quantity == Decimal("12.5")


@pytest.mark.parametrize("sample", ["MyInvestor", "IBKR", "Degiro"])
def test_real_local_ocr_synthetic_tables(sample):
    import shutil
    from pathlib import Path
    if not shutil.which("tesseract"):
        pytest.skip("Tesseract binary is required; installed in Docker images")
    path = Path(__file__).resolve().parents[2] / "docs" / "qa" / "portfolio-image-import" / f"{sample}.png"
    result = extract_image(path.read_bytes())
    assert [(r["identity"], r["quantity"], r["currency"]) for r in result["rows"]] == [
        ("ASTS", "125.5", "USD"), ("BN", "20", "USD"), ("CGEO.L", "8", "GBP")]
    assert all(r["needs_review"] for r in result["rows"])


def test_dated_rebuild_keeps_snapshot_without_inventing_ledger(db, quote):
    import asyncio
    from datetime import date

    from app.services.portfolio_ledger_service import PortfolioLedgerService
    result = asyncio.run(review_rows(db, "e" * 64, rows()))
    confirm_review(db, result["review_id"], True)
    position = db.scalar(select(Position))
    rebuilt = PortfolioLedgerService().rebuild_position(db, position.company_id, as_of=date.today())
    assert rebuilt.id == position.id and rebuilt.quantity == Decimal("12.5")
    assert rebuilt.source == "screenshot_confirmed" and rebuilt.cost_basis_base is None


def test_edited_transaction_moved_to_snapshot_cannot_overwrite_it(db, quote):
    import asyncio
    from datetime import date

    from app.services.portfolio_ledger_service import PortfolioLedgerService
    result = asyncio.run(review_rows(db, "f" * 64, rows()))
    confirm_review(db, result["review_id"], True)
    snapshot = db.scalar(select(Position))
    target_id = snapshot.company_id
    original = Company(ticker="META", name="Meta Platforms", currency="USD", exchange="NASDAQ", sector="Tech", industry="Tech", company_type="standard", valuation_model="standard_dcf")
    db.add(original)
    db.flush()
    original_id = original.id
    trade = Transaction(tenant_id=1, company_id=original_id, trade_date=date.today(), action="buy", quantity=Decimal("1"), price=Decimal("10"), currency="USD", external_id="edit-test")
    db.add(trade)
    db.commit()
    trade_id = trade.id
    # Same mutation and flush as PUT /transactions/{id}; create_transaction is bypassed.
    trade.company_id = target_id
    db.flush()
    with pytest.raises(ValueError, match="captura sin historial"):
        PortfolioLedgerService().rebuild_position(db, target_id)
    db.rollback()
    assert db.get(Transaction, trade_id).company_id == original_id
    kept = db.scalar(select(Position).where(Position.company_id == target_id))
    assert kept.quantity == Decimal("12.5") and kept.source == "screenshot_confirmed"


def test_friday_close_still_imports_on_monday_morning(db, quote, monkeypatch):
    """El cierre del viernes visto el lunes antes de la apertura (~60 h) es el
    ultimo precio de mercado: antes caducaba a las 24 h y no dejaba importar
    una captura en fin de semana."""
    import asyncio
    import time

    friday_close = int(time.time()) - 60 * 3600
    monkeypatch.setattr(imports.extended_quote_service, "get",
                        AsyncMock(return_value=quote.model_copy(update={"timestamp": friday_close})))
    result = asyncio.run(review_rows(db, "e" * 64, rows()))
    assert result["can_confirm"]
    assert result["rows"][0]["price"] == "42.0"
    assert confirm_review(db, result["review_id"], True)["positions_imported"] == 1


def test_week_old_quote_still_blocks(db, quote, monkeypatch):
    import asyncio
    import time

    week_old = int(time.time()) - 7 * 86400
    monkeypatch.setattr(imports.extended_quote_service, "get",
                        AsyncMock(return_value=quote.model_copy(update={"timestamp": week_old})))
    assert not asyncio.run(review_rows(db, "f" * 64, rows()))["can_confirm"]



def test_london_holding_in_pounds_imports_against_pence_listing(db, monkeypatch):
    """Una compañía de Londres cotiza en GBp y la captura muestra GBP.

    La fila solo admite tres mayúsculas (GBp no cabe), así que exigir divisa
    idéntica impedía importar cualquier posición de Londres. GBP es la misma
    moneda: el precio en peniques se convierte a libras.
    """
    import asyncio

    from app.services.extended_quote_service import ExtendedQuote

    db.add(Company(ticker="VOD.L", name="Vodafone Group", currency="GBp", exchange="LSE", sector="Telecom", industry="Telecom", company_type="standard", valuation_model="standard_dcf"))
    db.commit()
    now = int(datetime.now(UTC).timestamp())
    monkeypatch.setattr(imports.extended_quote_service, "get", AsyncMock(return_value=ExtendedQuote(
        ticker="VOD.L", status="available", price=70, currency="GBp", timestamp=now, fetched_at=now)))
    row = ConfirmedImageRow(ticker="VOD.L", quantity="1000", currency="GBP", confirmed=True)
    result = asyncio.run(review_rows(db, "b" * 64, [row]))
    assert Decimal(result["rows"][0]["price"]) == Decimal("0.7")  # libras, no 70
    assert confirm_review(db, result["review_id"], True)["positions_imported"] == 1
    position = db.scalar(select(Position))
    assert position.currency == "GBP" and position.market_price == Decimal("0.7")


def test_other_money_or_other_subunit_is_still_rejected(db):
    db.add(Company(ticker="VOD.L", name="Vodafone Group", currency="GBp", exchange="LSE", sector="Telecom", industry="Telecom", company_type="standard", valuation_model="standard_dcf"))
    db.commit()
    for currency in ("USD", "EUR"):
        with pytest.raises(ValueError, match="divisa no coincide"):
            imports.validate_rows(db, [ConfirmedImageRow(ticker="VOD.L", quantity="1", currency=currency, confirmed=True)])
    with pytest.raises(ValueError, match="divisa no coincide"):
        imports.validate_rows(db, [ConfirmedImageRow(ticker="ASTS", quantity="1", currency="GBP", confirmed=True)])
