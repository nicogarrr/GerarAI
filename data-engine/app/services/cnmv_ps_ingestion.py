"""Persistencia de participaciones significativas CNMV (PS) en schedule_13dg_filings.

Una notificacion PS = una fila Schedule13DGFiling con form="PS-ES" (SIN
migracion nueva). Cada (emisor, titular, F.Registro) es una fila inmutable:
una notificacion nueva del mismo titular crea fila nueva, nunca sobrescribe.
Idempotente por accession derivado del fingerprint (re-ingestar no duplica).

Solo emisores de la tabla revisada cnmv_mapping (issuer_for_nif). La tabla
CNMV declara porcentajes y fecha; no declara acciones del titular ni
desglose sole/shared: esos campos quedan N/D, nunca derivados ni inventados.

Las filas PS-ES NUNCA se mezclan con las SC 13D/G de EE. UU.: la pantalla de
ownership filtra por FORMS_13DG y el generador de noticias exige accession
SEC; ambos caminos ignoran "PS-ES" por construccion (ver
schedule13dg_service.filings_for_ticker y schedule13dg_news.ensure_news).
"""

from __future__ import annotations

import hashlib
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Company, Schedule13DGFiling
from app.services import cnmv_mapping
from app.services.connectors.cnmv_ps import (
    FORM,
    PARSER_VERSION,
    PSIssuerReport,
    fetch_reports,
)


def accession_for(nif: str, holder_name: str, registry_date: Any) -> str:
    """Identidad estable de la notificacion (cabe en String(40))."""
    raw = f"cnmv-ps:{nif}:{registry_date or 'sin-fecha'}:{holder_name.strip().upper()}"
    return "cnmvps-" + hashlib.sha256(raw.encode()).hexdigest()[:32]


def _companies_by_isin_and_ticker(db: Session) -> tuple[dict[str, Company], dict[str, Company]]:
    # .all(): db.scalars devuelve un iterador de UN SOLO USO; materializar
    # antes de recorrerlo dos veces (con el iterador, el segundo dict quedaba
    # siempre vacio y el fallback por ticker no encontraba nunca).
    rows = db.scalars(select(Company)).all()
    by_isin = {company.isin.upper(): company for company in rows if company.isin}
    by_ticker = {company.ticker.upper(): company for company in rows if company.ticker}
    return by_isin, by_ticker


def _known_nif(nif: str) -> bool:
    return cnmv_mapping.issuer_for_nif(nif) is not None


def ingest_cnmv_ps(
    db: Session,
    tenant: int,
    start,
    end,
    *,
    reports: list[PSIssuerReport] | None = None,
    issuers_seen: int | None = None,
) -> dict[str, int]:
    """Una pasada: informes PS de la ventana y filas nuevas de emisores conocidos.

    Si el tope de emisores por corrida deja emisores conocidos sin visitar,
    ``truncated=1`` lo señala en las métricas: lo a medias nunca se presenta
    como completo.
    """
    truncated = False
    if reports is None:
        reports, issuers_seen, truncated = fetch_reports(start, end, is_known=_known_nif)
    if issuers_seen is None:
        issuers_seen = len(reports)
    by_isin, by_ticker = _companies_by_isin_and_ticker(db)
    known_accessions = {
        row[0]
        for row in db.execute(
            select(Schedule13DGFiling.accession_number).where(
                Schedule13DGFiling.tenant_id == tenant,
                Schedule13DGFiling.form == FORM,
            )
        ).all()
    }
    result: dict[str, int] = {
        "issuers_seen": issuers_seen,
        "reports": len(reports),
        "holders_seen": sum(len(report.holders) for report in reports),
        "skipped_known": 0,
        "skipped_unknown_nif": 0,
        "skipped_unknown_company": 0,
        "saved": 0,
        "truncated": 1 if truncated else 0,
    }
    for report in reports:
        issuer = cnmv_mapping.issuer_for_nif(report.nif)
        if issuer is None:
            result["skipped_unknown_nif"] += 1
            continue
        company = by_isin.get(issuer.isin.upper()) or by_ticker.get(issuer.ticker.upper())
        if company is None:
            result["skipped_unknown_company"] += 1
            continue
        for holder in report.holders:
            accession = accession_for(report.nif, holder.holder_name, holder.registry_date)
            if accession in known_accessions:
                result["skipped_known"] += 1
                continue
            db.add(
                Schedule13DGFiling(
                    accession_number=accession,
                    form=FORM,
                    issuer_cik=(report.nif or "")[:20],
                    issuer_ticker=company.ticker,
                    issuer_name=report.issuer_name or issuer.legal_name,
                    filer_cik=None,
                    holder_name=holder.holder_name,
                    # La tabla CNMV no declara acciones del titular: N/D,
                    # nunca derivadas del porcentaje.
                    aggregate_shares=None,
                    percent_of_class=holder.pct_total,  # (A+B) declarado
                    # directo/indirecto no es sole/shared: N/D.
                    sole_voting_power=None,
                    shared_voting_power=None,
                    sole_dispositive_power=None,
                    shared_dispositive_power=None,
                    holders=[
                        {
                            "holder_name": holder.holder_name,
                            "pct_shares_total": holder.pct_shares_total,
                            "pct_direct": holder.pct_direct,
                            "pct_indirect": holder.pct_indirect,
                            "pct_instruments": holder.pct_instruments,
                            "pct_total": holder.pct_total,
                            "registry_date": (
                                holder.registry_date.isoformat() if holder.registry_date else None
                            ),
                            "document_url": holder.document_url,
                            "total_voting_rights": report.total_voting_rights,
                            "loyalty_voting_rights": report.loyalty_voting_rights,
                        }
                    ],
                    securities_class_title="acciones",
                    snapshot_date=(
                        holder.registry_date.isoformat() if holder.registry_date else None
                    ),
                    filing_date=(
                        holder.registry_date.isoformat() if holder.registry_date else None
                    ),
                    report_date=None,
                    signature_date=None,
                    source_url=holder.document_url,
                    index_url=report.page_url,
                    parser_version=PARSER_VERSION,
                    status="parsed",
                )
            )
            known_accessions.add(accession)
            result["saved"] += 1
    db.commit()
    return result
