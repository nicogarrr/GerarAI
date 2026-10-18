"""Tenant-validated evidence for read-only chat and guided review.

Never call the legacy /chat service: it may write memory on trigger phrases.
Never use user text or model output as an instruction to retrieve other tenants.
"""
from __future__ import annotations

import re
import unicodedata
from urllib.parse import urlsplit

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models import Company, Document, DocumentChunk, FinancialFact, NewsEvent, ResearchReview
from app.services.text_clip import clip_words


def _url(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = urlsplit(value.strip())
        return value.strip() if parsed.scheme in {"http", "https"} and parsed.hostname and not parsed.username else None
    except ValueError:
        return None


def _company(db: Session, ticker: str) -> Company:
    company = db.scalar(select(Company).where(Company.ticker == ticker.upper()))
    if not company:
        raise LookupError("Ticker no encontrado")
    return company


def _tenant(db: Session) -> int:
    tenant_id = db.info.get("tenant_id")
    if tenant_id is None:
        raise LookupError("Espacio de trabajo no disponible")
    return tenant_id


def _review(db: Session, review_id: int | None, company_id: int, tenant_id: int) -> ResearchReview | None:
    if review_id is None:
        return None
    review = db.scalar(select(ResearchReview).where(
        ResearchReview.id == review_id, ResearchReview.company_id == company_id,
        ResearchReview.tenant_id == tenant_id,
    ))
    if review is None:
        raise LookupError("Ticket no encontrado para este ticker")
    return review


def guide_context(db: Session, ticker: str) -> dict:
    tenant_id = _tenant(db)
    company = _company(db, ticker)
    reviews = db.scalars(select(ResearchReview).where(
        ResearchReview.tenant_id == tenant_id, ResearchReview.company_id == company.id,
        ResearchReview.status == "open",
    ).order_by(desc(ResearchReview.created_at)).limit(10)).all()
    legacy_count = db.scalar(select(NewsEvent.id).where(
        NewsEvent.tenant_id == tenant_id, NewsEvent.company_id == company.id,
        NewsEvent.metadata_["source_headline"].as_string().is_(None),
    ).limit(1)) is not None
    news = db.scalars(select(NewsEvent).where(
        NewsEvent.tenant_id == tenant_id, NewsEvent.company_id == company.id,
        NewsEvent.metadata_["source_headline"].as_string().is_not(None),
    ).order_by(desc(NewsEvent.date)).limit(10)).all()
    # Composite legacy titles mix ticker, headline and snippet. Never label
    # them as publisher-authored; omit them from the typed context response.
    original_news = [row for row in news if isinstance((row.metadata_ or {}).get("source_headline"), str)
                     and (row.metadata_ or {})["source_headline"].strip()]
    return {
        "ticker": company.ticker, "review_id": reviews[0].id if reviews else None,
        "open_reviews": [{"id": row.id, "status": row.status, "summary": row.summary} for row in reviews],
        "latest_news": [{"id": row.id, "title": row.metadata_["source_headline"].strip(), "source": row.source,
                         "source_url": _url(row.url), "date": row.date,
                         "date_source": (row.metadata_ or {}).get("date_source", "unknown")}
                        for row in original_news],
        "missing_data": (["No hay titulares originales verificables para este ticker."]
                         if not original_news else
                         ["Algunas noticias antiguas carecen del titular original y se han omitido."]
                         if legacy_count or len(original_news) < len(news) else []),
    }



_STOP = frozenset({"sobre", "para", "esta", "este", "dice", "dime", "cual", "cuáles", "what", "does", "about", "the", "and", "hay", "qué", "que", "los", "las", "del", "con", "por", "una", "uno", "como", "cómo", "documento"})


def _tokens(text: str) -> set[str]:
    normalized = "".join(c for c in unicodedata.normalize("NFKD", text.casefold()) if not unicodedata.combining(c))
    return {token for token in re.findall(r"[a-z0-9]+", normalized) if len(token) >= 3 and token not in _STOP}


# Preguntas en espanol contra filings en ingles: sin esto "guia" nunca coincide con
# "guidance" y la respuesta cae a "Sin datos citables" aunque haya fuentes. Solo
# amplia COMO se puede escribir un termino; el match sigue siendo obligatorio y
# no se cita nada que no contenga una de las formas.
_ES_EN: dict[str, frozenset[str]] = {
    "guia": frozenset({"guidance", "outlook"}),
    "guias": frozenset({"guidance", "outlook"}),
    "prevision": frozenset({"guidance", "outlook", "forecast"}),
    "perspectivas": frozenset({"outlook"}),
    "ingresos": frozenset({"revenue", "revenues"}),
    "ventas": frozenset({"sales", "revenue"}),
    "beneficio": frozenset({"earnings", "income", "profit"}),
    "beneficios": frozenset({"earnings", "income", "profit"}),
    "ganancias": frozenset({"earnings", "income", "profit"}),
    "resultados": frozenset({"results", "earnings"}),
    "perdida": frozenset({"loss"}),
    "perdidas": frozenset({"loss", "losses"}),
    "deuda": frozenset({"debt"}),
    "caja": frozenset({"cash"}),
    "efectivo": frozenset({"cash"}),
    "margen": frozenset({"margin"}),
    "margenes": frozenset({"margin", "margins"}),
    "lanzamiento": frozenset({"launch"}),
    "lanzamientos": frozenset({"launch", "launches"}),
    "satelite": frozenset({"satellite"}),
    "satelites": frozenset({"satellite", "satellites"}),
    "riesgo": frozenset({"risk"}),
    "riesgos": frozenset({"risk", "risks"}),
    "dilucion": frozenset({"dilution"}),
    "acciones": frozenset({"shares", "stock"}),
    "dividendo": frozenset({"dividend"}),
    "dividendos": frozenset({"dividend", "dividends"}),
    "licencia": frozenset({"license", "licence"}),
    "espectro": frozenset({"spectrum"}),
}


def _rank(citations: list[dict], question: str, ticker: str) -> list[dict]:
    terms = _tokens(question) - _tokens(ticker)
    if not terms:
        return []
    groups = [frozenset({term}) | _ES_EN.get(term, frozenset()) for term in terms]
    ranked = []
    for citation in citations:
        haystack = _tokens(f"{citation.get('source') or ''} {citation.get('excerpt') or ''}") - _tokens(ticker)
        score = sum(1 for group in groups if group & haystack)
        if score:
            ranked.append((score, citation))
    ranked.sort(key=lambda pair: (-pair[0], pair[1]["id"]))
    if not ranked:
        return []
    # A generic overlap ('filing') cannot dilute an exact multi-term match
    # ('ITU filing') with unrelated financial facts.
    best = ranked[0][0]
    return [citation for score, citation in ranked if score == best]


def _evidence(db: Session, company: Company, tenant_id: int, question: str) -> list[dict]:
    citations = []
    facts = db.scalars(select(FinancialFact).where(
        FinancialFact.tenant_id == tenant_id, FinancialFact.company_id == company.id,
        FinancialFact.source_id.is_not(None), FinancialFact.is_reported.is_(True),
    ).order_by(desc(FinancialFact.created_at)).limit(200)).all()
    document_ids = {fact.source_id for fact in facts}
    documents = db.scalars(select(Document).where(
        Document.tenant_id == tenant_id, Document.company_id == company.id,
        Document.id.in_(document_ids),
    )).all() if document_ids else []
    by_doc = {doc.id: doc for doc in documents}
    for row in facts:
        document = by_doc.get(row.source_id)
        if document is None or not _url(document.source_url):
            continue
        citations.append({"id": f"financial_fact:{row.id}", "kind": "financial_fact",
                          "source": document.title, "url": _url(document.source_url),
                          "as_of": f"{row.fiscal_year or 'año no indicado'} {row.period}",
                          "excerpt": f"{row.metric}: {row.value} {row.unit}"})
    news = db.scalars(select(NewsEvent).where(
        NewsEvent.tenant_id == tenant_id, NewsEvent.company_id == company.id,
    ).order_by(desc(NewsEvent.date)).limit(200)).all()
    for row in news:
        provenance = row.metadata_ or {}
        date_source = provenance.get("date_source")
        if provenance.get("connector") == "gdelt" and date_source == "source":
            date_source = "gdelt_first_seen"  # legacy GDELT `seendate`
        headline = provenance.get("source_headline")
        if not _url(row.url) or date_source not in {"source", "gdelt_first_seen"} or not isinstance(headline, str) or not headline.strip():
            continue
        label = "primera detección GDELT" if date_source == "gdelt_first_seen" else "fecha de la fuente"
        citations.append({"id": f"news_event:{row.id}", "kind": "news_event",
                          "source": row.source, "url": _url(row.url),
                          "as_of": f"{row.date.isoformat()} ({label})", "excerpt": headline.strip()[:500]})
    # Seek document candidates using the question, not merely the 100 newest
    # chunks. The cap bounds work, and empty/low-overlap results fail closed.
    chunks = db.execute(select(DocumentChunk, Document).join(Document, DocumentChunk.document_id == Document.id).where(
        DocumentChunk.tenant_id == tenant_id, Document.tenant_id == tenant_id,
        Document.company_id == company.id,
    ).order_by(desc(Document.published_at)).limit(2000)).all()
    for chunk, doc in chunks:
        if not _url(doc.source_url) or not doc.published_at:
            continue
        citations.append({"id": f"document_chunk:{chunk.id}", "kind": "document_chunk",
                          "source": doc.title, "url": _url(doc.source_url),
                          "as_of": doc.published_at.isoformat(), "excerpt": chunk.text[:450]})
    return _rank(citations, question, company.ticker)


def answer(db: Session, payload) -> dict:
    tenant_id = _tenant(db)
    if not payload.ticker:
        return _empty(payload.mode, "Indica un ticker para recuperar fuentes verificables del espacio de trabajo.")
    company = _company(db, payload.ticker)
    review = _review(db, payload.review_id, company.id, tenant_id)
    citations = _evidence(db, company, tenant_id, payload.question)
    if not citations:
        response = _empty(payload.mode, f"Sin datos citables para {company.ticker}.")
        response["review_id"] = review.id if review else None
        return response
    # The deterministic baseline quotes only retrieved, tenant-validated rows.
    # It is not an LLM conclusion and does not elevate a headline to a fact.
    selected = citations[:6]
    lines = []
    primary = any(citation["kind"] in {"financial_fact", "document_chunk"} for citation in selected)
    for citation in selected:
        stamp = citation["as_of"] or "fecha sin datos"
        statement = (f"Dato documentado en {citation['source']} ({stamp}): {citation['excerpt']}"
                     if citation["kind"] == "financial_fact"
                     else f"Extracto de {citation['source']} ({stamp}): {citation['excerpt']}"
                     if citation["kind"] == "document_chunk"
                     else f"Titular atribuido a {citation['source']} ({stamp}): {citation['excerpt']}")
        lines.append(f"{statement} [{citation['id']}]")
    note = ("Fuente primaria documental disponible para consulta; este resumen no verifica el documento completo."
            if primary else "Fuente primaria no consultada o no disponible; los titulares no verifican sus afirmaciones.")
    if payload.mode == "guide":
        note += " Contrasta el documento primario antes de aceptar una conclusión del ticket."
    return {"mode": payload.mode, "status": "answered", "answer": "\n".join([*lines, note]),
            "sections": [{"key": "facts", "body": "\n".join(lines),
                          "citation_ids": [c["id"] for c in selected]},
                         {"key": "insufficient_data", "body": note, "citation_ids": []}],
            "citations": selected,
            "missing_data": [] if primary else ["Fuente primaria no consultada o no disponible."],
            "suggested_next_steps": ["Abrir las fuentes y contrastar los hechos antes de concluir."],
            "review_id": review.id if review else None, "writeback": False}


def _empty(mode: str, reason: str) -> dict:
    return {"mode": mode, "status": "insufficient_data", "answer": reason,
            "sections": [{"key": "insufficient_data", "body": reason, "citation_ids": []}],
            "citations": [], "missing_data": [reason],
            "suggested_next_steps": ["Aporta o conecta una fuente con fecha y URL para este ticker."],
            "review_id": None, "writeback": False}
