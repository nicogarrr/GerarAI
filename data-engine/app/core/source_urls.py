"""URLs de fuente que se pueden enlazar.

Antes de #2968 la ingesta ESEF guardaba en ``Document.source_url`` un texto
inventado («https://filings.xbrl.org/api/filings (fxo_id=…)») que no es un
filing. La ingesta ya no lo escribe y lo limpia al reingerir; hasta entonces
las filas antiguas se neutralizan al LEER, sin migracion de datos.
"""

FABRICATED_ESEF_URL_MARKER = "api/filings (fxo_id="


def linkable_source_url(url: str | None) -> str | None:
    """La URL tal cual, o None si es el enlace ESEF fabricado de antes de #2968."""
    if url and FABRICATED_ESEF_URL_MARKER in url:
        return None
    return url
