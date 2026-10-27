"""Lectura de filings SC 13D/13G persistidos (titulares >5%, SEC EDGAR).

Regla de veracidad: un campo no parseado se muestra N/D, NUNCA una cifra
inventada. Toda fila lleva su procedencia (enlace al filing y al indice de
EDGAR, accession, version del parser).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.tenancy import tenant_filters
from app.models.entities import Schedule13DGFiling

ND = "N/D"
SOURCE_LABEL = "SEC EDGAR · SC 13D/13G"


def _nd_number(value: float | None) -> str:
    """Numero con separador de miles es-ES; N/D si no se parseo."""
    if value is None:
        return ND
    return f"{value:,.0f}".replace(",", ".")


def _nd_percent(value: float | None) -> str:
    if value is None:
        return ND
    return f"{value:.1f} %".replace(".", ",")


def _nd_text(value: str | None) -> str:
    return value if value else ND


def _filing_payload(row: Schedule13DGFiling) -> dict:
    return {
        "accession_number": row.accession_number,
        "form": row.form,
        "is_amendment": row.is_amendment,
        "issuer_ticker": row.issuer_ticker,
        "issuer_name": row.issuer_name,
        "issuer_cik": row.issuer_cik,
        "filer_cik": row.filer_cik,
        "holder_name": row.holder_name,
        "aggregate_shares": row.aggregate_shares,
        "percent_of_class": row.percent_of_class,
        "sole_voting_power": row.sole_voting_power,
        "shared_voting_power": row.shared_voting_power,
        "sole_dispositive_power": row.sole_dispositive_power,
        "shared_dispositive_power": row.shared_dispositive_power,
        "securities_class_title": row.securities_class_title,
        "snapshot_date": row.snapshot_date,
        "filing_date": row.filing_date,
        "report_date": row.report_date,
        "signature_date": row.signature_date,
        "status": row.status,
        "source": SOURCE_LABEL,
        "source_url": row.source_url,
        "index_url": row.index_url,
        "parser_version": row.parser_version,
        "display": {
            "holder": _nd_text(row.holder_name),
            "aggregate_shares": _nd_number(row.aggregate_shares),
            "percent_of_class": _nd_percent(row.percent_of_class),
            "snapshot_date": _nd_text(row.snapshot_date),
        },
    }


def filings_for_ticker(
    db: Session,
    ticker: str,
    *,
    limit: int = 50,
) -> dict:
    """Filings SC 13D/13G persistidos del ticker, mas recientes primero."""
    normalized = ticker.strip().upper()
    rows = db.scalars(
        select(Schedule13DGFiling)
        .where(
            Schedule13DGFiling.issuer_ticker == normalized,
            *tenant_filters(db, Schedule13DGFiling),
        )
        .order_by(Schedule13DGFiling.filing_date.desc(), Schedule13DGFiling.id.desc())
        .limit(limit)
    ).all()
    return {
        "ticker": normalized,
        "source": SOURCE_LABEL,
        "count": len(rows),
        "filings": [_filing_payload(row) for row in rows],
        "limitations": [
            "Solo emisores seguidos (watchlist/cartera) y filings ya ingeridos; "
            "los campos no parseados se muestran N/D, nunca estimados.",
            "Un Schedule 13G pasivo puede declararse hasta 45 dias despues del "
            "cierre del trimestre (Rule 13d-1(b)): la fecha de snapshot es la "
            "declarada en el filing, no la de presentacion.",
        ],
    }
