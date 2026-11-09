"""Companies House: cuentas escaneadas (OCR), encolado y cache del uso sincrono.

Sin red y sin broker: el actor dramatiq es un modulo falso en sys.modules y la
cache OCR (scanned_accounts) va doblada. Se fijan: attach con y sin cache OCR
(con figuras mapeadas a etiquetas y pagina, y las sin valor descartadas), el
encolado que cuenta envios y no tumba si el broker falla, la re-lectura de las
pendientes en un cache hit, None cuando no hay cliente configurado, y el cierre
del cliente propio con cacheo del resultado.

NO prueba (declarado): la API real, el broker real, la base de datos del cache
OCR (load_cached/claim_pending doblados), ni el contenido de los PDF.
"""

from __future__ import annotations

import sys
import time
import types

from app.services import companies_house_evidence as ev
from app.services import scanned_accounts


def _fila_pendiente(number="00000001", via="nombre exacto del holding"):
    return {"company_number": number, "company_name": "Acme Holdings Ltd",
            "via": via, "document_url": "https://doc.example/TX1",
            "made_up_to": "2024-12-31", "accounts_type": "full",
            "scanned": {"status": "pending"}}


def test_attach_sin_cache_ocr_marca_pendiente(monkeypatch):
    monkeypatch.setattr(scanned_accounts, "load_cached", lambda n, m: None)
    fila = _fila_pendiente()
    ev.attach_scanned_figures(fila)
    assert fila["scanned"] == {"status": "pending"}
    assert "figures" not in fila


def test_attach_con_cache_ocr_mapea_figuras_y_descarta_las_sin_valor(monkeypatch):
    """La figura con valor entra con etiqueta, pagina y enlace de pagina; la
    figura sin valor se descarta; los rechazados se conservan con su motivo."""
    monkeypatch.setattr(scanned_accounts, "load_cached", lambda n, m: {
        "status": "ok", "reason": None, "checks": ["c1"], "statements": ["e1"],
        "rejected": [{"metric": "cash", "page": 6, "reason": "ilegible"}],
        "figures": [
            {"metric": "revenue", "label": "Turnover", "value": 123000000,
             "value_millions": 123.0, "currency": "GBP", "unit": "m",
             "period_end": "2024-12-31", "page": 5, "line": 12,
             "basis": "consolidado", "check": "c1"},
            {"metric": "cash", "label": "Cash", "value": None, "page": 6},
        ],
    })
    fila = _fila_pendiente()
    ev.attach_scanned_figures(fila)
    assert fila["scanned"]["status"] == "ok"
    assert fila["scanned"]["rejected"] == [
        {"metric": "cash", "page": 6, "reason": "ilegible"}]
    (figura,) = fila["figures"]
    assert figura["metric"] == "revenue"
    assert figura["label"] == "ingresos / primas"
    assert figura["value"] == 123000000
    assert figura["page"] == 5
    assert figura["source"] == "ocr"
    assert figura["page_url"] == scanned_accounts.page_url(
        "https://doc.example/TX1", 5)
    assert "pág. 5" in figura["concept"]


def _actor_falso(monkeypatch, falla=False):
    """Modulo dramatiq falso: registra los envios o los hace fallar."""
    modulo = types.ModuleType("app.workers.dramatiq_app")
    envios = []

    class _Actor:
        def send(self, *args):
            if falla:
                raise RuntimeError("sin broker")
            envios.append(args)

    modulo.extract_scanned_accounts = _Actor()
    monkeypatch.setitem(sys.modules, "app.workers.dramatiq_app", modulo)
    return envios


def test_queue_scanned_reads_encola_y_cuenta(monkeypatch):
    envios = _actor_falso(monkeypatch)
    monkeypatch.setattr(scanned_accounts, "claim_pending", lambda n, m: True)
    resultado = {"members": [_fila_pendiente()]}
    assert ev.queue_scanned_reads(resultado, "ACME") == 1
    assert envios == [("00000001", "2024-12-31", "https://doc.example/TX1",
                       "Acme Holdings Ltd", "ACME")]


def test_queue_scanned_reads_sin_broker_no_tumba_y_cuenta_cero(monkeypatch):
    """El broker caido deja la cuenta pendiente para otro intento (0 enviadas,
    sin excepcion)."""
    _actor_falso(monkeypatch, falla=True)
    monkeypatch.setattr(scanned_accounts, "claim_pending", lambda n, m: True)
    resultado = {"members": [_fila_pendiente()]}
    assert ev.queue_scanned_reads(resultado, "ACME") == 0


def test_cache_hit_relee_las_escaneadas_pendientes(monkeypatch):
    """Un resultado fresco con lecturas OCR pendientes las reintenta desde la
    cache del worker (spy), sin tocar la API; las ya leidas no se tocan."""
    pendiente = _fila_pendiente("X1")
    leida = {"company_number": "X2", "scanned": {"status": "ok"}}
    cacheado = {"status": "ok", "reason": "ok", "members": [pendiente, leida],
                "requests_used": 3, "unverified": []}
    clave = (ev.normalize_name("Cache Pendiente Ltd"), (), ())
    monkeypatch.setitem(ev._CACHE, clave, (time.monotonic(), cacheado))
    llamadas = []
    monkeypatch.setattr(ev, "attach_scanned_figures", llamadas.append)
    assert ev.collect_group_accounts("Cache Pendiente Ltd", [], client=object()) is cacheado
    assert llamadas == [pendiente]


class _DoblePropio:
    """Cliente creado desde settings: holding exacto, sin cuentas, con aclose
    contado (spy)."""

    def __init__(self):
        self.requests_used = 1
        self.llamadas_search = 0
        self.cerrado = 0

    async def search_companies(self, query, items=10):
        self.llamadas_search += 1
        return [{"company_number": "00000001", "title": query,
                 "company_status": "active"}]

    async def officers(self, number):
        return []

    async def filing_history(self, number, category=None, items=10):
        return []

    async def aclose(self):
        self.cerrado += 1


def test_collect_sin_cliente_configurado_devuelve_none(monkeypatch):
    from app.services.connectors import companies_house as ch

    monkeypatch.setattr(ch, "client_from_settings", lambda: None)
    assert ev.collect_group_accounts("Sin Cliente Holdings Ltd", []) is None


def test_collect_cierra_cliente_propio_y_cachea(monkeypatch):
    """El cliente creado por la funcion se cierra siempre; el resultado ok se
    cachea y la segunda llamada no vuelve a buscar (spy de busquedas)."""
    from app.services.connectors import companies_house as ch

    monkeypatch.setattr(ev, "_CACHE", {})  # la entrada que crea la funcion no debe fugarse
    doble = _DoblePropio()
    monkeypatch.setattr(ch, "client_from_settings", lambda: doble)
    primero = ev.collect_group_accounts("Cierre Propio Holdings Ltd", [])
    assert primero["status"] == "ok"
    assert primero["members"][0]["company_number"] == "00000001"
    assert primero["members"][0]["accounts_type"] is None  # sin cuentas: fila basica
    assert doble.cerrado == 1
    segundo = ev.collect_group_accounts("Cierre Propio Holdings Ltd", [])
    assert segundo is primero
    assert doble.llamadas_search == 1
