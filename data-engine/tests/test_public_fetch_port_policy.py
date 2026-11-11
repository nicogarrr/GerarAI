"""Public downloads keep the existing effective policy: HTTP 80 / HTTPS 443."""

import asyncio

import pytest

from app.services import public_fetch as pf


@pytest.mark.parametrize('url', [
    'http://reports.example:8080/report',
    'https://reports.example:8443/report',
    'http://reports.example:443/report',
    'https://reports.example:80/report',
    'https://reports.example:0/report',
])
@pytest.mark.parametrize('asynchronous', [False, True])
def test_nonstandard_ports_rejected_before_dns(monkeypatch, url, asynchronous):
    def no_dns(*args, **kwargs):
        raise AssertionError('port policy must reject before DNS')

    monkeypatch.setattr(pf.socket, 'getaddrinfo', no_dns)
    monkeypatch.setattr(pf.anyio, 'getaddrinfo', no_dns)
    with pytest.raises(ValueError, match='port'):
        if asynchronous:
            asyncio.run(pf.fetch_public_url_async(url))
        else:
            pf.fetch_public_url(url)


@pytest.mark.parametrize('url,expected', [
    ('http://reports.example:80/report', 80),
    ('https://reports.example:443/report', 443),
])
def test_explicit_standard_ports_still_allowed(url, expected):
    assert pf._parse_public_url(url)[2] == expected
