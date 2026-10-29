"""Bounded, transactional four-row repair; official facts are never edited.

Callers own backup/restore validation before apply. Dry-run never adds ORM rows.
The reviewed consumer policy must be deployed before applying this plan.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Company, Document, FinancialFact
from app.services.esef_fact_quarantine import EBRO_LEI, LOG_LEI, fact_quarantine_reason
from app.services.reviewed_eps_adjustments import (
    REVIEW_ID,
    REVIEWED,
    SOURCE_TYPE,
    is_reviewed_eps_adjustment,
)

# Exact production identities reviewed against issuer PDFs. A changed source
# is a reason to abort, never a reason to guess another row or rescale it.
PLAN = (
    (3853675, "EBRO", EBRO_LEI, "2025-01-01:FY", "1351", "2024-12-31:FY", "1.351"),
    (3853676, "EBRO", EBRO_LEI, "2024-01-01:FY", "1215", "2023-12-31:FY", "1.215"),
    (9552186, "LOG", LOG_LEI, "2025-09-30:FY", "2130", "2025-09-30:FY", "2.13"),
    (9552187, "LOG", LOG_LEI, "2024-09-30:FY", "2340", "2024-09-30:FY", "2.34"),
)


def _raw_digest(rows: list[FinancialFact]) -> str:
    data = [
        {col.name: str(getattr(row, col.name)) for col in FinancialFact.__table__.columns} for row in rows
    ]
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def repair_reviewed_eps(db: Session, *, tenant_id: int, apply: bool = False) -> dict:
    """Stage changes only. Caller commits, atomically, after this function passes."""
    if db.info.get("tenant_id") != tenant_id:
        raise ValueError("explicit session tenant does not match repair tenant")
    rows = list(
        db.scalars(
            select(FinancialFact)
            .options(selectinload(FinancialFact.source))
            .where(FinancialFact.tenant_id == tenant_id, FinancialFact.id.in_([entry[0] for entry in PLAN]))
            .order_by(FinancialFact.id)
            .with_for_update()
        ).all()
    )
    if len(rows) != len(PLAN):
        raise ValueError("expected exactly four original facts for this tenant")
    before = _raw_digest(rows)
    by_id = {row.id: row for row in rows}
    staged = []
    # Validate every source and target before adding even the first document.
    for raw_id, ticker, lei, raw_period, raw_value, period, value in PLAN:
        raw = by_id[raw_id]
        company = db.scalar(select(Company).where(Company.id == raw.company_id))
        if (
            company is None
            or company.ticker != ticker
            or raw.source_type != "ESEF"
            or raw.metric != "eps_diluted"
            or raw.value != Decimal(raw_value)
            or raw.period != raw_period
            or raw.fiscal_year != int(raw_period[:4])
            or raw.fiscal_quarter != "FY"
            or raw.unit != "EUR/share"
            or not raw.is_reported
            or raw.is_adjusted
            or raw.source is None
            or raw.source.tenant_id != tenant_id
            or raw.source.company_id != company.id
            or (raw.source.metadata_ or {}).get("lei") != lei
            or not fact_quarantine_reason(raw)
        ):
            raise ValueError(f"original fact {raw_id} no longer matches reviewed plan")
        targets = list(
            db.scalars(
                select(FinancialFact)
                .options(selectinload(FinancialFact.source))
                .where(
                    FinancialFact.tenant_id == tenant_id,
                    FinancialFact.company_id == company.id,
                    FinancialFact.metric == "eps_diluted",
                    FinancialFact.period == period,
                    FinancialFact.source_type == SOURCE_TYPE,
                )
            ).all()
        )
        if len(targets) > 1:
            raise ValueError(f"duplicate adjusted target for original {raw_id}")
        existing = next(iter(targets), None)
        if existing is not None and (
            not is_reviewed_eps_adjustment(existing)
            or existing.value != Decimal(value)
            or (existing.source.metadata_ or {}).get("raw_fact_id") != raw_id
        ):
            raise ValueError(f"adjusted target conflicts for original {raw_id}")
        staged.append((raw, ticker, lei, period, value, existing))
    result = {
        "review_id": REVIEW_ID,
        "mode": "apply" if apply else "dry_run",
        "tenant_id": tenant_id,
        "raw_sha256_before": before,
        "inserted": 0,
        "existing": 0,
        "adjustments": [],
    }
    for raw, ticker, lei, period, value, existing in staged:
        row = existing
        if existing is not None:
            result["existing"] += 1
        elif apply:
            url, checksum, page = REVIEWED[(lei, period, Decimal(value))]
            doc = Document(
                tenant_id=tenant_id,
                company_id=raw.company_id,
                title=f"{ticker} {period[:4]} BPA ajustado: PDF revisado",
                source_type=SOURCE_TYPE,
                source_url=url,
                checksum=checksum,
                metadata_={
                    "lei": lei,
                    "review_id": REVIEW_ID,
                    "pdf_page": page,
                    "raw_fact_id": raw.id,
                    "raw_source_id": raw.source_id,
                    "raw_period": raw.period,
                    "raw_value": str(raw.value),
                    "note": "Transcripción revisada; no reemplaza el hecho ESEF oficial",
                },
            )
            db.add(doc)
            db.flush()
            row = FinancialFact(
                tenant_id=tenant_id,
                company_id=raw.company_id,
                metric="eps_diluted",
                value=Decimal(value),
                unit="EUR/share",
                period=period,
                fiscal_year=int(period[:4]),
                fiscal_quarter="FY",
                source_type=SOURCE_TYPE,
                source_id=doc.id,
                source=doc,
                is_reported=False,
                is_adjusted=True,
                confidence=Decimal("1.0"),
                # Historical publication was not independently verified.
                filed=None,
            )
            db.add(row)
            db.flush()
            if not is_reviewed_eps_adjustment(row):
                raise ValueError("staged adjustment failed consumer validation")
            result["inserted"] += 1
        result["adjustments"].append(
            {
                "raw_fact_id": raw.id,
                "ticker": ticker,
                "period": period,
                "value": value,
                "adjusted_fact_id": row.id if row else None,
            }
        )
    # Refresh persisted originals, so the invariant checks the database state.
    for raw in rows:
        db.refresh(raw)
    result["raw_sha256_after"] = _raw_digest(rows)
    if result["raw_sha256_after"] != before:
        raise ValueError("original source rows changed during repair")
    return result
