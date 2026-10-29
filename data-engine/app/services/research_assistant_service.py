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

from app.models import (
    Company,
    Document,
    DocumentChunk,
    FinancialFact,
    NewsEvent,
    ResearchReview,
    ThesisVersion,
)
from app.services.text_clip import clip_words
from app.services.thesis_publication_gate import archived_thesis_notice, thesis_withheld_reason
from app.valuation.margin_convention import historical_margin_note


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
    "valoracion": frozenset({"valuation"}),
    "competencia": frozenset({"competition", "competitors"}),
    "crecimiento": frozenset({"growth"}),
    "inversion": frozenset({"investment", "capex"}),
    "inversiones": frozenset({"investment", "investments", "capex"}),
    "espectro": frozenset({"spectrum"}),
    "gastos": frozenset({"expenses", "expense", "costs"}),
    "costes": frozenset({"costs", "cost"}),
    "costos": frozenset({"costs", "cost"}),
    "flujo": frozenset({"flow", "cash"}),
    "producto": frozenset({"product", "products"}),
    "productos": frozenset({"product", "products"}),
    "clientes": frozenset({"customers", "customer"}),
    "demanda": frozenset({"demand"}),
    "recompra": frozenset({"repurchase", "buyback"}),
    "recompras": frozenset({"repurchase", "repurchases", "buyback"}),
    "patentes": frozenset({"patent", "patents"}),
    "regulacion": frozenset({"regulation", "regulatory"}),
    "aranceles": frozenset({"tariffs", "tariff"}),
    "cadena": frozenset({"supply", "chain"}),
}


# Palabras de pregunta general («¿Qué sabemos, qué falta y qué contradicciones
# hay?»): no nombran ningún tema, así que no pueden coincidir con un extracto.
_GENERAL = frozenset({
    "sabemos", "saber", "sabe", "falta", "faltan", "contradicciones", "contradiccion",
    "resumen", "resume", "resumir", "tenemos", "evidencia", "evidencias", "fuentes",
    "datos", "informacion", "empresa", "general", "principal", "principales", "situacion",
    "tesis", "novedades", "novedad", "reciente", "recientes", "ultimas", "ultimos", "ultima",
    "ultimo", "noticias", "analisis", "pasa", "pasado", "ocurrido", "cuentame", "hablame",
    "explica", "explicame", "cuenta", "acerca", "tema", "temas", "tengo", "hay", "ahora",
})


def is_general_question(question: str, ticker: str) -> bool:
    terms = _tokens(question) - _tokens(ticker)
    return bool(terms) and not (terms - _GENERAL)


def _overview(citations: list[dict]) -> list[dict]:
    """Pregunta general: las fuentes más recientes, primarias antes que titulares, una por fuente."""
    order = {"thesis_record": 0, "document_chunk": 1, "financial_fact": 2, "news_event": 3}
    picked, seen = [], set()
    for citation in sorted(citations, key=lambda c: order.get(c["kind"], 3)):
        key = (citation["kind"], citation["source"])
        if key in seen:
            continue
        seen.add(key)
        picked.append(citation)
    return picked


def _rank(citations: list[dict], question: str, ticker: str) -> list[dict]:
    terms = _tokens(question) - _tokens(ticker)
    if not terms:
        return []
    if not (terms - _GENERAL):
        return _overview(citations)
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
                          "as_of": f"{row.date.isoformat()} ({label})", "excerpt": clip_words(headline.strip(), 500, ellipsis="")})
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
                          "as_of": doc.published_at.isoformat(), "excerpt": clip_words(chunk.text, 450, ellipsis="")})
    citations.extend(_thesis_citations(db, company, tenant_id))
    return _rank(citations, question, company.ticker)


def _money(value, currency: str | None) -> str:
    """USD en formato en-US ($120.50); el resto de divisas, es-ES con su código."""
    amount = float(value)
    if currency == "USD":
        return f"${amount:,.2f}"
    text = f"{amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{text} {currency or ''}".strip()


