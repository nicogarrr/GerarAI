"""Limites operativos de la tuberia primaria: sin red ni VM, hijos reales y runner inyectado."""
import sys
from datetime import date

import pytest

from app.services import commitment_primary_pipeline as pp
from tests.test_commitment_primary_pipeline import PAGES, TODAY, URL

OK = {
    "bytes_sha256": "a" * 64, "byte_size": 10, "content_type": "application/pdf",
    "final_url": URL, "pages": PAGES,
}


@pytest.fixture(autouse=True)
def _clean():
    pp._CACHE.clear()
    pp._SEEN_BYTES.clear()
    yield
    pp._CACHE.clear()
    pp._SEEN_BYTES.clear()


def test_child_deadline_kills_process():
    with pytest.raises(pp.PrimarySourceError, match="Tiempo total"):
        pp.run_child([sys.executable, "-c", "import time; time.sleep(30)"], deadline=0.5)


def test_child_memory_and_cpu_limits_fail_closed():
    code_mem = "import resource;resource.setrlimit(resource.RLIMIT_AS,(200_000_000,)*2);x=bytearray(900_000_000)"
    with pytest.raises(pp.PrimarySourceError):
        pp.run_child([sys.executable, "-c", code_mem], deadline=20)
    code_cpu = "import resource;resource.setrlimit(resource.RLIMIT_CPU,(1,1))\nwhile True: pass"
    with pytest.raises(pp.PrimarySourceError):
        pp.run_child([sys.executable, "-c", code_cpu], deadline=20)


def test_child_output_is_bounded_and_must_be_json_object():
    with pytest.raises(pp.PrimarySourceError):
        pp.run_child([sys.executable, "-c", "print('[1,2]')"], deadline=10)
    with pytest.raises(pp.PrimarySourceError):
        pp.run_child([sys.executable, "-c", "print('x'*(4*1_500_000+10))"], deadline=10)


def test_dedup_by_url_and_bytes_change_is_only_process_scoped():
    calls = []

    def runner(argv, deadline):
        calls.append(argv)
        return dict(OK)

    d1, m1 = pp.fetch_registered_document_isolated("UBER", URL, today=TODAY, runner=runner)
    d2, m2 = pp.fetch_registered_document_isolated("UBER", URL, today=TODAY, runner=runner)
    assert len(calls) == 1 and d1 is d2
    assert m1 == {"cache_hit": False, "previous_bytes_sha256": None, "bytes_changed": None}
    assert m2["cache_hit"] is True
    pp._CACHE.clear()
    changed = dict(OK, bytes_sha256="b" * 64)
    _, m3 = pp.fetch_registered_document_isolated(
        "UBER", URL, today=TODAY, runner=lambda argv, deadline: changed)
    assert m3["bytes_changed"] is True and m3["previous_bytes_sha256"] == "a" * 64


def test_concurrency_is_bounded():
    acquired = [pp._SLOTS.acquire(blocking=False) for _ in range(pp.MAX_CONCURRENT)]
    try:
        with pytest.raises(pp.PrimarySourceError, match="Demasiadas"):
            pp.fetch_registered_document_isolated(
                "UBER", URL, today=TODAY, runner=lambda argv, deadline: dict(OK))
    finally:
        for ok in acquired:
            if ok:
                pp._SLOTS.release()


@pytest.mark.parametrize("bad", [
    {"error": "No se pudo descargar la fuente oficial"},
    dict(OK, final_url="https://evil.example/x.pdf"),
    dict(OK, content_type="text/html"),
    dict(OK, pages=["corto"]),
    dict(OK, pages="no-lista"),
    dict(OK, bytes_sha256="zz"),
])
def test_inconsistent_child_response_is_rejected(bad):
    with pytest.raises(pp.PrimarySourceError):
        pp.fetch_registered_document_isolated(
            "UBER", URL, today=date(2026, 10, 22), runner=lambda argv, deadline: bad)


def test_unregistered_url_never_spawns_a_child():
    def boom(*a, **k):
        raise AssertionError("no debe lanzar hijo")

    with pytest.raises(pp.PrimarySourceError):
        pp.fetch_registered_document_isolated(
            "UBER", URL.replace("Transcript", "Presentation"), today=TODAY, runner=boom)


def test_html_fetch_goes_through_isolated_worker_and_checks_integrity():
    import base64
    import hashlib

    from app.services.commitment_financial_release import FINANCIAL_ASSETS

    url = FINANCIAL_ASSETS[0].url
    html = b"<html>x</html>"
    good = {"bytes_sha256": hashlib.sha256(html).hexdigest(), "byte_size": len(html),
            "content_type": "text/html", "final_url": url, "html_b64": base64.b64encode(html).decode()}
    seen = []

    def runner(argv, deadline):
        seen.append((argv, deadline))
        return dict(good)

    assert pp.fetch_registered_html_isolated(url, runner=runner) == html
    assert seen[0][0][-1] == "html" and seen[0][1] == pp.TOTAL_DEADLINE_SECONDS
    for bad in (dict(good, final_url="https://evil.example/"), dict(good, bytes_sha256="0" * 64),
                dict(good, content_type="application/pdf"), {"error": "x"}):
        with pytest.raises(pp.PrimarySourceError):
            pp.fetch_registered_html_isolated(url, runner=lambda a, deadline, b=bad: b)
    with pytest.raises(pp.PrimarySourceError):
        pp.fetch_registered_html_isolated(url + "?x=1", runner=runner)
