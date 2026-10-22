"""alembic_version.version_num es VARCHAR(32): un id mas largo falla en PostgreSQL (SQLite no lo detecta)."""
import re
from pathlib import Path


def test_all_revision_ids_fit_alembic_version_column():
    root = Path(__file__).resolve().parent.parent / "alembic" / "versions"
    for f in root.glob("*.py"):
        m = re.search(r'^revision\s*=\s*"([^"]+)"', f.read_text(), re.M)
        assert m, f.name
        assert len(m.group(1)) <= 32, (f.name, m.group(1), len(m.group(1)))
