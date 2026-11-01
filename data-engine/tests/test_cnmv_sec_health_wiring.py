"""Pruebas del cableado CNMV y SEC EDGAR al registry de salud de fuentes.

Fulfills: VAL-DATA-004
Expected Behavior:
- CNMV (HTML scrapeado sin API): un cambio de estructura (CNMVParseError), un
  error HTTP o de red mueven el circuito; éxito lo cierra
- SEC EDGAR: 429/401/403/5xx/red degradan; 400/404 son dato por ticker y NO
  degradan (mismo criterio que Yahoo); éxito cierra
"""

from __future__ import annotations

from unittest.mock import MagicMock

import httpx
import pytest

from app.services.connectors import edgartools_client
from app.services.connectors.cnmv import fetch_oir_filings
from app.services.data_source_health import get_data_source_registry


@pytest.fixture(autouse=True)
def registry_limpio():
    registry = get_data_source_registry()
    snapshot = {key: (s.consecutive_failures, s.state) for key, s in registry.sources.items()}
    yield registry
    for key, (failures, state) in snapshot.items():
        registry.sources[key].consecutive_failures = failures
        registry.sources[key].state = state


def test_registry_incluye_sec_y_cnmv(registry_limpio):
    registry = registry_limpio
    assert registry.get_status("sec_edgar").name == "SEC EDGAR"
    assert registry.get_status("cnmv").name == "CNMV"


@pytest.mark.anyio
async def test_cnmv_cambio_de_html_degrada(registry_limpio):
    """El caso exacto de la auditoría: la CNMV cambia su página y el parser
    levanta CNMVParseError; eso debe mover el circuito."""
    registry = registry_limpio
    status = registry.get_status("cnmv")
    before = status.consecutive_failures

    client = MagicMock(spec=httpx.AsyncClient)
    response = MagicMock()
    response.status_code = 200
    response.raise_for_status = lambda: None
    response.text = "<html><body>Totalmente rediseñado</body></html>"

    async def fake_get(url, params=None):
        return response

    client.get = fake_get
    from app.services.connectors.cnmv import CNMVParseError

    with pytest.raises(CNMVParseError):
        await fetch_oir_filings(days=1, client=client)
    assert status.consecutive_failures == before + 1


@pytest.mark.anyio
async def test_cnmv_exito_recierra(registry_limpio):
    registry = registry_limpio
    status = registry.get_status("cnmv")
    status.record_failure("fallo previo")

    client = MagicMock(spec=httpx.AsyncClient)
    response = MagicMock()
    response.status_code = 200
    response.raise_for_status = lambda: None
    response.text = (
        '<html><body><ul><li class="blocks-single">'
        '<ul><li class="fecha-con-hora">30/10/2026</li><li class="time">18:00</li></ul>'
        '<a href="datosentidad.aspx?nif=A28000000">ENTIDAD SA</a>'
        '<a href="verdocumento/123">Hecho relevante</a>'
        '<span class="negrita">OIR</span>'
        "Número de registro: 12345"
        "</li></ul></body></html>"
    )

    async def fake_get(url, params=None):
        return response

    client.get = fake_get
    filings = await fetch_oir_filings(days=1, client=client)
    assert len(filings) == 1
    assert status.consecutive_failures == 0


def test_sec_429_y_bloqueo_ip_degradan(registry_limpio):
    registry = registry_limpio
    status = registry.get_status("sec_edgar")
    before = status.consecutive_failures

    assert edgartools_client.report_sec_failure_to_health(429) is True
    assert edgartools_client.report_sec_failure_to_health(403) is True
    assert edgartools_client.report_sec_failure_to_health(None) is True
    assert status.consecutive_failures == before + 3


def test_sec_404_es_dato_por_ticker_no_degrada(registry_limpio):
    registry = registry_limpio
    status = registry.get_status("sec_edgar")
    before = status.consecutive_failures

    assert edgartools_client.report_sec_failure_to_health(404) is False
    assert edgartools_client.report_sec_failure_to_health(400) is False
    assert status.consecutive_failures == before


def test_sec_exito_recierra(registry_limpio):
    registry = registry_limpio
    status = registry.get_status("sec_edgar")
    status.record_failure("fallo previo")

    edgartools_client.report_sec_success_to_health()
    assert status.consecutive_failures == 0


EMPTY_DAY_HTML = (
    '<html><body><section id="maincontent">'
    '<article class="block-content-pdf block-content">'
    '<ul id="listaElementosPrimernivel"></ul>'
    "</article></section></body></html>"
)


def test_cnmv_dia_vacio_no_es_deriva_parse():
    """Fin de semana/festivo: la lista de resultados se renderiza vacía.
    Es un día sin hechos, NO un cambio de estructura: parse devuelve []."""
    from app.services.connectors.cnmv import parse_oir_results

    assert parse_oir_results(EMPTY_DAY_HTML) == []


def test_cnmv_estructura_rota_sin_contenedor_es_deriva_parse():
    """Sin el <ul id="listaElementosPrimernivel"> la página cambió de verdad."""
    from app.services.connectors.cnmv import CNMVParseError, parse_oir_results

    with pytest.raises(CNMVParseError):
        parse_oir_results("<html><body><div>Rediseño total</div></body></html>")


@pytest.mark.anyio
async def test_cnmv_dia_vacio_registra_exito_no_fallo(registry_limpio):
    """Bloqueo del piloto: un día vacío (finde/festivo) no puede contar como
    fallo de la fuente — sería una falsa alarma cada fin de semana."""
    registry = registry_limpio
    status = registry.get_status("cnmv")
    status.record_failure("fallo previo")
    failures_before = status.consecutive_failures

    client = MagicMock(spec=httpx.AsyncClient)
    response = MagicMock()
    response.status_code = 200
    response.raise_for_status = lambda: None
    response.text = EMPTY_DAY_HTML

    async def fake_get(url, params=None):
        return response

    client.get = fake_get

    filings = await fetch_oir_filings(days=1, client=client)
    assert filings == []
    # Éxito: recierre del circuito, no incremento de fallos.
    assert status.consecutive_failures == 0
    assert failures_before == 1
