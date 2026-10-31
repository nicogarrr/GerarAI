"""Guardian de la migracion B314: todo conector que parsea XML externo lo hace
via defusedxml (entidades/DOCTYPE con entidades rechazadas sin expandir).

Si un conector vuelve a parsear con xml.etree stdlib, el bomb XML deja de
lanzar EntitiesForbidden y este test lo detecta. Los feeds legitimos de cada
fuente siguen cubiertos por los tests de cada conector (fixtures reales).
"""

from __future__ import annotations

import defusedxml.ElementTree as defused_et
import pytest
from defusedxml.common import EntitiesForbidden

BOMB = (
    '<?xml version="1.0"?>'
    '<!DOCTYPE r [<!ENTITY a "xxxxxxxxxx"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">]>'
    "<r>&b;&b;&b;&b;</r>"
)


def _module_parser(module):
    parser = getattr(module, "DefusedElementTree", None) or getattr(module, "DefusedET", None)
    assert parser is defused_et, f"{module.__name__} no parsea con defusedxml"
    return parser


def test_connectors_parse_with_defusedxml_and_reject_entities():
    from app.services import ibkr_connection_service, investor_videos
    from app.services.connectors import ecb, form4, form13dg, form13f, ibkr, rss, sec_xbrl_instance

    for module in (ecb, form4, form13dg, form13f, ibkr, rss, sec_xbrl_instance,
                   ibkr_connection_service, investor_videos):
        parser = _module_parser(module)
        with pytest.raises(EntitiesForbidden):
            parser.fromstring(BOMB)
