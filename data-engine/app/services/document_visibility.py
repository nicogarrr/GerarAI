"""Visibilidad de documentos con re-ingestas historicas (F252).

La misma pieza de la SEC se re-ingiere a diario con una deriva de bytes
minima (~14 bytes), asi que el checksum no la captura y cada re-ingesta
creaba una fila visible en la ficha de empresa y en la vista global.

La identidad por URL solo se aplica a URLs de ARCHIVO INMUTABLE (SEC
Archives): ahi, la misma URL es el mismo filing aunque los bytes deriven.
Cualquier otra URL puede servir contenido que cambia con el tiempo (feeds,
paginas vivas, URLs reutilizadas) y ante esa ambiguedad NO se oculta nada:
solo se colapsan los grupos de archivo inmutable. De cada grupo se conserva
la fila con mayor fecha de publicacion (desempate: mayor id, la ingesta mas
reciente), no simplemente el mayor id.
"""

from sqlalchemy import desc, func, or_, select

from app.models import Document

SEC_ARCHIVE_URL_PREFIXES = (
    "https://www.sec.gov/Archives/",
    "http://www.sec.gov/Archives/",
)


def is_immutable_archive_url(url: str | None) -> bool:
    """True solo si la URL apunta a un archivo inmutable de la SEC."""
    return bool(url) and url.startswith(SEC_ARCHIVE_URL_PREFIXES)


def _archive_url_predicate():
    return or_(
        *[
            Document.source_url.like(f"{prefix}%")
            for prefix in SEC_ARCHIVE_URL_PREFIXES
        ]
    )


def without_archive_duplicates(statement, *, company_ids: list[int] | None = None):
    """Excluye las re-ingestas del mismo filing de archivo inmutable.

    Devuelve el statement con un join al ranking por (tenant, empresa, URL):
    solo pasa la fila mejor de cada grupo de archivo (mayor published_at,
    desempate mayor id). Las filas sin URL o con URL no-archivo pasan
    siempre: ante la duda no se oculta contenido.
    """
    # Filtering on the partition key does not change the winner within any
    # requested company, and avoids ranking unrelated companies' documents.
    scope = () if company_ids is None else (Document.company_id.in_(company_ids),)
    if company_ids is not None:
        statement = statement.where(Document.company_id.in_(company_ids))
    ranked = (
        select(
            Document.id.label("id"),
            func.row_number()
            .over(
                partition_by=(
                    Document.tenant_id,
                    Document.company_id,
                    Document.source_url,
                ),
                order_by=(
                    desc(Document.published_at).nullslast(),
                    desc(Document.id),
                ),
            )
            .label("archive_rank"),
        )
        .where(*scope)
        .where(Document.source_url.isnot(None))
        .where(_archive_url_predicate())
        .subquery()
    )
    return statement.outerjoin(ranked, ranked.c.id == Document.id).where(
        or_(ranked.c.archive_rank.is_(None), ranked.c.archive_rank == 1)
    )
