"""Datos del declarante: una clave desmesurada no vuelve entera en el error.

Un ISIN o una partida pegados mal (decenas de miles de caracteres) se repetían
completos en «ISIN desconocido: …» / «Partida desconocida: …», un mensaje que
se pinta en pantalla. Ahora se recortan a 40 caracteres con «…»; una clave
corta se sigue mostrando entera.
"""

import pytest

from app.models import Tenant
from app.services import tax_declarant_service as svc
from tests.test_tax_declarant import ENTITY, db  # noqa: F401  (fixture)

LARGO = "US" + "9" * 100_000


@pytest.mark.parametrize(
    ("payload", "prefijo"),
    [
        ({"custody": {LARGO: "IE"}}, "Partida desconocida: "),
        ({"custody_entities": {LARGO: ENTITY}}, "Partida desconocida: "),
        ({"first_acquisition_dates": {LARGO: "2023-01-15"}}, "ISIN desconocido: "),
    ],
)
def test_clave_larga_recortada_en_el_error(db, payload, prefijo):  # noqa: F811
    with pytest.raises(ValueError) as exc:
        svc.write(db, payload)
    message = str(exc.value)
    assert message == prefijo + LARGO[:40] + "…"
    assert (db.get(Tenant, db.info["tenant_id"]).metadata_ or {}).get("tax_declarant") is None


def test_clave_corta_sigue_entera(db):  # noqa: F811
    with pytest.raises(ValueError, match=r"^ISIN desconocido: NOEXISTE$"):
        svc.write(db, {"first_acquisition_dates": {"NOEXISTE": "2023-01-15"}})
