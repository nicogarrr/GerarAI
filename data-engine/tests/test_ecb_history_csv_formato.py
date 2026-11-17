"""Un 200 que no es el CSVdata del BCE no es salud ni «divisas no publicadas».

Antes de ``_require_csv_header``, ``fetch_ecb_csv`` y ``fetch_ecb_csv_sync``
registraban éxito con CUALQUIER 200 y ``parse_ecb_csv`` devolvía [] ante HTML
de challenge o un cambio de formato: el backfill reportaba TODAS las divisas
pedidas como ``not_published`` (indistinguible de «el BCE no publica esa
divisa») con el panel de salud en verde. Ahora la cabecera se valida ANTES de
registrar el éxito, como ya hace ``fred.series_csv``.
"""

import asyncio
from datetime import date
from decimal import Decimal
from unittest.mock import Mock

import httpx
import pytest

from app.services.connectors import ecb_history as ecb

DAY = date(2026, 11, 9)

VALID_CSV = "FREQ,CURRENCY,CURRENCY_DENOM,TIME_PERIOD,OBS_VALUE\nD,USD,EUR,2026-11-09,1.1\n"
CHALLENGE_HTML = "<html><head><title>Just a moment</title></head><body>challenge</body></html>"


def _sync_client(monkeypatch, registry, text, requests):
    monkeypatch.setattr(ecb, "get_data_source_registry", lambda: registry)
    original_client = httpx.Client

    def handler(request):
        requests.append(request)
        return httpx.Response(200, text=text)

    monkeypatch.setattr(
        ecb.httpx, "Client", lambda **kw: original_client(transport=httpx.MockTransport(handler), **kw)
    )


def _async_client(monkeypatch, registry, text):
    monkeypatch.setattr(ecb, "get_data_source_registry", lambda: registry)
    original_client = httpx.AsyncClient

    def handler(request):
        return httpx.Response(200, text=text)

    monkeypatch.setattr(
        ecb.httpx,
        "AsyncClient",
        lambda **kw: original_client(transport=httpx.MockTransport(handler), **kw),
    )


def test_sync_200_challenge_html_records_failure_and_raises(monkeypatch):
    registry = Mock()
    _sync_client(monkeypatch, registry, CHALLENGE_HTML, [])
    with pytest.raises(RuntimeError, match="CSV esperado"):
        ecb.fetch_ecb_csv_sync(["USD"], DAY, DAY)
    registry.record_failure.assert_called_once_with(
        "ecb", "respuesta no CSV (challenge o cambio de formato)"
    )
    registry.record_success.assert_not_called()


def test_async_200_challenge_html_records_failure_and_raises(monkeypatch):
    registry = Mock()
    _async_client(monkeypatch, registry, CHALLENGE_HTML)
    with pytest.raises(RuntimeError, match="CSV esperado"):
        asyncio.run(ecb.fetch_ecb_csv(["USD"], DAY, DAY))
    registry.record_failure.assert_called_once_with(
        "ecb", "respuesta no CSV (challenge o cambio de formato)"
    )
    registry.record_success.assert_not_called()


@pytest.mark.parametrize(
    "text",
    [
        # Cabecera sin la columna de fecha: no es la serie diaria.
        "CURRENCY,OBS_VALUE\nUSD,1.1\n",
        # Cabecera sin el valor: sin tasa no hay dato.
        "CURRENCY,TIME_PERIOD\nUSD,2026-11-09\n",
        # CSV vacío (proxy cortando): tampoco es la serie.
        "",
    ],
)
def test_partial_or_empty_header_is_rejected(monkeypatch, text):
    registry = Mock()
    _async_client(monkeypatch, registry, text)
    with pytest.raises(RuntimeError, match="CSV esperado"):
        asyncio.run(ecb.fetch_ecb_csv(["USD"], DAY, DAY))
    registry.record_failure.assert_called_once()
    registry.record_success.assert_not_called()


def test_valid_header_records_success_and_returns_text(monkeypatch):
    registry = Mock()
    _async_client(monkeypatch, registry, VALID_CSV)
    assert asyncio.run(ecb.fetch_ecb_csv(["USD"], DAY, DAY)) == VALID_CSV
    registry.record_success.assert_called_once()
    registry.record_failure.assert_not_called()


def test_header_with_bom_and_lowercase_and_extra_columns_is_accepted(monkeypatch):
    # BOM de UTF-8 y minúsculas no son cambio de formato: el BCE puede
    # reordenar columnas y añadir otras (FREQ, EXR_TYPE...).
    text = "\ufeffcurrency,time_period,obs_value,extra\nUSD,2026-11-09,1.1,x\n"
    registry = Mock()
    _sync_client(monkeypatch, registry, text, [])
    assert ecb.fetch_ecb_csv_sync(["USD"], DAY, DAY) == text
    registry.record_success.assert_called_once()


def test_valid_csv_without_rows_stays_not_published_not_an_outage(monkeypatch):
    # La divisa que el BCE no publica sigue siendo «sin datos» por divisa:
    # cabecera válida, cero filas -> not_published, SIN fallo de salud y sin
    # excepción. Este test fija que la validación NO convierte una ausencia
    # legítima en caída de fuente.
    registry = Mock()
    _async_client(monkeypatch, registry, "CURRENCY,TIME_PERIOD,OBS_VALUE\n")
    db = Mock()

    async def run():
        # fetch real (validado) como fetcher del backfill.
        return await ecb.backfill_ecb_rates(db, currencies={"XXX"}, start=DAY, end=DAY)

    result = asyncio.run(run())
    assert result["not_published"] == ["XXX"]
    assert result["written"] == {}
    registry.record_success.assert_called_once()
    registry.record_failure.assert_not_called()
    db.commit.assert_called_once()


def test_outage_masquerading_as_unpublished_is_now_visible(monkeypatch):
    # Repro del bug: con HTML de challenge el backfill ANTES devolvía
    # not_published=["USD"] y salud verde; ahora propaga RuntimeError y el
    # registry registra el fallo. Sin ``_require_csv_header`` este test falla.
    registry = Mock()
    _async_client(monkeypatch, registry, CHALLENGE_HTML)
    db = Mock()
    with pytest.raises(RuntimeError, match="CSV esperado"):
        asyncio.run(ecb.backfill_ecb_rates(db, currencies={"USD"}, start=DAY, end=DAY))
    registry.record_failure.assert_called_once()
    registry.record_success.assert_not_called()
    db.commit.assert_not_called()


def test_real_shape_csv_parses_after_validation(monkeypatch):
    # Forma real del csvdata del BCE (cabecera larga, columnas reordenadas).
    registry = Mock()
    _async_client(monkeypatch, registry, VALID_CSV)
    text = asyncio.run(ecb.fetch_ecb_csv(["USD"], DAY, DAY))
    assert ecb.parse_ecb_csv(text) == [(DAY, "USD", Decimal("1.1"))]
