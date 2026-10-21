"""Identidad atribuida de los cambios de tesis originados en noticias.

Un ThesisChange no enlaza con su NewsEvent, pero la ResearchReview creada
con él sí (``thesis_change_id`` + ``news_event_id``). Por ese puente la
presentación («Desde tu última visita») recupera la identidad atribuida del
evento (URL, titular original y traducción española cacheada por GerarAI) y
agrupa el mismo cambio publicado en dos idiomas o con URLs distintas.

Regla (idéntica a la del feed de noticias): solo identidad, nunca
similitud — mismo evento, misma URL normalizada, mismo titular normalizado
o traducción atribuida que coincide exactamente con el titular del otro.
Los originales no se borran: el grupo conserva las fuentes absorbidas en
``tambien_en`` con su URL revisable.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.services.news_headline_translation import display_translation, original_headline
from app.services.news_identity import normalize_headline, normalize_url


@dataclass
class ChangeItem:
    """Un cambio de tesis proyectado para presentación, con su identidad."""

    resumen: str
    direccion: str
    requiere_revision: bool
    fecha: str | None
    orden: int  # posición original (más reciente primero)
    news_event_id: int | None = None
    fuente_url: str | None = None
    fuente_nombre: str | None = None
    titular_original: str | None = None
    traduccion_titular: str | None = None
    tambien_en: list[dict] = field(default_factory=list)
    # Carga del caller (p. ej. el ThesisChange origen) que viaja con el grupo.
    extra: dict = field(default_factory=dict)


def identity_keys(item: ChangeItem) -> set[str]:
    """Claves de identidad atribuida de un cambio (vacías si no hay evidencia)."""
    keys: set[str] = set()
    if item.news_event_id is not None:
        keys.add(f"e:{item.news_event_id}")
    url = normalize_url(item.fuente_url)
    if url:
        keys.add(f"u:{url}")
    for text in (item.titular_original, item.traduccion_titular):
        headline = normalize_headline(text)
        if headline:
            keys.add(f"t:{headline}")
    return keys


def group_change_items(items: list[ChangeItem]) -> list[ChangeItem]:
    """Agrupa cambios con la misma identidad atribuida; conserva el más reciente.

    El representante es el primero en el orden de entrada (más reciente).
    Las fuentes absorbidas quedan en ``tambien_en`` (fuente + URL + fecha),
    en orden de llegada, sin duplicar URLs. Un cambio sin identidad nunca
    se agrupa: sin evidencia atribuida no se fusiona nada.
    """
    seen: dict[str, ChangeItem] = {}
    grouped: list[ChangeItem] = []
    for item in items:
        keys = identity_keys(item)
        representative = next((seen[key] for key in keys if key in seen), None)
        if representative is None:
            for key in keys:
                seen[key] = item
            grouped.append(item)
            continue
        representative.requiere_revision = representative.requiere_revision or item.requiere_revision
        absorbed_urls = {entry.get("url") for entry in representative.tambien_en}
        if item.fuente_url and item.fuente_url != representative.fuente_url and item.fuente_url not in absorbed_urls:
            representative.tambien_en.append(
                {"url": item.fuente_url, "fuente": item.fuente_nombre, "fecha": item.fecha}
            )
        # Las claves nuevas del absorbido (p. ej. su propio titular) también
        # identifican al grupo: una tercera fila igual a él debe caer aquí.
        for key in keys:
            seen.setdefault(key, representative)
    return grouped
