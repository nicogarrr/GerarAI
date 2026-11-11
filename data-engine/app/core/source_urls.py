"""URLs de fuente que se pueden enlazar.

Antes de #2968 la ingesta ESEF guardaba en ``Document.source_url`` un texto
inventado («https://filings.xbrl.org/api/filings (fxo_id=…)») que no es un
filing. La ingesta ya no lo escribe y lo limpia al reingerir; hasta entonces
las filas antiguas se neutralizan al LEER, sin migracion de datos.
"""

import re
from collections.abc import Mapping
from datetime import date
from typing import Any

FABRICATED_ESEF_URL_MARKER = "api/filings (fxo_id="
_GENERIC_EDGAR = "cgi-bin/browse-edgar"
_ACCESSION = re.compile(r"^(\d{10})-?(\d{2})-?(\d{6})$")


def linkable_source_url(url: str | None) -> str | None:
    """La URL tal cual, o None si es el enlace ESEF fabricado de antes de #2968."""
    if url and FABRICATED_ESEF_URL_MARKER in url:
        return None
    return url


# Un informe anual trae el ejercicio cerrado y, como comparativo, el anterior: el del ejercicio N cubre
# cierres de N y N-1 (hasta ~400 días antes, por los ejercicios de 52/53 semanas).
_FILING_COVERS_DAYS = 400


def filed_package_url(metadata: Mapping[str, Any] | None, period: str | None) -> str | None:
    """Informe oficial (filings.xbrl.org o NSM de la FCA) del que sale un hecho ESEF, o None.

    La ingesta ESEF guarda en ``metadata.filing_sources`` la URL verificada (con sha256) de cada informe anual
    que fusionó; ``merge_facts`` fusiona del más reciente al más antiguo, así que la cifra de un cierre viene del
    informe más reciente que la cubre (el de su ejercicio o el siguiente, como comparativo). Sin informe que la
    cubra, o con una URL que no es https, None: nunca un enlace inventado.
    """
    sources = (metadata or {}).get("filing_sources") if isinstance(metadata, Mapping) else None
    if not isinstance(sources, list):
        return None
    try:
        end = date.fromisoformat(str(period or "").split(":")[0][:10])
    except ValueError:
        return None
    best: tuple[date, str] | None = None
    for src in sources:
        if not isinstance(src, Mapping):
            continue
        url = linkable_source_url(str(src.get("url") or "").strip())
        try:
            filed_end = date.fromisoformat(str(src.get("period_end") or "")[:10])
        except ValueError:
            continue
        if not url or not url.startswith("https://") or " " in url:
            continue
        if 0 <= (filed_end - end).days <= _FILING_COVERS_DAYS and (best is None or filed_end > best[0]):
            best = (filed_end, url)
    return best[1] if best else None


def sec_filing_url(url: str | None, accession_number: str | None, cik: str | int | None) -> str | None:
    """El índice del filing exacto en EDGAR cuando la fuente guardada es la página genérica.

    La ingesta SEC guarda un ``Document`` por empresa cuya URL es el listado
    ``cgi-bin/browse-edgar?action=getcompany…`` (sin el filing), mientras que cada hecho
    trae su número de acceso. Con acceso + CIK el enlace va al filing del que sale la
    cifra (``/Archives/edgar/data/<cik>/<acceso>/<acceso>-index.htm``). Sin alguno de
    los dos, o si la URL ya apunta a un documento concreto, se deja la URL tal cual.
    """
    m = _ACCESSION.match(str(accession_number or "").strip())
    cik_s = str(cik or "").strip()
    if m and cik_s.isdigit() and int(cik_s) > 0 and (not url or _GENERIC_EDGAR in url):
        digits = "".join(m.groups())
        return f"https://www.sec.gov/Archives/edgar/data/{int(cik_s)}/{digits}/{'-'.join(m.groups())}-index.htm"
    return linkable_source_url(url)
