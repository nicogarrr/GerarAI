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
from datetime import date

import httpx
from sqlalchemy import select

from app.core.errors import redact_secrets
from app.models import KnowledgeCollection
from app.services.knowledge_library_service import KnowledgeLibraryService

COLLECTION_NAME = "Corpus libre value investing"
COLLECTION_SLUG = "corpus-libre-value-investing"

NUMANTIA_AUTHOR = "Emérito Quintana (Numantia Patrimonio)"
NUMANTIA_HOME = "https://numantiapatrimonio.com/"

BUFFETT_AUTHOR = "Warren E. Buffett (Berkshire Hathaway)"

AZVALOR_AUTHOR = "Azvalor Asset Management"
AZVALOR_INDEX = "https://www.azvalor.com/categorias_anuncios/cartas-a-inversores/"

MAGALLANES_AUTHOR = "Magallanes Value Investors"
MAGALLANES_NOTICIAS = "https://magallanesvalue.com/noticias/"

USER_AGENT = "GerarAI research corpus ingest (contact: owner-configured)"
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


# Manifiesto estatico de cartas anuales de Buffett (Berkshire Hathaway), una por
# entrada: (anio de la carta, ruta en berkshirehathaway.com/letters/, fecha de
# firma que consta en el propio documento o None si el documento no la declara).
# Verificado el 2026-10-20 con una peticion real por enlace: 200, contenido de
# Berkshire y fecha de firma del anio siguiente al de la carta (la de 2007
# solo declara "February 2008", sin dia). El indice oficial se scrapeaba con regex,
# pero Berkshire sirve siempre Content-Encoding: br (incluso pidiendo
# identity): con un httpx sin brotli el HTML llegaba sin decodificar y el
# discovery devolvia lista vacia en silencio (corpus sin Buffett). Para anadir
# la carta de un anio nuevo: verificar el enlace igual y extender la lista.
BUFFETT_LETTERS: tuple[tuple[int, str, date | None], ...] = (
    (1977, "1977.html", date(1978, 3, 14)),
    (1978, "1978.html", date(1979, 3, 26)),
    (1979, "1979.html", date(1980, 3, 3)),
    (1980, "1980.html", date(1981, 2, 27)),
    (1981, "1981.html", date(1982, 2, 26)),
    (1982, "1982.html", date(1983, 3, 3)),
    (1983, "1983.html", date(1984, 3, 14)),
    (1984, "1984.html", date(1985, 2, 25)),
    (1985, "1985.html", date(1986, 3, 4)),
    (1986, "1986.html", date(1987, 2, 27)),
    (1987, "1987.html", date(1988, 2, 29)),
    (1988, "1988.html", date(1989, 2, 28)),
    (1989, "1989.html", date(1990, 3, 2)),
    (1990, "1990.html", date(1991, 3, 1)),
    (1991, "1991.html", date(1992, 2, 28)),
    (1992, "1992.html", date(1993, 3, 1)),
    (1993, "1993.html", date(1994, 3, 1)),
    (1994, "1994.html", date(1995, 3, 7)),
    (1995, "1995.html", date(1996, 3, 1)),
    (1996, "1996.html", date(1997, 2, 28)),
    (1997, "1997.html", date(1998, 2, 27)),
    (1998, "1998pdf.pdf", date(1999, 3, 1)),
    (1999, "final1999pdf.pdf", date(2000, 3, 1)),
    (2000, "2000pdf.pdf", date(2001, 2, 28)),
    (2001, "2001pdf.pdf", date(2002, 2, 28)),
    (2002, "2002pdf.pdf", date(2003, 2, 21)),
    (2003, "2003ltr.pdf", date(2004, 2, 27)),
    (2004, "2004ltr.pdf", date(2005, 2, 28)),
    (2005, "2005ltr.pdf", date(2006, 2, 28)),
    (2006, "2006ltr.pdf", date(2007, 2, 28)),
    (2007, "2007ltr.pdf", None),
    (2008, "2008ltr.pdf", date(2009, 2, 27)),
    (2009, "2009ltr.pdf", date(2010, 2, 26)),
    (2010, "2010ltr.pdf", date(2011, 2, 26)),
    (2011, "2011ltr.pdf", date(2012, 2, 25)),
    (2012, "2012ltr.pdf", date(2013, 3, 1)),
    (2013, "2013ltr.pdf", date(2014, 2, 28)),
    (2014, "2014ltr.pdf", date(2015, 2, 27)),
    (2015, "2015ltr.pdf", date(2016, 2, 27)),
    (2016, "2016ltr.pdf", date(2017, 2, 25)),
    (2017, "2017ltr.pdf", date(2018, 2, 24)),
    (2018, "2018ltr.pdf", date(2019, 2, 23)),
    (2019, "2019ltr.pdf", date(2020, 2, 22)),
    (2020, "2020ltr.pdf", date(2021, 2, 27)),
    (2021, "2021ltr.pdf", date(2022, 2, 26)),
    (2022, "2022ltr.pdf", date(2023, 2, 25)),
    (2023, "2023ltr.pdf", date(2024, 2, 24)),
    (2024, "2024ltr.pdf", date(2025, 2, 22)),
)


def _buffett_sources() -> list[dict]:
    """Una fuente por carta del manifiesto verificado (sin red, sin scraping)."""
    sources: list[dict] = []
    for year, path, published in BUFFETT_LETTERS:
        ext = path.rsplit(".", 1)[-1]
        sources.append(
            {
                "title": f"Berkshire Hathaway - Carta anual accionistas {year}",
                "url": f"https://www.berkshirehathaway.com/letters/{path}",
                "filename": f"Berkshire{year}.{ext}",
                "author": BUFFETT_AUTHOR,
                "document_type": "fund_letter",
                "language": "en",
                "published_on": published,
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
        sources.extend(_buffett_sources())
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
                    publication_date=source.get("published_on"),
                )
                db.commit()
                if result["status"] == "duplicate":
                    stats["duplicates"] += 1
                else:
                    stats["ingested"] += 1
            except Exception as exc:  # noqa: BLE001 - una fuente no frena al corpus
                db.rollback()
                stats["failed"].append({"title": source["title"], "error": redact_secrets(str(exc))[:200]})
            time.sleep(1.0)
    return stats
