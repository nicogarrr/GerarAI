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
