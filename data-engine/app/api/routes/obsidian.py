"""Descarga privada del vault Obsidian: por ticker o del tenant completo."""

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import (
    Claim,
    ClaimEvidence,
    Company,
    Document,
    Position,
    ThesisSection,
    ThesisVersion,
    WatchItem,
)
from app.services.company_resolver import resolve_companies, resolve_company
from app.services.obsidian_export import (
    CompanyEntry,
    Note,
    Source,
    build_obsidian_vault,
    build_obsidian_zip,
    find_mentions,
)
from app.services.thesis_publication_gate import archived_thesis_notice, thesis_withheld_reasons

router = APIRouter()
vault_router = APIRouter()


def _zip_response(content: bytes, filename: str) -> Response:
    return Response(
        content=content,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


def _load_thesis_notes(db: Session, company: Company) -> list[Note]:
    """Tesis persistidas del tenant para una empresa, con sus fuentes reales.

    ThesisVersion/Claim/ClaimEvidence/Document son TenantOwned: la sesión ya
    filtra por el tenant firmado, así que ninguna nota mezcla tenants.
    """
    return _load_thesis_notes_by_company(db, [company]).get(company.id, [])


def _load_thesis_notes_by_company(
    db: Session, companies: list[Company]
) -> dict[int, list[Note]]:
    """Notas de tesis de VARIAS empresas con una consulta por tabla.

    Mismo resultado que llamar a ``_load_thesis_notes`` empresa a empresa,
    pero el coste ya no crece con el vault: antes eran hasta cinco consultas
    por empresa (versiones, secciones, claims, evidencias y documentos).
    Solo aparecen las empresas con alguna tesis.
    """
    by_id = {company.id: company for company in companies}
    if not by_id:
        return {}
    versions = list(
        db.scalars(
            select(ThesisVersion)
            .where(ThesisVersion.company_id.in_(sorted(by_id)))
            .order_by(ThesisVersion.version, ThesisVersion.id)
        ).all()
    )
    if not versions:
        return {}
    version_ids = [v.id for v in versions]
    sections = list(
        db.scalars(
            select(ThesisSection)
            .where(ThesisSection.thesis_version_id.in_(version_ids))
            .order_by(ThesisSection.order_index, ThesisSection.id)
        ).all()
    )
    sections_by_version: dict[int, list[ThesisSection]] = {v.id: [] for v in versions}
    for section in sections:
        sections_by_version[section.thesis_version_id].append(section)
    claims = list(db.scalars(select(Claim).where(Claim.thesis_version_id.in_(version_ids))).all())
    evidence = (
        list(
            db.scalars(
                select(ClaimEvidence)
                .where(ClaimEvidence.claim_id.in_([c.id for c in claims]))
                .order_by(ClaimEvidence.id)
            ).all()
        )
        if claims
        else []
    )
    doc_ids = [e.document_id for e in evidence if e.document_id is not None]
    documents = (
        {d.id: d for d in db.scalars(select(Document).where(Document.id.in_(doc_ids))).all()}
        if doc_ids
        else {}
    )
    claim_by_id = {c.id: c for c in claims}
    sources: dict[int, list[Source]] = {v.id: [] for v in versions}
    for row in evidence:
        claim = claim_by_id[row.claim_id]
        document = documents.get(row.document_id)
        sources[claim.thesis_version_id].append(
            Source(
                url=row.source_url or (document.source_url if document else "") or "",
                date=document.published_at.date().isoformat() if document and document.published_at else "",
                statement=claim.statement or "",
                tier=row.source_tier or "",
            )
        )
    reasons = thesis_withheld_reasons(db, versions)
    notes: dict[int, list[Note]] = {}
    for v in versions:
        company = by_id[v.company_id]
        notes.setdefault(company.id, []).append(
            Note(
                title=f"Tesis {company.ticker} v{v.version}",
                version=v.version,
                date=v.updated_at.date().isoformat() if v.updated_at else "",
                status=v.status or "",
                body=(archived_thesis_notice(v, reasons[v.id]) if reasons[v.id] else
                v.thesis_markdown or "\n\n".join(
                    part
                    for part in [
                        v.executive_summary or "",
                        *(
                            f"## {section.title}\n\n{section.body}"
                            for section in sections_by_version[v.id]
                            if section.body
                        ),
                    ]
                    if part
                )),
                sources=[] if reasons[v.id] else sources[v.id],
            )
        )
    return notes


@router.get("/{ticker}/obsidian.zip")
def export_obsidian(ticker: str, db: Session = Depends(get_db)) -> Response:
    company = resolve_company(db, ticker)
    if company is None:
        raise HTTPException(status_code=404, detail="Company not found")
    notes = _load_thesis_notes(db, company)
    if not notes:
        raise HTTPException(status_code=404, detail="No thesis for ticker")
    content = build_obsidian_zip(company.ticker, notes)
    return _zip_response(content, f"gerarai-obsidian-{company.ticker}.zip")


@vault_router.get("/vault.zip")
def export_obsidian_vault(db: Session = Depends(get_db)) -> Response:
    """Vault Markdown del tenant: cartera + watchlist, solo datos persistidos.

    Coste cero: ni LLM ni red, solo lecturas de la base ya filtradas por el
    tenant firmado (Position/WatchItem/tesis son TenantOwned). Los símbolos
    de watchlist sin empresa en el universo se listan como "sin datos de
    empresa" en vez de inventarse una ficha.
    """
    # Solo tenencias vivas: una posición cerrada (quantity=0 tras vender) es
    # historial del ledger, no cartera; el resto de la app la trata igual.
    positions = list(db.scalars(select(Position)).all())
    company_ids = sorted(
        {position.company_id for position in positions if position.quantity > 0}
    )
    companies: dict[str, Company] = {}
    if company_ids:
        companies = {
            company.ticker: company
            for company in db.scalars(select(Company).where(Company.id.in_(company_ids))).all()
        }
    portfolio_tickers = set(companies)
    watch_tickers: set[str] = set()
    unresolved: list[str] = []
    watch_items = list(db.scalars(select(WatchItem)).all())
    # Match exacto de todos los símbolos en un IN (antes, resolve_company por
    # símbolo). resolve_companies (lote) solo se usa para los que no casan exacto
    # (sufijo de mercado, clase de acción, FIGI), con la misma política.
    wanted = sorted({item.symbol.strip().upper() for item in watch_items})
    exact = (
        {
            company.ticker: company
            for company in db.scalars(select(Company).where(Company.ticker.in_(wanted))).all()
        }
        if wanted
        else {}
    )
    for company in exact.values():
        watch_tickers.add(company.ticker)
        companies.setdefault(company.ticker, company)
    # Los que no casan exacto, en lote (1-2 IN): el coste no crece con el
    # numero de simbolos.
    pending = [symbol for symbol in wanted if symbol not in exact]
    resolved, missing = resolve_companies(db, pending)
    for company in resolved:
        watch_tickers.add(company.ticker)
        companies.setdefault(company.ticker, company)
    missing_set = set(missing)
    unresolved.extend(
        item.symbol for item in watch_items if item.symbol.strip().upper() in missing_set
    )

    entries = [
        CompanyEntry(
            ticker=ticker,
            name=company.name or "",
            sector=company.sector or "",
            industry=company.industry or "",
            in_portfolio=ticker in portfolio_tickers,
            in_watchlist=ticker in watch_tickers,
        )
        for ticker, company in companies.items()
    ]
    notes_by_ticker: dict[str, list[Note]] = {}
    texts: dict[str, str] = {}
    notes_by_company = _load_thesis_notes_by_company(db, list(companies.values()))
    for ticker, company in companies.items():
        notes = notes_by_company.get(company.id, [])
        if not notes:
            continue
        notes_by_ticker[ticker] = notes
        texts[ticker] = "\n\n".join(
            part
            for note in notes
            for part in [note.body, *(source.statement for source in note.sources)]
            if part
        )
    names = {ticker: company.name or "" for ticker, company in companies.items()}
    mentions = {
        ticker: found
        for ticker, text in texts.items()
        if (found := find_mentions(text, {other: name for other, name in names.items() if other != ticker}))
    }
    content = build_obsidian_vault(entries, notes_by_ticker, mentions, unresolved_symbols=unresolved)
    return _zip_response(content, "gerarai-obsidian-vault.zip")
