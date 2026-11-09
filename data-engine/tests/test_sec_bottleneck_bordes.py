"""sec_bottleneck_filings (bordes): frase larga descartada entera, guardas
429 y JSON no objeto de EFTS/Archives, clientes propios creados y cerrados
cuando no se inyectan, _existing_urls vacío, freno al llegar a
MAX_DOCS_PER_THEME y documento ilegible que no frena al resto.

Sin red: clientes AsyncClient falsos (AsyncMock o clase doble con
__aenter__/__aexit__). SQLite real para la ingesta. Respuestas grabadas
sintéticas.
"""

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models import Document, Tenant
from app.services import sec_bottleneck_filings as sb

THEME = "Semiconductores"
PASSAGE_OK = "ACME CHIPS INC reported that chip shortages persist across its supplier network."
FILING_HTML = f"<html><body><p>{PASSAGE_OK}</p><p>Revenue grew.</p></body></html>"


class FakeResponse:
    def __init__(self, payload=None, text="", status_code=200):
        self._payload = payload
        self.text = text
        self.status_code = status_code
        self.headers = {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        return None


def _hit(n: int, day: str = "2026-10-15") -> dict:
    accession = f"0000950170-25-00000{n}"
    return {
        "_id": f"{accession}:d{n}k.htm",
        "_source": {
            "adsh": accession,
            "form": "8-K",
            "file_date": day,
            "display_names": [f"EMPRESA {n}"],
            "ciks": ["0001234567"],
        },
    }


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Tenant(id=1, external_id="a"))
        session.commit()
        session.info["tenant_id"] = 1
        yield session
    engine.dispose()


# --- matching_passages ------------------------------------------------------


def test_matching_passages_frase_larga_se_descarta_entera():
    larga = "Chip shortages persist " + "across every supplier network " * 25 + "today"
    assert len(larga) > 700
    out = sb.matching_passages(f"{larga}. {PASSAGE_OK}", THEME)
    assert out == [PASSAGE_OK]


# --- guardas HTTP de _get_json / _get_text ----------------------------------


def test_get_json_429_no_reintenta():
    client = AsyncMock()
    client.get.return_value = FakeResponse(status_code=429)
    with pytest.raises(RuntimeError) as excinfo:
        asyncio.run(sb._get_json("https://efts.sec.gov/x", {"q": "x"}, client))
    assert str(excinfo.value) == "SEC EFTS rate-limited (429): no se reintenta en la misma corrida"


def test_get_json_no_objeto():
    client = AsyncMock()
    client.get.return_value = FakeResponse(payload=[1, 2, 3])
    with pytest.raises(RuntimeError) as excinfo:
        asyncio.run(sb._get_json("https://efts.sec.gov/x", {"q": "x"}, client))
    assert str(excinfo.value) == "SEC EFTS devolvio un JSON no objeto"


def test_get_text_429_no_reintenta():
    client = AsyncMock()
    client.get.return_value = FakeResponse(status_code=429)
    with pytest.raises(RuntimeError) as excinfo:
        asyncio.run(sb._get_text("https://www.sec.gov/Archives/x", client))
    assert str(excinfo.value) == "SEC Archives rate-limited (429): no se reintenta en la misma corrida"


def test_get_json_sin_cliente_crea_y_cierra_propio(monkeypatch):
    creados = []

    class FakeOwned:
        def __init__(self, **kwargs):
            self.closed = False
            creados.append(self)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            self.closed = True

        async def get(self, url, params=None):
            return FakeResponse(payload={"ok": True})

    monkeypatch.setattr(sb.httpx, "AsyncClient", FakeOwned)
    data = asyncio.run(sb._get_json("https://efts.sec.gov/x", {"q": "x"}, None))
    assert data == {"ok": True}
    assert len(creados) == 1
    assert creados[0].closed is True


def test_get_text_sin_cliente_crea_y_cierra_propio(monkeypatch):
    creados = []

    class FakeOwned:
        def __init__(self, **kwargs):
            self.closed = False
            creados.append(self)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            self.closed = True

        async def get(self, url):
            return FakeResponse(text="cuerpo del filing")

    monkeypatch.setattr(sb.httpx, "AsyncClient", FakeOwned)
    assert asyncio.run(sb._get_text("https://www.sec.gov/Archives/x", None)) == "cuerpo del filing"
    assert len(creados) == 1
    assert creados[0].closed is True


# --- _existing_urls ----------------------------------------------------------


def test_existing_urls_sin_urls_devuelve_vacio(db):
    assert sb._existing_urls(db, 1, []) == set()


# --- ingest_theme: freno al tope y documento ilegible ------------------------


async def _no_sleep(*args, **kwargs):
    return None


def test_ingest_theme_frena_al_llegar_al_tope(db, monkeypatch):
    monkeypatch.setattr(asyncio, "sleep", _no_sleep)
    hits = [_hit(n) for n in range(1, 7)]
    payload = {"hits": {"total": {"value": 6}, "hits": hits}}
    buscadas = []

    class Client:
        def __init__(self):
            self.get = AsyncMock(side_effect=self._get)

        async def _get(self, url, params=None, headers=None):
            if "search-index" in url:
                return FakeResponse(payload=payload)
            buscadas.append(url)
            return FakeResponse(text=FILING_HTML)

    # El sexto hit existe ya: la ventana amplía el corte, pero el freno por
    # MAX_DOCS_PER_THEME salta antes de buscar el sexto documento nuevo.
    ultimo = hits[-1]
    url_existente = sb._hit_document_url(
        str(ultimo["_source"]["ciks"][0]), ultimo["_source"]["adsh"], "d6k.htm"
    )
    db.add(Document(title="viejo", source_type="sec_filing", source_url=url_existente))
    db.commit()

    result = asyncio.run(
        sb.ingest_theme(db, 1, THEME, since=datetime(2026, 10, 1, tzinfo=UTC), client=Client())
    )
    assert result == {"hits": 6, "skipped_existing": 0, "documents": 5, "passages": 5}
    assert len(buscadas) == 5


def test_ingest_theme_documento_ilegible_no_frena_al_resto(db, monkeypatch):
    monkeypatch.setattr(asyncio, "sleep", _no_sleep)
    payload = {"hits": {"total": {"value": 2}, "hits": [_hit(1), _hit(2)]}}
    primeras = {"d1k.htm"}

    class Client:
        def __init__(self):
            self.get = AsyncMock(side_effect=self._get)

        async def _get(self, url, params=None, headers=None):
            if "search-index" in url:
                return FakeResponse(payload=payload)
            if any(marker in url for marker in primeras):
                raise OSError("conexion rota")
            return FakeResponse(text=FILING_HTML)

    result = asyncio.run(
        sb.ingest_theme(db, 1, THEME, since=datetime(2026, 10, 1, tzinfo=UTC), client=Client())
    )
    assert result == {"hits": 2, "skipped_existing": 0, "documents": 1, "passages": 1}
