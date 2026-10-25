"""Capa editorial, no evidencia ni puntuacion. No fuerza categorias ambiguas."""
NICO_MOAT_TYPES = {
    "real_product": "Diferenciación real de producto",
    "perceived_product": "Diferenciación percibida",
    "lower_costs": "Disminución de costes",
    "customer_lock": "Bloqueo de clientes",
    "competitor_lock": "Bloqueo de competidores",
}
# Correspondencias conceptuales, no prueba de que una empresa tenga ventaja.
# Red, distribucion, datos, ecosistema y proceso admiten varios mecanismos.
MAPPING = {
    "switching_costs": "customer_lock",
    "cost_advantage": "lower_costs",
    "scale": "lower_costs",
    "brand": "perceived_product",
    "regulation": "competitor_lock",
    "capital_barrier": "competitor_lock",
}


def classification(moat_type: str) -> dict:
    key = MAPPING.get(moat_type)
    return {
        "type": key,
        "label": NICO_MOAT_TYPES.get(key, "Sin clasificar") if key is not None else "Sin clasificar",
        "method": "NICO_MOAT_MAPPING_V1",
        "basis": "Correspondencia editorial de categoría; no modifica el score.",
    }


def classify_result(result: dict) -> dict:
    for item in result.get("moats", []) + result.get("unevaluated_moats", []):
        item["nico_classification"] = classification(item["type"])
    result["nico_mapping"] = {
        "version": "NICO_MOAT_MAPPING_V1",
        "types": NICO_MOAT_TYPES,
        "mapping": MAPPING,
        "unclassified": ["network_effects", "distribution", "data", "ecosystem", "process_advantage"],
    }
    return result
