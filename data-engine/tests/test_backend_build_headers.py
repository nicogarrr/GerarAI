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
    assert 'apt-mark manual "$library"' in dockerfile[:cleanup]
    assert "import numpy, scipy, arch, torch; import sentence_transformers" in block
    assert "tesseract --version" in block
    assert "libgomp1 libatomic1 libquadmath0" in dockerfile[:cleanup]


@pytest.mark.parametrize("name", ["Dockerfile", "Dockerfile.prod"])
@pytest.mark.parametrize("architecture", ["arm64", "amd64"])
def test_runtime_library_marking_uses_only_installed_packages(name, architecture, tmp_path):
    """Execute the actual RUN prefix with architecture-specific dpkg inventory."""
    import subprocess

    dockerfile = (ENGINE / name).read_text()
    run = next(block for block in dockerfile.split("\n\n")
               if "apt-get purge --auto-remove -y" in block)
    prefix = run[run.index("RUN ") + 4:].split("&& apt-get purge", 1)[0]
    # The old unconditional apt-mark fails for ARM's absent libquadmath0.
    inventory = "libstdc++6 libgcc-s1 libffi8 libgomp1 libatomic1"
    if architecture == "amd64":
        inventory += " libquadmath0"
    scripts = {
        "dpkg-query": """#!/bin/sh
for installed in $INSTALLED; do
    if [ "$installed" = "$3" ]; then
        printf 'install ok installed'; exit 0
    fi
done
exit 1
""",
        "apt-mark": """#!/bin/sh
shift
for package in "$@"; do
    case " $INSTALLED " in
        *" $package "*) printf '%s\\n' "$package" ;;
        *) exit 42 ;;
    esac
done
""",
    }
    for command, content in scripts.items():
        executable = tmp_path / command
        executable.write_text(content)
        executable.chmod(0o755)
    script = prefix.rstrip().removesuffix("\\").rstrip()
    result = subprocess.run(
        ["sh", "-ec", script], env={"INSTALLED": inventory, "PATH": f"{tmp_path}:/usr/bin:/bin"},
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert set(result.stdout.splitlines()) == set(inventory.split())
