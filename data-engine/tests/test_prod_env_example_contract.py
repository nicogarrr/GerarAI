"""Contrato de la plantilla de producción con docker-compose.prod.yml.

Cada variable que el compose de producción exige con `${VAR:?...}` tiene que
estar en `.env.production.example`: si falta, quien copia la plantilla tal
cual se encuentra el compose sin arrancar y sin saber qué poner.
"""

import re
from pathlib import Path

ROOT = Path(__file__).parents[2]
COMPOSE = ROOT / "docker-compose.prod.yml"
EXAMPLE = ROOT / ".env.production.example"


def _required_in_compose() -> set[str]:
    return set(re.findall(r"\$\{([A-Z][A-Z0-9_]*):\?", COMPOSE.read_text(encoding="utf-8")))


def _declared_in_example() -> set[str]:
    text = EXAMPLE.read_text(encoding="utf-8")
    return set(re.findall(r"^#?\s*([A-Z][A-Z0-9_]*)=", text, re.MULTILINE))


def test_compose_prod_tiene_variables_obligatorias():
    # Si esto falla, el patrón ha dejado de reconocer el compose y el test
    # de abajo no comprobaría nada.
    assert "REDIS_PASSWORD" in _required_in_compose()


def test_plantilla_declara_todas_las_obligatorias_del_compose():
    missing = sorted(_required_in_compose() - _declared_in_example())
    assert not missing, f"Faltan en .env.production.example: {missing}"


def test_redis_password_de_la_plantilla_no_trae_un_valor_inventado():
    # Vacía a propósito: el compose se para con su mensaje («Define
    # REDIS_PASSWORD en .env.production») en vez de arrancar con una clave
    # de ejemplo conocida.
    text = EXAMPLE.read_text(encoding="utf-8")
    assert re.search(r"^REDIS_PASSWORD=$", text, re.MULTILINE)
