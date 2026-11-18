"""CNMV NOD v3: cobertura del connector a 100% de lo nuevo (auditor 18-nov).

Cubre lo que v2 dejo sin ejecutar: _cnmv_redis_client (3 ramas), _get con
error no reintentable o Retry-After no numerico, CNMVNODFetch.__bool__,
cliente propio (close), fetch_latest, y todas las ramas de _parse_block
(anchor no-NIF, sin NIF, negrita no-declarante, sin verdoc, verdoc sin
dos puntos, sin fecha, fecha invalida, sin emisor ni NIF).
"""

import sys
from datetime import date
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest
from bs4 import BeautifulSoup

from app.services.connectors import cnmv_nod, cnmv_pacer

FIXTURE = (
    Path(__file__).parent / "fixtures" / "cnmv" / "nod_results_2026-11.html"
).read_text(encoding="utf-8")


def _block(html: str):
    return BeautifulSoup(html, "html.parser").select_one("li.blocks-single")


# ---- pacer «cnmv» compartido (auditoria 2026-11-18, punto 3) ----


def test_pacer_is_single_shared_instance():
    # Un solo modulo = una sola instancia: el fallback local sin Redis tambien
    # es unico para todo cnmv.es (antes NOD y PS doblaban el ritmo real).
    assert cnmv_nod._pacer is cnmv_pacer.cnmv_pacer
    assert cnmv_nod._pacer.key == "cnmv"


# ---- cnmv_pacer._cnmv_redis_client ----


def test_redis_client_none_without_url(monkeypatch):
    monkeypatch.setattr(
        "app.core.config.get_settings", lambda: Mock(redis_url="")
    )
    assert cnmv_pacer._cnmv_redis_client() is None


def test_redis_client_none_on_internal_error(monkeypatch):
    def boom():
        raise RuntimeError("settings rotos")

    monkeypatch.setattr("app.core.config.get_settings", boom)
    assert cnmv_pacer._cnmv_redis_client() is None


def test_redis_client_builds_from_url(monkeypatch):
    sentinel = object()
    fake_redis = Mock(from_url=Mock(return_value=sentinel))
    monkeypatch.setitem(sys.modules, "redis", fake_redis)
    monkeypatch.setattr(
        "app.core.config.get_settings", lambda: Mock(redis_url="redis://localhost:6379/0")
    )
    assert cnmv_pacer._cnmv_redis_client() is sentinel
    assert fake_redis.from_url.call_args[0][0] == "redis://localhost:6379/0"


# ---- _get: ramas de error ----


def test_get_500_without_retry_after_raises_without_cooldown(monkeypatch):
    cooldowns: list[float] = []
    monkeypatch.setattr(cnmv_nod, "_throttle", lambda: None)
    monkeypatch.setattr(cnmv_nod._pacer, "cool_down", lambda s: cooldowns.append(s))
    client = httpx.Client(
        transport=httpx.MockTransport(lambda req: httpx.Response(500, text="boom"))
    )
    with pytest.raises(httpx.HTTPStatusError):
        cnmv_nod._get(client, cnmv_nod.RESULTS_URL, {})
    assert cooldowns == []


def test_get_429_with_non_numeric_retry_after_cooldown_60s(monkeypatch):
    cooldowns: list[float] = []
    monkeypatch.setattr(cnmv_nod, "_throttle", lambda: None)
    monkeypatch.setattr(cnmv_nod._pacer, "cool_down", lambda s: cooldowns.append(s))
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda req: httpx.Response(429, headers={"Retry-After": "later"})
        )
    )
    with pytest.raises(httpx.HTTPStatusError):
        cnmv_nod._get(client, cnmv_nod.RESULTS_URL, {})
    # v4: parser compartido; valor ilegible = 60 s conservadores (antes: ignorado)
    assert cooldowns == [60.0]


# ---- CNMVNODFetch.__bool__ ----


def test_fetch_result_truthiness():
    assert not cnmv_nod.CNMVNODFetch()
    assert cnmv_nod.CNMVNODFetch(entries=[Mock()], fetched_pages=1)


# ---- fetch_entries con cliente propio ----


def test_fetch_entries_default_uses_public_session_and_closes_it(monkeypatch):
    monkeypatch.setattr(cnmv_nod, "_throttle", lambda: None)
    state = {"exited": 0, "urls": [], "kwargs": None}

    class FakeSession:
        def __init__(self, **kwargs):
            state["kwargs"] = kwargs

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            state["exited"] += 1

        def get(self, url):
            state["urls"].append(url)
            return httpx.Response(200, text=FIXTURE, request=httpx.Request("GET", url))

    monkeypatch.setattr(cnmv_nod, "PublicSession", FakeSession)
    fetched = cnmv_nod.fetch_entries(date(2026, 11, 17), date(2026, 11, 18))
    assert len(fetched.entries) == 2
    assert state["exited"] == 1
    assert state["kwargs"]["allowed_url"] is cnmv_nod.is_cnmv_url
    assert state["kwargs"]["extra_headers"] == {"Accept-Language": "es"}
    assert state["urls"][0].startswith(cnmv_nod.RESULTS_URL + "?fechad=17%2F11%2F2026")


