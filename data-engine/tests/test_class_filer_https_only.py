"""Los fetchers de EDGAR solo abren https (sin file://, ftp://, http://)."""

import json

import pytest

from app.services import class_filer_eps_service as svc


@pytest.mark.parametrize("fetch", [svc._fetch_json, svc._fetch_bytes])
def test_non_https_scheme_is_rejected(tmp_path, fetch):
    target = tmp_path / "x.json"
    target.write_text(json.dumps({"a": 1}))
    for url in (target.as_uri(), "http://data.sec.gov/x", "ftp://data.sec.gov/x"):
        with pytest.raises(ValueError):
            fetch(url)


def _redirect(target):
    """Que haria el opener del servicio ante un 302 a ``target``."""
    import urllib.request

    request = urllib.request.Request("https://data.sec.gov/submissions/CIK0001234567.json")
    handler = next(h for h in svc._OPENER.handlers if isinstance(h, urllib.request.HTTPRedirectHandler))
    return handler.redirect_request(request, None, 302, "Found", {}, target)


@pytest.mark.parametrize(
    "target",
    [
        "http://data.sec.gov/submissions/CIK0001234567.json",  # downgrade
        "http://169.254.169.254/latest/meta-data/",  # metadata interna
        "https://evil.example/x",  # otro host https
        "file:///etc/passwd",  # lectura local (la rechazan http_error_302 y el handler)
        "ftp://data.sec.gov/x",
    ],
)
def test_redirects_outside_edgar_https_are_rejected(target):
    import urllib.error

    with pytest.raises(urllib.error.HTTPError):
        _redirect(target)


@pytest.mark.parametrize(
    "target",
    [
        "https://data.sec.gov/submissions/CIK0001234567.json",
        "https://www.sec.gov/Archives/edgar/data/123/acc/x_htm.xml",
    ],
)
def test_redirects_within_edgar_https_are_followed(target):
    forwarded = _redirect(target)
    assert forwarded is not None and forwarded.full_url == target


def test_fetchers_use_the_strict_opener():
    # Guarda: si alguien vuelve a urllib.request.urlopen, los 302 vuelven
    # a ser libres. Los fetchers deben abrir con el opener endurecido.
    import inspect

    for fetch in (svc._fetch_json, svc._fetch_bytes):
        source = inspect.getsource(fetch)
        assert "_OPENER.open" in source
        assert "urlopen" not in source


@pytest.mark.parametrize(
    "target",
    [
        "https://data.sec.gov:8443/Archives/edgar/data/123/acc/x_htm.xml",
        "https://data.sec.gov:badport/x",
        "https://www.sec.gov:8080/x",
    ],
)
def test_redirects_to_non_default_port_are_rejected(target):
    import urllib.error

    with pytest.raises(urllib.error.HTTPError):
        _redirect(target)


def test_redirect_to_explicit_443_is_followed():
    target = "https://data.sec.gov:443/submissions/CIK0001234567.json"
    forwarded = _redirect(target)
    assert forwarded is not None and forwarded.full_url == target
