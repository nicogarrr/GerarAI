"""Ingesta del corpus libre de cartas de value investing en la biblioteca.

Solo fuentes PUBLICAS publicadas por la propia gestora, con URL de origen
declarada en cada documento. Idempotente: la biblioteca deduplica por
checksum SHA-256. Los fallos de descarga se saltan y se listan; nunca se
inventan contenidos.

Lo usa el actor `ingest_letters_corpus` (primera carga por cuenta nueva,
encolada desde la UI) y el script CLI `scripts/ingest_corpus.py`.
"""

from __future__ import annotations

import re
import time

import httpx
from sqlalchemy import select

from app.models import KnowledgeCollection
from app.services.knowledge_library_service import KnowledgeLibraryService

COLLECTION_NAME = "Corpus libre value investing"
COLLECTION_SLUG = "corpus-libre-value-investing"

NUMANTIA_AUTHOR = "Emérito Quintana (Numantia Patrimonio)"
NUMANTIA_HOME = "https://numantiapatrimonio.com/"

BUFFETT_AUTHOR = "Warren E. Buffett (Berkshire Hathaway)"
BUFFETT_INDEX = "https://www.berkshirehathaway.com/letters/letters.html"

AZVALOR_AUTHOR = "Azvalor Asset Management"
AZVALOR_INDEX = "https://www.azvalor.com/categorias_anuncios/cartas-a-inversores/"

MAGALLANES_AUTHOR = "Magallanes Value Investors"
MAGALLANES_NOTICIAS = "https://magallanesvalue.com/noticias/"

USER_AGENT = "CavaAI research corpus ingest (contact: owner-configured)"
MAX_LETTER_PAGES_PER_SOURCE = 40


def _slug_title(slug: str) -> str:
    return slug.strip("/").rsplit("/", 1)[-1].replace("-", " ").strip()


def _extract_azvalor_pages(html: str) -> list[str]:
    """Enlaces a anuncios de cartas en el indice publico de Azvalor."""
    found = re.findall(
        r'href="(https://www\.azvalor\.com/anuncios-y-comunicados/carta-[^"]+/?)"',
        html,
        re.IGNORECASE,
    )
    return sorted(set(found))


def _extract_azvalor_gateway(html: str) -> str | None:
    """En cada anuncio, el enlace oficial a la carta en PDF: los recientes usan
    una pagina pasarela /azvalor-carta-* (redirect al PDF) y los antiguos un
    PDF directo en wp-content/uploads con "Carta" en el nombre."""
    match = re.search(r'href="(https://www\.azvalor\.com/azvalor-carta-[^"]+/?)"', html, re.IGNORECASE)
    if match:
        return match.group(1)
    match = re.search(
        r'href="(https://www\.azvalor\.com/wp-content/uploads/[^"]*Carta[^"]*\.pdf)"',
        html,
        re.IGNORECASE,
    )
    return match.group(1) if match else None


def _discover_azvalor_sources(client: httpx.Client) -> list[dict]:
    try:
        response = client.get(AZVALOR_INDEX)
        response.raise_for_status()
    except Exception:
        return []
    sources: list[dict] = []
    for page_url in _extract_azvalor_pages(response.text)[:MAX_LETTER_PAGES_PER_SOURCE]:
        try:
            page = client.get(page_url)
            page.raise_for_status()
        except Exception:
            continue
        gateway = _extract_azvalor_gateway(page.text)
        if not gateway:
            continue
        slug = _slug_title(page_url)
        sources.append(
            {
                "title": f"Azvalor - {slug}",
                "url": gateway,
                "filename": f"Azvalor-{slug.replace(' ', '_')}.pdf",
                "author": AZVALOR_AUTHOR,
                "document_type": "fund_letter",
                "language": "es",
            }
        )
        time.sleep(0.5)
    return sources


def _extract_magallanes_pdfs(html: str) -> list[str]:
    found = re.findall(
        r'href="(https://magallanesvalue\.com/wp-content/uploads/MAGALLANES-(?:CARTA|LETTER)-[^"#]+\.pdf)',
        html,
        re.IGNORECASE,
    )
    return sorted(set(found))


def _discover_magallanes_sources(client: httpx.Client) -> list[dict]:
    try:
        response = client.get(MAGALLANES_NOTICIAS)
        response.raise_for_status()
    except Exception:
        return []
    sources: list[dict] = []
    for pdf_url in _extract_magallanes_pdfs(response.text):
        filename = pdf_url.rsplit("/", 1)[-1]
        label = filename.replace("MAGALLANES-", "").replace(".pdf", "").replace("-", " ")
        label = label.removeprefix("CARTA ").removeprefix("LETTER ")
        sources.append(
            {
                "title": f"Magallanes Value Investors - Carta {label}",
                "url": pdf_url,
                "filename": filename,
                "author": MAGALLANES_AUTHOR,
                "document_type": "fund_letter",
                "language": "es",
            }
        )
    return sources


