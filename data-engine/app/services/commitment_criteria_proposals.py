"""PROPUESTAS de criterio de cumplimiento para revision humana. NO son criterios revisados.

Cada propuesta cita literalmente la llamada oficial registrada (URL, pagina, hash) y lista las
ambiguedades que un revisor debe resolver antes de que exista un criterio. Nada aqui lo consume el
motor de reconciliacion (que exige un criterio estructurado REVISADO), no se crea ninguna
aprobacion y no se mide ningun resultado. Ninguna propuesta es una metrica de cumplimiento.
"""
from __future__ import annotations

from dataclasses import dataclass

PENDING_REVIEW = "propuesta_sin_revisar"


@dataclass(frozen=True)
class CriterionProposal:
    ticker: str
    source_url: str  # activo registrado exacto
    period: str
    page: int  # pagina del PDF (1-based)
    quote: str  # literal, tal cual en el texto extraido
    claim: str  # que se promete, en palabras del revisor potencial
    due: str | None  # fecha limite inferida de la propia cita (sin inventar)
    evaluable_with: str  # que documento futuro permitiria comparar
    ambiguities: tuple[str, ...]
    status: str = PENDING_REVIEW
    consumable_by_engine: bool = False

    def __post_init__(self) -> None:
        if self.status != PENDING_REVIEW or self.consumable_by_engine:
            raise ValueError("una propuesta no puede declararse revisada ni consumible")


PROPOSALS: tuple[CriterionProposal, ...] = (
    CriterionProposal(
        ticker="UBER",
        source_url="https://s23.q4cdn.com/407969754/files/doc_events/2026/Aug/05/Uber-Q2-26-Earnings-Call-Transcript.pdf",
        period="Q2 2026",
        page=7,
        quote="We'll be in 15 markets by the end of the year.",
        claim="Uber estara presente en 15 mercados (de vehiculos autonomos con socios, contexto "
              "Waymo/otros) a fin de 2026",
        due="2026-12-31",
        evaluable_with="Comunicado/llamada de resultados Q4 2026 (o documento oficial que liste "
                       "mercados AV) posterior al 2026-12-31",
        ambiguities=(
            "'markets' no esta definido en la cita: confirmar si son mercados con AV de socios "
            "(Waymo, otros) y no el total de ciudades de Uber",
            "'by the end of the year' = 2026-12-31 segun la fecha de la llamada (2026-08-05)",
            "Requiere un recuento oficial comparable; si el documento posterior no lo da, el "
            "criterio queda sin evaluar (abstencion), no 'incumplido'",
        ),
    ),
)


def verify_quote_in_text(p: CriterionProposal, text: str) -> dict:
    """Comprueba que la cita literal esta en el texto (una vez) y devuelve pagina/offset reales."""
    n = text.count(p.quote)
    if n != 1:
        return {"ok": False, "reason": "cita_ausente" if n == 0 else "cita_ambigua", "count": n}
    pos = text.index(p.quote)
    page = text[:pos].count("\f") + 1
    return {"ok": page == p.page, "reason": "ok" if page == p.page else "pagina_distinta",
            "page": page, "offset": pos}
