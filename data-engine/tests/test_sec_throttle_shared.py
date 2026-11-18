"""El rate-limit de la SEC es UN estado de proceso, no uno por conector.

data.sec.gov limita a 10 req/s por IP. ``form4`` y ``form13f`` tenian cada uno
su propio ``threading.Lock()`` + ``_last_request_at``: un fetch 13F y un Form 4
seguidos creian ambos que habia pasado su intervalo y disparaban a la vez. El
403 de la SEC llegaba a los dos y el docstring de ``form13f`` ("mismo contrato
que form4") promesia justo lo que la duplicacion rompia en silencio.

El estado compartido vive en ``connectors/base.py``; estos tests fijan el
contrato. Cero red: el cliente HTTP es un stub que solo registra el instante de
la llamada.
"""

from __future__ import annotations

import threading
import time

import pytest

from app.services.connectors import base
from app.services.connectors import form4 as form4_connector
from app.services.connectors import form13f as form13f_connector

# 10 req/s => 0.1 s entre llamadas. El margen absorbe la holgura del sleep,
# no el reloj: las mediciones van con perf_counter (~100 ns) porque monotonic
# en Windows es GetTickCount64 y solo resuelve a ~15.6 ms.
MIN_INTERVAL = 0.1
TOLERANCE = 0.01

EMPTY_SUBMISSIONS = {"filings": {"recent": {"accessionNumber": [], "form": []}}}


class _StubResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class _StubClient:
    """Cliente httpx minimo que solo memoriza WHEN se pidio cada URL."""

    def __init__(self, payload: dict) -> None:
        self._payload = payload
        self.at: list[float] = []
        self.urls: list[str] = []

    def get(self, url: str, headers: dict | None = None) -> _StubResponse:
        self.urls.append(url)
        self.at.append(time.perf_counter())
        return _StubResponse(self._payload)


@pytest.fixture(autouse=True)
def _clean_sec_clock():
    """Estado global: reloj limpio antes y despues de cada test."""
    base.reset_sec_rate_limiter()
    yield
    base.reset_sec_rate_limiter()


def test_interval_is_ten_requests_per_second_and_never_looser():
    assert MIN_INTERVAL == 0.1
    assert base.SEC_MIN_INTERVAL_SECONDS == MIN_INTERVAL
    # Ningun modulo queda mas laxo que el limite de la SEC.
    assert form4_connector.MIN_INTERVAL_SECONDS == MIN_INTERVAL
    assert form13f_connector.MIN_INTERVAL_SECONDS == MIN_INTERVAL


def test_both_modules_expose_the_same_shared_throttle():
    """Un solo objeto throttle: identidad, no solo comportamiento parecida."""
    assert form4_connector._throttle is base.sec_throttle
    assert form13f_connector._throttle is base.sec_throttle


def test_submissions_url_has_a_single_definition():
    assert form13f_connector.SUBMISSIONS_URL is form4_connector.SUBMISSIONS_URL
    assert (
        form13f_connector.SUBMISSIONS_URL == "https://data.sec.gov/submissions/CIK{cik}.json"
    )


def _fetch_form4(stub: _StubClient) -> None:
    form4_connector.recent_form4_filings(320193, limit=1, client=stub)


def _fetch_13f(stub: _StubClient) -> None:
    form13f_connector.recent_13f_filings(1067983, limit=1, client=stub)


@pytest.mark.parametrize(
    ("first", "second"),
    [(_fetch_form4, _fetch_13f), (_fetch_13f, _fetch_form4)],
    ids=["form4-then-13f", "13f-then-form4"],
)
def test_two_back_to_back_calls_one_per_module_respect_the_global_interval(first, second):
    """El caso de produccion: dos conectores distintos, seguidos, un solo reloj.

    Con estado por modulo el segundo fetch no espera nada (cree que su ultima
    llamada fue hace un instante) y ambas peticiones salen juntas.
    """
    stub = _StubClient(EMPTY_SUBMISSIONS)

    first(stub)
    second(stub)

    assert len(stub.at) == 2
    gap = stub.at[1] - stub.at[0]
    assert gap >= MIN_INTERVAL - TOLERANCE, f"gap={gap:.4f}s (minimo {MIN_INTERVAL}s)"


def test_alternating_modules_hold_the_spacing_over_four_calls():
    """El reloj no se reinicia por cambiar de modulo en mitad de la rafaga."""
    stub = _StubClient(EMPTY_SUBMISSIONS)

    for _ in range(2):
        _fetch_form4(stub)
        _fetch_13f(stub)

    gaps = [b - a for a, b in zip(stub.at, stub.at[1:])]
    assert len(gaps) == 3
    assert all(gap >= MIN_INTERVAL - TOLERANCE for gap in gaps), gaps


class _StampLock:
    """Lock real que anota el instante de CADA concesion del throttle.

    La marca se toma dentro del ``with`` (antes de soltar el cerrojo), asi mide
    cuando concedio el limitador y no cuando el planificador desperto al hilo
    que llamo al stub: esa latencia (decenas de ms bajo carga) hacia fallar el
    test con huecos de 0,005 s que el throttle nunca concedio.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.grants: list[float] = []

    def __enter__(self):
        self._lock.acquire()
        return self

    def __exit__(self, *exc) -> None:
        self.grants.append(time.perf_counter())
        self._lock.release()


def test_two_threads_from_different_modules_are_serialized(monkeypatch):
    """El lock es compartido, no por modulo: 4 llamadas = 3 huecos, en total."""
    stub = _StubClient(EMPTY_SUBMISSIONS)
    stamp = _StampLock()
    monkeypatch.setattr(base._sec_rate_limiter, "_lock", stamp)

    def worker(module: str) -> None:
        # El lock del throttle vive dentro de base, no en el modulo: si cada
        # modulo tuviera el suyo, los dos hilos saldrian a la vez.
        if module == "form4":
            _fetch_form4(stub)
        else:
            _fetch_13f(stub)

    threads = [
        threading.Thread(target=worker, args=(name,))
        for name in ("form4", "13f", "form4", "13f")
    ]
    started = time.perf_counter()
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    # 4 llamadas a 10 req/s no pueden completarse en menos de 3 intervalos.
    assert time.perf_counter() - started >= 3 * MIN_INTERVAL - TOLERANCE
    assert len(stub.at) == 4
    # Una concesion por llamada, todas por el limitador compartido de base.
    assert len(stamp.grants) == 4, stamp.grants
    gaps = [b - a for a, b in zip(stamp.grants, stamp.grants[1:])]
    assert all(gap >= MIN_INTERVAL - TOLERANCE for gap in gaps), gaps