def _discover_numantia_sources(client: httpx.Client) -> list[dict]:
    """Descubre las cartas publicadas en la web de la gestora (home lista los
    PDFs vigentes: anuales + semestrales sueltas). Si la home no responde,
    se devuelve lista vacia y se reporta - nunca se fabrican URLs."""
    try:
        response = client.get(NUMANTIA_HOME)
        response.raise_for_status()
    except Exception:
        return []
    sources: list[dict] = []
    seen: set[str] = set()
    for href in re.findall(r'href="(pdfs/[^"]+\.pdf)"', response.text, re.IGNORECASE):
        if href in seen:
            continue
        seen.add(href)
        filename = href.rsplit("/", 1)[-1]
        label = filename.replace("Numantia", "").replace(".pdf", "").strip("_") or "?"
        sources.append(
            {
                "title": f"Numantia Patrimonio - Carta {label}",
                "url": f"https://numantiapatrimonio.com/{href}",
                "filename": filename,
                "author": NUMANTIA_AUTHOR,
                "document_type": "fund_letter",
                "language": "es",
            }
        )
    return sources


def _discover_buffett_sources(client: httpx.Client) -> list[dict]:
    """Lee el indice publico de cartas de Berkshire y declara cada enlace.

    El indice lista las cartas con su año; solo se aceptan enlaces del propio
    dominio (html/htm/pdf). Si el indice no responde, se devuelve lista vacia
    y se reporta - nunca se fabrican URLs.
    """
    try:
        response = client.get(BUFFETT_INDEX)
        response.raise_for_status()
    except Exception:
        return []
    sources: list[dict] = []
    for href, label in re.findall(
        r'href="([^"]+\.(?:html?|pdf))"[^>]*>([^<]*)', response.text, re.IGNORECASE
    ):
        if href.startswith("http") and "berkshirehathaway.com" not in href:
            continue
        url = href if href.startswith("http") else f"https://www.berkshirehathaway.com/letters/{href}"
        year_match = re.search(r"(19|20)\d{2}", label) or re.search(r"(19|20)\d{2}", href)
        if not year_match:
            continue
        year = year_match.group(0)
        ext = href.rsplit(".", 1)[-1].lower()
        sources.append(
            {
                "title": f"Berkshire Hathaway - Carta anual accionistas {year}",
                "url": url,
                "filename": f"Berkshire{year}.{ext}",
                "author": BUFFETT_AUTHOR,
                "document_type": "fund_letter",
                "language": "en",
            }
        )
    return sources


def get_or_create_corpus_collection(db) -> KnowledgeCollection:
    collection = db.scalar(select(KnowledgeCollection).where(KnowledgeCollection.slug == COLLECTION_SLUG))
    if collection is None:
        collection = KnowledgeCollection(
            name=COLLECTION_NAME,
            slug=COLLECTION_SLUG,
            description="Corpus público y libre de value investing (cartas de gestores, fuentes declaradas).",
            collection_type="system",
        )
        db.add(collection)
        db.flush()
    return collection


def ingest_free_corpus(db) -> dict:
    """Descarga e ingiere el corpus libre para el tenant de la sesion.

    La sesion llega con db.info["tenant_id"] fijado (actor o CLI). Devuelve
    stats: {"ingested", "duplicates", "failed", "skipped_sources"}.
    """
    stats = {"ingested": 0, "duplicates": 0, "failed": [], "skipped_sources": []}

    service = KnowledgeLibraryService()
    collection = get_or_create_corpus_collection(db)
    db.commit()

    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=60, follow_redirects=True) as client:
        sources = _discover_numantia_sources(client)
        if not sources:
            stats["skipped_sources"].append("numantia_home_unreachable")
        buffett = _discover_buffett_sources(client)
        if not buffett:
            stats["skipped_sources"].append("buffett_index_unreachable")
        sources.extend(buffett)
        for name, discoverer in (
            ("azvalor", _discover_azvalor_sources),
            ("magallanes", _discover_magallanes_sources),
        ):
            found = discoverer(client)
            if not found:
                stats["skipped_sources"].append(f"{name}_unreachable_or_empty")
            sources.extend(found)

        for source in sources:
            try:
                response = client.get(source["url"])
                response.raise_for_status()
                result = service.ingest_bytes(
                    db,
                    title=source["title"],
                    content=response.content,
                    filename=source["filename"],
                    document_type=source["document_type"],
                    collection_id=collection.id,
                    author=source["author"],
                    source_url=source["url"],
                    language=source["language"],
                )
                db.commit()
                if result["status"] == "duplicate":
                    stats["duplicates"] += 1
                else:
                    stats["ingested"] += 1
            except Exception as exc:  # noqa: BLE001 - una fuente no frena al corpus
                db.rollback()
                stats["failed"].append({"title": source["title"], "error": str(exc)[:200]})
            time.sleep(1.0)
    return stats