def test_fetch_latest_delegates_with_window(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        cnmv_nod,
        "fetch_entries",
        lambda start, end: seen.update(start=start, end=end) or cnmv_nod.CNMVNODFetch(),
    )
    cnmv_nod.fetch_latest(days=3)
    assert (seen["end"] - seen["start"]).days == 3
    assert seen["end"] == date.today()


# ---- _parse_block: todas las ramas ----

_BLOCK_ANCHOR_NO_NIF_FIRST = """
<li class="blocks-single"><ul>
<li class="fecha-no-icon">17/11/2026</li>
<li><a href="/portal/otra">Enlace previo sin NIF</a></li>
<li><a href="datosentidad.aspx?nif=A47412333"><span class="tit-small">EBRO FOODS, S.A.</span></a></li>
<li><span class="negrita">Emisor: otra etiqueta</span></li>
<li><a href="https://www.cnmv.es/webservices/verdocumento/ver?e=ABC">Ver documento</a></li>
<li>Número de registro: 2026145125</li>
</ul></li>
"""


def test_block_anchor_without_nif_first_and_verdoc_without_colon():
    entry = cnmv_nod._parse_block(_block(_BLOCK_ANCHOR_NO_NIF_FIRST))
    assert entry.nif == "A47412333"
    assert entry.issuer_name == "EBRO FOODS, S.A."
    assert entry.declarant is None  # negrita sin prefijo "Declarante:"
    assert entry.motive is None  # enlace verdocumento sin ":" en la etiqueta
    assert entry.document_url == "https://www.cnmv.es/webservices/verdocumento/ver?e=ABC"
    assert entry.registry_number == "2026145125"


_BLOCK_RELATIVE_VERDOC = """
<li class="blocks-single"><ul>
<li class="fecha-no-icon">17/11/2026</li>
<li><a href="datosentidad.aspx?nif=A47412333">EBRO FOODS, S.A.</a></li>
<li><span class="negrita">Declarante: TITULAR, S.A.</span></li>
<li><a href="/webservices/verdocumento/ver?e=XYZ">Motivo de la notificación: PDMR</a></li>
<li>Número de registro: 2026145125</li>
</ul></li>
"""


def test_block_anchor_text_fallback_and_relative_verdoc_url():
    entry = cnmv_nod._parse_block(_block(_BLOCK_RELATIVE_VERDOC))
    # sin span.tit-small: el nombre cae al texto del anchor
    assert entry.issuer_name == "EBRO FOODS, S.A."
    assert entry.declarant == "TITULAR, S.A."
    assert entry.motive == "PDMR"
    assert entry.document_url == "https://www.cnmv.es/webservices/verdocumento/ver?e=XYZ"


_BLOCK_NO_NIF_NO_DECLARANT_NO_VERDOC = """
<li class="blocks-single"><ul>
<li class="fecha-no-icon">17/11/2026</li>
<li><a href="/portal/otra">Sin NIF</a></li>
<li>Número de registro: 2026145125</li>
</ul></li>
"""


def test_block_without_nif_or_issuer_raises():
    with pytest.raises(cnmv_nod.CNMVNODParseError, match="sin emisor ni NIF"):
        cnmv_nod._parse_block(_block(_BLOCK_NO_NIF_NO_DECLARANT_NO_VERDOC))


_BLOCK_NO_DATE = """
<li class="blocks-single"><ul>
<li>Número de registro: 2026145125</li>
</ul></li>
"""


def test_block_without_date_raises():
    with pytest.raises(cnmv_nod.CNMVNODParseError, match="sin fecha"):
        cnmv_nod._parse_block(_block(_BLOCK_NO_DATE))


def test_block_with_unparseable_date_raises():
    broken = FIXTURE.replace(
        '<li id="ctl00_ContentPrincipal_wucRegistros_repListaPrincipal_ctl01_liFechaRegistro" class="fecha-no-icon">\n                        17/11/2026',
        '<li class="fecha-no-icon">fecha ilegible',
    )
    with pytest.raises(cnmv_nod.CNMVNODParseError, match="fecha NOD no reconocida"):
        cnmv_nod._parse_page(broken)


def test_parse_date_direct_invalid():
    with pytest.raises(cnmv_nod.CNMVNODParseError):
        cnmv_nod._parse_date("2026-11-17")  # formato ISO: no es el formato CNMV
