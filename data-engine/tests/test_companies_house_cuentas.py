"""Companies House: ultimas cuentas depositadas (latest_accounts), camino a camino.

Sin red: el cliente es un doble minimo con filing_history y metadatos de
documento. Se fijan: sin cuentas depositadas -> None; sin transaction_id el
enlace publico se deriva del link self; sin metadatos (o con metadatos vacios)
la fila sale igualmente con formatos vacios; un documento sin iXBRL ni PDF no se
lee; y un iXBRL ilegible no tumba la fila (figures_error con el tipo de la
excepcion, fail closed por documento).

NO prueba (declarado): la API real, el contenido real de los documentos, ni la
cache de cuentas escaneadas (attach_scanned_figures va doblada con un spy en el
test del formato no legible -un CSV-, que demuestra que NO se llama cuando el
documento no es un PDF).
"""

from __future__ import annotations

import asyncio

from app.services import companies_house_evidence as ev
from app.services.connectors import companies_house as ch

_MIEMBRO = ev.GroupMember("00000001", "Acme Holdings Ltd", 0, "nombre exacto del holding")


class _DobleCuentas:
    """Cliente minimo: filing_history y metadatos prefijados."""

    requests_used = 1

    def __init__(self, filings, meta=None):
        self._filings = filings
        self._meta = meta

    async def filing_history(self, number, category=None, items=10):
        return self._filings

    async def document_metadata(self, url):
        return self._meta

    async def document_content(self, meta, mime):
        raise ValueError("iXBRL ilegible")


def test_sin_cuentas_depositadas_devuelve_none():
    """Hay historial pero ninguna cuenta (solo confirmation statements): None."""
    doble = _DobleCuentas([
        {"description": "confirmation-statement-with-updates", "date": "2025-01-01"},
    ])
    assert asyncio.run(ev.latest_accounts(doble, _MIEMBRO)) is None


def test_sin_transaction_id_el_enlace_sale_del_link_self():
    """tx se deriva del ultimo tramo del link self; sin metadatos la fila sale
    con formatos vacios y sin cifras."""
    doble = _DobleCuentas([
        {"description": "accounts-with-accounts-type-full", "date": "2025-03-01",
         "links": {"self": "/company/00000001/filing-history/TXSELF"},
         "description_values": {"made_up_date": "2024-12-31"}},
    ])
    fila = asyncio.run(ev.latest_accounts(doble, _MIEMBRO))
    assert fila["accounts_type"] == "full"
    assert fila["document_url"] == ch.public_document_url("00000001", "TXSELF")
    assert fila["filed_on"] == "2025-03-01"
    assert fila["made_up_to"] == "2024-12-31"
    assert fila["formats"] == []
    assert fila["pages"] is None
    assert fila["figures"] == []


def test_metadatos_vacios_devuelven_fila_sin_formatos():
    """La API responde pero sin cuerpo: la fila conserva enlace y fecha, sin
    formatos ni cifras."""
    doble = _DobleCuentas([
        {"description": "accounts-with-accounts-type-group", "date": "2025-03-01",
         "transaction_id": "TX1",
         "links": {"document_metadata": "https://document-api/meta/TX1"}},
    ], meta={})
    fila = asyncio.run(ev.latest_accounts(doble, _MIEMBRO))
    assert fila["accounts_type"] == "group"
    assert fila["document_url"] == ch.public_document_url("00000001", "TX1")
    assert fila["formats"] == []
    assert fila["pages"] is None
    assert fila["figures"] == []
    assert "ixbrl_url" not in fila


def test_documento_sin_ixbrl_ni_pdf_no_se_lee(monkeypatch):
    """Solo hay un formato que no se sabe leer: se citan los formatos y NO se
    llama a la lectura de escaneadas (spy que nunca salta)."""
    llamadas = []

    def _espia_attach(fila):
        llamadas.append(fila)

    monkeypatch.setattr(ev, "attach_scanned_figures", _espia_attach)
    doble = _DobleCuentas([
        {"description": "accounts-with-accounts-type-full", "date": "2025-03-01",
         "transaction_id": "TX2",
         "links": {"document_metadata": "https://document-api/meta/TX2"}},
    ], meta={"resources": {"text/csv": {}}, "pages": 3})
    fila = asyncio.run(ev.latest_accounts(doble, _MIEMBRO))
    assert fila["formats"] == ["text/csv"]
    assert fila["pages"] == 3
    assert fila["figures"] == []
    assert "ixbrl_url" not in fila
    assert llamadas == []


def test_ixbrl_ilegible_no_tumba_la_fila():
    """El documento iXBRL no se puede leer: figures_error con el tipo de la
    excepcion y la fila se conserva con su enlace xhtml (fail closed)."""
    doble = _DobleCuentas([
        {"description": "accounts-with-accounts-type-full", "date": "2025-03-01",
         "transaction_id": "TX3",
         "links": {"document_metadata": "https://document-api/meta/TX3"}},
    ], meta={"resources": {ch.IXBRL_MIME: {}}, "pages": 12})
    fila = asyncio.run(ev.latest_accounts(doble, _MIEMBRO))
    assert fila["figures_error"] == "ValueError"
    assert fila["figures"] == []
    assert fila["ixbrl_url"] == ch.public_document_url("00000001", "TX3", fmt="xhtml")
    assert fila["pages"] == 12
