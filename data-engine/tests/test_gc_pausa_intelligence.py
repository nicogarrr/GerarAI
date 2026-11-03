"""GC ciclico en pausa durante /portfolio/intelligence y risk-matrix (misma respuesta)."""

import gc
import threading

import pytest

from app.core import gc_pause
from app.core.gc_pause import gc_paused


@pytest.fixture(autouse=True)
def _gc_on():
    gc.enable()
    yield
    gc.enable()


def test_pausa_y_reactiva():
    with gc_paused():
        assert not gc.isenabled()
    assert gc.isenabled()


def test_reactiva_tras_excepcion():
    with pytest.raises(RuntimeError), gc_paused():
        raise RuntimeError("x")
    assert gc.isenabled()


def test_si_estaba_apagado_sigue_apagado():
    gc.disable()
    with gc_paused():
        pass
    assert not gc.isenabled()


def test_solapados_solo_reactiva_el_ultimo():
    entered = threading.Event()
    release = threading.Event()

    def other():
        with gc_paused():
            entered.set()
            release.wait(5)

    t = threading.Thread(target=other)
    t.start()
    entered.wait(5)
    with gc_paused():
        assert not gc.isenabled()
    assert not gc.isenabled()  # el otro calculo sigue en curso
    release.set()
    t.join(5)
    assert gc.isenabled()
    assert gc_pause._holders == 0


@pytest.mark.parametrize(
    ("path", "target"),
    [
        (
            "/api/portfolio/intelligence",
            "app.services.portfolio_intelligence_service.PortfolioIntelligenceService.build",
        ),
        (
            "/api/portfolio/risk-matrix",
            "app.services.portfolio_risk_matrix_service.PortfolioRiskMatrixService.build",
        ),
    ],
)
def test_las_rutas_calculan_con_el_gc_en_pausa(monkeypatch, path, target):
    from tests.auth_helpers import signed_request
    from tests.test_portfolio_risk_matrix_route import SECRET, _client

    client, tenant, user = _client(monkeypatch)
    seen = []
    module_path, cls_name, meth = target.rsplit(".", 2)
    module = __import__(module_path, fromlist=[cls_name])
    cls = getattr(module, cls_name)
    original = getattr(cls, meth)

    def spy(self, *args, **kwargs):
        seen.append(gc.isenabled())
        return original(self, *args, **kwargs)

    monkeypatch.setattr(cls, meth, spy)
    response = signed_request(client, SECRET, tenant, user, "GET", path)
    assert response.status_code == 200
    assert seen == [False]
    assert gc.isenabled()
