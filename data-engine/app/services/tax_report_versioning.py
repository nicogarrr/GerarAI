"""Versionado de informes fiscales persistidos: ¿el informe guardado sigue al día?

Un ``TaxReport`` se guarda tal cual se calculó (JSON). Si el código cambia un
criterio de cálculo, el informe viejo sigue devolviendo las cifras viejas hasta
que el usuario pulsa «Regenerar» (ver ``DGT_REPORT_REGENERATION.md``). Este
módulo hace verificable ese estado: compara los marcadores de criterio que el
informe guardó en su ``summary`` con los que el código aplica hoy.

No calcula ni cambia ninguna cifra fiscal y no toca la base de datos: solo lee
el ``summary`` ya persistido. Un informe sin marcador (anterior a que el
criterio se registrase) cuenta como desactualizado, nunca como vigente.
"""

from __future__ import annotations

from collections.abc import Mapping

#: Criterio de divisa en ventas de valores: ganancia en la moneda del valor y
#: conversión de la diferencia al cambio BCE de la fecha de venta (DGT V1740-17,
#: V2422-20, V0282-22, V0152-26). Fuente única: ``compute_report`` lo escribe en
#: ``summary.securities_fx_criterion`` con este valor.
SECURITIES_FX_CRITERION = "dgt_native_gain_sale_date_v1"

#: Marcadores de ``summary`` que un informe debe llevar para considerarse
#: calculado con las reglas actuales: clave -> valor vigente. Al cambiar un
#: criterio de cálculo se sube su valor aquí y los informes guardados con el
#: anterior pasan a «desactualizados» sin reescribirlos.
REQUIRED_SUMMARY_MARKERS: dict[str, str] = {
    "securities_fx_criterion": SECURITIES_FX_CRITERION,
}

REASON_MISSING_MARKER = "criterio_no_registrado"
REASON_OUTDATED_MARKER = "criterio_anterior"


def report_versioning(summary: Mapping[str, object] | None, *, persisted: bool) -> dict:
    """Estado de versión de un informe.

    ``persisted=False`` (informe calculado al vuelo, no guardado): nunca está
    desactualizado, porque se acaba de calcular con el código actual.

    Devuelve ``stale`` (bool), ``regenerate_recommended`` (igual que ``stale``,
    para la UI) y ``outdated`` con un item por marcador que no coincide:
    ``{marker, stored, current, reason}``. ``stored`` es ``None`` si el informe
    no lo registró.
    """
    if not persisted:
        return {"persisted": False, "stale": False, "regenerate_recommended": False, "outdated": []}
    stored_summary: Mapping[str, object] = summary or {}
    outdated: list[dict] = []
    for marker, current in REQUIRED_SUMMARY_MARKERS.items():
        stored = stored_summary.get(marker)
        if stored == current:
            continue
        outdated.append(
            {
                "marker": marker,
                "stored": stored,
                "current": current,
                "reason": REASON_MISSING_MARKER if stored in (None, "") else REASON_OUTDATED_MARKER,
            }
        )
    stale = bool(outdated)
    return {
        "persisted": True,
        "stale": stale,
        "regenerate_recommended": stale,
        "outdated": outdated,
    }
