"""Reviewed screenshot snapshots, not fabricated buys or tax cost basis."""
from __future__ import annotations

import asyncio
import hashlib
import json
import time
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.tenancy import tenant_filters
from app.models import Company, Position, Tenant, Transaction, WorkflowRun
from app.services.extended_quote_service import extended_quote_service
from app.services.portfolio_fx_service import PortfolioFXService
from app.services.portfolio_ledger_service import PortfolioLedgerService
from app.services.price_units import price_in_currency

WORKFLOW = "portfolio_image_import"


# Antiguedad maxima de la cotizacion: el ultimo cierre de la ultima sesion.
# Con 24 h, el cierre del viernes caducaba el sabado y no se podia importar una
# captura en fin de semana ni un lunes antes de la apertura; 4 dias cubren el
# fin de semana mas un festivo (viernes al cierre -> martes por la manana).
QUOTE_MAX_AGE_SECONDS = 4 * 86400


class ConfirmedImageRow(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    ticker: str = Field(pattern=r"^[A-Z0-9.\-]{1,20}$")
    quantity: str = Field(pattern=r"^\d+(?:\.\d{1,6})?$", max_length=18)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    confirmed: bool


def validate_rows(db: Session, rows: list[ConfirmedImageRow]) -> list[tuple[Company, ConfirmedImageRow]]:
    if not db.info.get("tenant_id"):
        raise ValueError("Falta la sesión de cartera")
    if not 1 <= len(rows) <= 60 or len({r.ticker for r in rows}) != len(rows):
        raise ValueError("Revisa las filas: no se permiten instrumentos repetidos")
    found = []
    for row in rows:
        quantity = Decimal(row.quantity)
        if not row.confirmed or not 0 < quantity <= 1_000_000_000:
            raise ValueError("Confirma instrumento, cantidad y divisa de cada fila")
        company = db.scalar(select(Company).where(Company.ticker == row.ticker))
        if not company or company.exchange in {"UNKNOWN", ""} or company.name == company.ticker:
            raise ValueError(f"{row.ticker}: elige un instrumento identificado en el catálogo")
        if company.currency != row.currency:
            raise ValueError(f"{row.ticker}: la divisa no coincide con el instrumento")
        existing = db.scalar(select(Position.id).where(Position.company_id == company.id, *tenant_filters(db, Position)))
        history = db.scalar(select(Transaction.id).where(Transaction.company_id == company.id, *tenant_filters(db, Transaction)).limit(1))
        if existing or history:
            raise ValueError(f"{row.ticker}: ya existe en tu cartera o historial. Usa el fichero del bróker para conciliar; no se sumará ni sobrescribirá")
        found.append((company, row))
    return found


async def review_rows(db: Session, image_hash: str, rows: list[ConfirmedImageRow]) -> dict:
    if not db.info.get("tenant_id"):
        raise ValueError("Falta la sesión de cartera")
    key = hashlib.sha256(json.dumps({"image": image_hash, "rows": [r.model_dump() for r in rows]}, sort_keys=True).encode()).hexdigest()
    prior = db.scalar(select(WorkflowRun).where(WorkflowRun.workflow_name == WORKFLOW, WorkflowRun.idempotency_key == key, *tenant_filters(db, WorkflowRun)))
    if prior is not None and prior.status == "succeeded":
        return {"review_id": prior.id, **(prior.result_payload or {}), "already_imported": True}
    pairs = validate_rows(db, rows)
    # Each quote uses the existing no-key, timestamped market source, never OCR.
    semaphore = asyncio.Semaphore(4)

    async def quote_one(company, row):
        async with semaphore:
            try:
                quote = await asyncio.wait_for(extended_quote_service.get(company.ticker), timeout=5)
            except TimeoutError:
                from app.services.extended_quote_service import ExtendedQuote

                quote = ExtendedQuote(ticker=company.ticker, fetched_at=int(time.time()))
        price = None
        if quote.price and quote.timestamp and quote.status != "unavailable" and 0 <= time.time() - quote.timestamp < QUOTE_MAX_AGE_SECONDS:
            price = price_in_currency(Decimal(str(quote.price)), quote_currency=quote.currency, target_currency=row.currency, company=company)
        return {**row.model_dump(), "name": company.name, "exchange": company.exchange,
                "price": str(price) if price else None, "timestamp": quote.timestamp if price else None,
                "source": quote.source, "value_native": str(price * Decimal(row.quantity)) if price else None}

    try:
        reviewed = list(await asyncio.wait_for(asyncio.gather(*(quote_one(c, r) for c, r in pairs)), timeout=20))
    except TimeoutError as exc:
        raise ValueError("La consulta de precios tardó demasiado. Revisa menos filas a la vez o vuelve a intentarlo") from exc
    # Weights only in a common, verified base unit. Missing FX means no weight, not zero.
    fx = PortfolioFXService()
    base = fx.base_currency(db)
    for item in reviewed:
        rate = fx.rate(db, quote_currency=item["currency"], base_currency=base, as_of=date.today())
        item["value_base"] = str(Decimal(item["value_native"]) * rate) if rate and item["value_native"] else None
    total = sum(Decimal(item["value_base"]) for item in reviewed if item["value_base"])
    complete = all(item["value_base"] is not None for item in reviewed)
    for item in reviewed:
        item["weight_percent"] = str(Decimal(item["value_base"]) / total * 100) if complete and total > 0 else None
    payload = {"rows": reviewed, "base_currency": base, "cash": None, "margin": None,
               "can_confirm": all(item["price"] is not None for item in reviewed),
               "expires_at": (datetime.now(UTC) + timedelta(minutes=10)).isoformat()}
    tenant_id = db.info["tenant_id"]
    # Serialize creation by tenant to enforce idempotency, including concurrent retries.
    db.scalar(select(Tenant).where(Tenant.id == tenant_id).with_for_update())
    run = db.scalar(select(WorkflowRun).where(WorkflowRun.workflow_name == WORKFLOW, WorkflowRun.idempotency_key == key, *tenant_filters(db, WorkflowRun)))
    if run is None:
        run = WorkflowRun(tenant_id=tenant_id, workflow_name=WORKFLOW, idempotency_key=key, status="review", input_payload={}, result_payload=payload)
        db.add(run)
    elif run.status != "succeeded":
        run.result_payload = payload
    db.commit()
    return {"review_id": run.id, **(run.result_payload or payload), "already_imported": run.status == "succeeded"}


def confirm_review(db: Session, review_id: int, confirmed: bool) -> dict:
    tenant_id = db.info.get("tenant_id")
    if not tenant_id or confirmed is not True:
        raise ValueError("Confirma la revisión antes de guardar")
    db.scalar(select(Tenant).where(Tenant.id == tenant_id).with_for_update())
    run = db.scalar(select(WorkflowRun).where(WorkflowRun.id == review_id, WorkflowRun.workflow_name == WORKFLOW, *tenant_filters(db, WorkflowRun)).with_for_update())
    if not run:
        raise ValueError("La revisión no existe en tu cartera")
    if run.status == "succeeded":
        return {"status": "already_imported", "positions_imported": 0}
    payload = run.result_payload or {}
    if not payload.get("can_confirm") or datetime.fromisoformat(payload["expires_at"]) < datetime.now(UTC):
        raise ValueError("Faltan cotizaciones o la revisión ha caducado. Vuelve a revisar")
    rows = [ConfirmedImageRow.model_validate({k: item[k] for k in ("ticker", "quantity", "currency", "confirmed")}) for item in payload["rows"]]
    pairs = validate_rows(db, rows)
    fx = PortfolioFXService()
    portfolio = fx.ensure_portfolio(db)
    ledger = PortfolioLedgerService()
    for (company, row), item in zip(pairs, payload["rows"], strict=True):
        if not item["timestamp"] or not 0 <= time.time() - item["timestamp"] < QUOTE_MAX_AGE_SECONDS:
            raise ValueError("Cotización caducada. Vuelve a revisar")
        position = Position(tenant_id=tenant_id, company_id=company.id, portfolio_id=portfolio.id,
                            quantity=Decimal(row.quantity), average_cost=Decimal("0"), currency=row.currency,
                            base_currency=portfolio.base_currency, source="screenshot_confirmed",
                            cost_basis_native=None, cost_basis_base=None)
        db.add(position)
        db.flush()
        ledger.update_market_price(db, company_id=company.id, position=position,
                                   price=Decimal(item["price"]), as_of=datetime.fromtimestamp(item["timestamp"], UTC).date())
        # No purchase cost, tax date, realized gain or cash is derived from a screenshot.
        position.cost_basis_native = None
        position.cost_basis_base = None
        position.realized_pnl_base = None
    run.status = "succeeded"
    run.finished_at = datetime.now(UTC)
    db.commit()
    return {"status": "imported", "positions_imported": len(rows)}
