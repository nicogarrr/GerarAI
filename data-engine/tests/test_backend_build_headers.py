"""Build-only kernel headers must not remain in either backend runtime."""
from pathlib import Path

import pytest

ENGINE = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("name", ["Dockerfile", "Dockerfile.prod"])
def test_backend_removes_build_headers_after_python_install(name):
    dockerfile = (ENGINE / name).read_text()
    install = dockerfile.index("pip install")
    cleanup = dockerfile.index("apt-get purge --auto-remove -y")
    runtime = dockerfile.index("USER cavaai")
    assert install < cleanup < runtime
    block = dockerfile[cleanup:runtime].split("\n\n", 1)[0]
    assert "linux-libc-dev" in block
    assert "gcc g++ libffi-dev" in block
    assert "dpkg-query" in block  # build fails if the headers remain
    assert "apt-mark manual libstdc++6 libgcc-s1 libffi8" in dockerfile[:cleanup]
    assert "import numpy, scipy, arch, torch; import sentence_transformers" in block
    assert "tesseract --version" in block
    assert "libgomp1 libatomic1 libquadmath0" in dockerfile[:cleanup]