def _thesis_citations(db: Session, company: Company, tenant_id: int) -> list[dict]:
    """Tesis guardada del tenant. Cifras (valores, margen de seguridad) solo de
    una tesis PUBLICADA, tal como se guardaron; un borrador se cita como borrador,
    sin cifras ni margen."""
    versions = db.scalars(select(ThesisVersion).where(
        ThesisVersion.tenant_id == tenant_id, ThesisVersion.company_id == company.id,
    ).order_by(desc(ThesisVersion.version)).limit(20)).all()
    if not versions:
        return []
    latest = versions[0]
    published = next((v for v in versions if v.status == "published"), None)

    def stamp(thesis: ThesisVersion) -> str:
        return thesis.created_at.date().isoformat() if thesis.created_at else "fecha sin datos"

    def record(thesis: ThesisVersion, excerpt: str) -> dict:
        return {"id": f"thesis_record:{thesis.id}", "kind": "thesis_record",
                "source": f"Tesis v{thesis.version} de {company.ticker}", "url": None,
                "as_of": stamp(thesis), "excerpt": excerpt}

    def figures(thesis: ThesisVersion) -> str:
        reason = thesis_withheld_reason(db, thesis)
        if reason:
            return archived_thesis_notice(thesis, reason)
        parts = [f"Tesis v{thesis.version} publicada, rating {thesis.rating}."]
        values = [("bajista", thesis.bear_value), ("base", thesis.base_value), ("alcista", thesis.bull_value)]
        shown = [f"{label} {_money(v, company.currency)}" for label, v in values if v is not None]
        if shown:
            parts.append("Valoración por acción: " + ", ".join(shown) + ".")
        if thesis.expected_value is not None:
            parts.append(f"Valor esperado {_money(thesis.expected_value, company.currency)}.")
        if thesis.margin_of_safety is not None:
            parts.append(f"Margen de seguridad archivado {float(thesis.margin_of_safety) * 100:,.1f} %".replace(".", ",") + ". "
                         + historical_margin_note(thesis.valuation_basis))
        if thesis.executive_summary:
            parts.append(clip_words(thesis.executive_summary.strip(), 300, ellipsis=""))
        return " ".join(parts)

    citations = []
    if published is not None:
        citations.append(record(published, figures(published)))
    if latest is not published:
        citations.append(record(
            latest,
            f"Tesis v{latest.version} en estado {latest.status}: borrador sin publicar, sin cifras de "
            "valoración ni margen de seguridad.",
        ))
    return citations


def _linked_review_news(db: Session, review: ResearchReview, company: Company, tenant_id: int) -> list[dict]:
    """A selected review is a source anchor, never evidence for another tenant."""
    if not review.news_event_id:
        return []
    row = db.scalar(select(NewsEvent).where(
        NewsEvent.id == review.news_event_id, NewsEvent.tenant_id == tenant_id,
        NewsEvent.company_id == company.id,
    ))
    if row is None:
        return []
    provenance = row.metadata_ or {}
    headline = provenance.get("source_headline")
    date_source = provenance.get("date_source")
    if provenance.get("connector") == "gdelt" and date_source == "source":
        date_source = "gdelt_first_seen"
    if not _url(row.url) or date_source not in {"source", "gdelt_first_seen"} or not isinstance(headline, str) or not headline.strip():
        return []
    label = "primera detección GDELT" if date_source == "gdelt_first_seen" else "fecha de la fuente"
    return [{"id": f"news_event:{row.id}", "kind": "news_event", "source": row.source,
             "url": _url(row.url), "as_of": f"{row.date.isoformat()} ({label})",
             "excerpt": clip_words(headline.strip(), 500, ellipsis="")}]


def _asks_about_selected_review(question: str, ticker: str) -> bool:
    # Only deictic/general follow-ups use the anchor. A specific new topic must
    # still match retrieved evidence; adding 'review' must not bypass ranking.
    terms = _tokens(question) - _tokens(ticker)
    context_words = _GENERAL | {"noticia", "revision", "ticket", "articulo", "esta", "esto", "esa", "ese", "ella", "ello", "explicamelo", "explicala"}
    return bool(terms) and not (terms - context_words)


def answer(db: Session, payload) -> dict:
    tenant_id = _tenant(db)
    if not payload.ticker:
        return _empty(payload.mode, "Indica un ticker para recuperar fuentes verificables del espacio de trabajo.")
    company = _company(db, payload.ticker)
    review = _review(db, payload.review_id, company.id, tenant_id)
    anchored = review is not None and _asks_about_selected_review(payload.question, company.ticker)
    citations = (_linked_review_news(db, review, company, tenant_id) if anchored
                 else _evidence(db, company, tenant_id, payload.question))
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
        stamp = re.sub(r"(\d{4}-\d{2}-\d{2})T[\d:.+\-Z]+", r"\1", citation["as_of"] or "fecha sin datos")
        statement = (f"Dato documentado en {citation['source']} ({stamp}): {citation['excerpt']}"
                     if citation["kind"] == "financial_fact"
                     else f"Registro guardado, {citation['source']} ({stamp}): {citation['excerpt']}"
                     if citation["kind"] == "thesis_record"
                     else f"Extracto de {citation['source']} ({stamp}): {citation['excerpt']}"
                     if citation["kind"] == "document_chunk"
                     else f"Titular atribuido a {citation['source']} ({stamp}): {citation['excerpt']}")
        lines.append(f"{statement} [{citation['id']}]")
    note = ("Fuente primaria documental disponible para consulta; este resumen no verifica el documento completo."
            if primary else "Fuente primaria no consultada o no disponible; los titulares no verifican sus afirmaciones.")
    if is_general_question(payload.question, company.ticker):
        note = "Pregunta general: se muestran las fuentes más recientes, sin filtrar por tema. " + note
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
