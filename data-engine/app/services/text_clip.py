"""Recorte de textos de display sin partir palabras."""


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
