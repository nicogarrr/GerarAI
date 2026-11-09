"""URLs de fuente que se pueden enlazar.

Antes de #2968 la ingesta ESEF guardaba en ``Document.source_url`` un texto
inventado («https://filings.xbrl.org/api/filings (fxo_id=…)») que no es un
filing. La ingesta ya no lo escribe y lo limpia al reingerir; hasta entonces
las filas antiguas se neutralizan al LEER, sin migracion de datos.
"""

import re

FABRICATED_ESEF_URL_MARKER = "api/filings (fxo_id="
_GENERIC_EDGAR = "cgi-bin/browse-edgar"
_ACCESSION = re.compile(r"^(\d{10})-?(\d{2})-?(\d{6})$")


def linkable_source_url(url: str | None) -> str | None:
    """La URL tal cual, o None si es el enlace ESEF fabricado de antes de #2968."""
    if url and FABRICATED_ESEF_URL_MARKER in url:
        return None
    return url


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
