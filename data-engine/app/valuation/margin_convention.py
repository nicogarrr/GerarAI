"""Explicit provenance of a stored margin, never inferred from date or value."""

MARGIN_OF_SAFETY_CONVENTION = "discount_to_value_v1"
MARGIN_OF_SAFETY_FORMULA = "(V - P) / V"


def margin_convention_known(basis: dict | None) -> bool:
    return (basis or {}).get("margin_of_safety_convention") == MARGIN_OF_SAFETY_CONVENTION


def historical_margin_note(basis: dict | None) -> str:
    if margin_convention_known(basis):
        return "Convención verificada: (V - P) / V."
    return (
        "Cifra archivada con fórmula no verificada; no es un margen comparable "
        "con el actual (V - P) / V. Se conserva el texto original."
    )


def known_margin_status(thesis_status: str | None) -> str:
    """A known formula is indicative until its thesis claims final publication.

    This does not certify the economic assumptions. Publication gates still
    withhold archived or unpublishable final models independently.
    """
    return "verified" if thesis_status in {"final", "published"} else "indicative"
