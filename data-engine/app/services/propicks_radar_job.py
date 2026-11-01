"""Job del radar ProPicks+DCA: evalúa el universo con precios asentados.

Puente entre los datos ya persistidos (``market_prices``) y el núcleo puro
``propicks_dca_radar.evaluate_candidate``. SIN red, SIN LLM, SIN alertas ni
outbox: solo lecturas de precios y escritura de snapshots públicos vía
``propicks_radar_store``. El presupuesto (``ScanBudget``) acota empresas y
tiempo; el cursor por ``scan_date`` hace la ejecución resumible.

Decisiones de honestidad de datos:

* Solo sesiones asentadas: ``settled_through`` es el día anterior a
  ``as_of``; la sesión de hoy nunca entra aunque haya fila (puede ser un
  spot intradía, no un cierre).
* ``quote_currency`` NULL (legado o unidad no verificable) llega como None y
  el núcleo marca ``currency_mismatch``: la unidad nunca se adivina.
* ``adj_close`` NULL llega como None -> ``unverified_adjusted_series``: la
  señal exige serie ajustada; un cierre bruto no se disfraza de ajustado.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Company, MarketPrice
from app.services.propicks_dca_radar import UNIVERSE_TARGET, RadarPrice, evaluate_candidate
from app.services.propicks_radar_batch import ScanBudget, scan_batch
from app.services.propicks_radar_store import save_snapshot, scan_cursor


def universe_company_ids(db: Session, *, limit: int = UNIVERSE_TARGET) -> list[int]:
    """Empresas con al menos un precio persistido, orden estable por id."""
    return list(
        db.scalars(
            select(MarketPrice.company_id)
            .group_by(MarketPrice.company_id)
            .order_by(MarketPrice.company_id)
            .limit(min(limit, UNIVERSE_TARGET))
        ).all()
    )


def load_radar_prices(
    db: Session, company_id: int, *, settled_through: date
) -> list[RadarPrice]:
    """Serie diaria asentada de una empresa; unidad y ajuste sin inventar."""
    rows = db.scalars(
        select(MarketPrice)
        .where(MarketPrice.company_id == company_id, MarketPrice.date <= settled_through)
        .order_by(MarketPrice.date)
    ).all()
    return [
        RadarPrice(
            day=row.date,
            close=float(row.close),
            adjusted_close=float(row.adj_close) if row.adj_close is not None else None,
            currency=row.quote_currency,
            source=row.source,
            volume=float(row.volume) if row.volume is not None else None,
        )
        for row in rows
        if row.close is not None
    ]


def run_radar_scan(
    db: Session,
    *,
    as_of: date | None = None,
    now: datetime | None = None,
    budget: ScanBudget = ScanBudget(),
) -> dict:
    """Barrido acotado y resumible del universo; devuelve el resumen del lote."""
    now = now or datetime.now(UTC)
    as_of = as_of or now.date()
    settled_through = as_of - timedelta(days=1)
    after_id, saved_before = scan_cursor(db, as_of)
    ids = universe_company_ids(db)
    companies = {
        company.id: company
        for company in db.scalars(select(Company).where(Company.id.in_(ids))).all()
    }

    def fetch_and_evaluate(company_id: int) -> dict:
        company = companies[company_id]
        rows = load_radar_prices(db, company_id, settled_through=settled_through)
        return evaluate_candidate(
            rows,
            as_of=as_of,
            settled_through=settled_through,
            expected_currency=company.currency,
        )

    result = scan_batch(
        ids,
        after_id=after_id,
        fetch_and_evaluate=fetch_and_evaluate,
        save_and_checkpoint=lambda cid, payload: save_snapshot(db, cid, payload, now=now),
        budget=budget,
    )
    result["saved_before"] = saved_before
    result["universe"] = len(ids)
    result["settled_through"] = settled_through.isoformat()
    return result
