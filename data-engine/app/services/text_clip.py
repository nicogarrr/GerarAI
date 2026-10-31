"""Recorte de textos de display sin partir palabras."""

import re

# Saneado ACOTADO a los casos de pegado observados al extraer texto de HTML
# (etiquetas inline sin separador, saltos de línea dentro de números). Cada
# regla evita tocar nombres propios, tickers ni decimales en formato español:
#  - «$210. 32» -> «$210.32» (solo punto; la coma española «1, 23» no se toca)
#  - «~$794Street» -> «~$794 Street» (solo ≥2 dígitos pegados a mayúscula;
#    tickers cortos como «3M» o «B2B» quedan fuera)
#  - «What Happened?Coherent» -> «What Happened? Coherent»
#  - «(FY)..» -> «(FY).» (sin tocar la elipsis «...» ni «…»)
#  - «StockCurrent» -> «Stock Current» (≥4 minúsculas + palabra Capitalizada,
#    con guarda de marcas camelCase conocidas como iPhone, eBay o ExxonMobil)
_BROKEN_DECIMAL = re.compile(r"(?<=\d)\.\s+(?=\d)")
_GLUED_DIGIT_UPPER = re.compile(r"(?<!\d)(\d{2,})([A-ZÁÉÍÓÚÑÐ])")
_GLUED_AFTER_CLOSE = re.compile(r"(?<=[?!])(?=\S)")
_DOUBLE_PERIOD = re.compile(r"(?<![.])\.{2}(?![.])")
# Sin heurística camelCase general: nombres reales (SpaceMobile, UnitedHealth,
# ServiceNow…) son indistinguibles del pegado. Solo se separan las cadenas
# exactas observadas en producción al perderse el separador del HTML.
_KNOWN_GLUED = {"StockCurrent": "Stock Current"}
_KNOWN_GLUED_RE = re.compile(
    r"\b(" + "|".join(re.escape(w) for w in _KNOWN_GLUED) + r")\b"
) if _KNOWN_GLUED else None


def normalize_scraped_text(text: str) -> str:
    """Sanea separadores perdidos en texto scrapeado antes de resumirlo o
    mostrarlo. Acotado a patrones de pegado HTML observados; no traduce ni
    reescribe contenido y no toca nombres, tickers ni decimales españoles."""
    cleaned = " ".join((text or "").split())
    cleaned = _BROKEN_DECIMAL.sub(".", cleaned)
    cleaned = _GLUED_DIGIT_UPPER.sub(r"\1 \2", cleaned)
    cleaned = _GLUED_AFTER_CLOSE.sub(" ", cleaned)
    cleaned = _DOUBLE_PERIOD.sub(".", cleaned)
    if _KNOWN_GLUED_RE is not None:
        cleaned = _KNOWN_GLUED_RE.sub(lambda m: _KNOWN_GLUED[m.group(1)], cleaned)
    return cleaned


def clip_words(text: str, limit: int, ellipsis: str = "…") -> str:
    """Devuelve `text` tal cual si cabe en `limit` caracteres; si no, lo corta en
    la ultima palabra completa y anade la elipsis. Sin espacios aprovechables
    (una sola palabra gigante) corta en `limit`."""
    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    cut = text[:limit]
    # Si el siguiente caracter es un espacio, la palabra final ya estaba completa.
    if not text[limit].isspace():
        space = cut.rfind(" ")
        if space > 0:
            cut = cut[:space]
    return cut.rstrip(" ,;:.-") + ellipsis
