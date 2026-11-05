"""Contratos estaticos de scripts/ops/audit-storage-diff.sh (read-only)."""
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "ops" / "audit-storage-diff.sh"


def _script_text() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_storage_audit_script_is_valid_bash() -> None:
    bash = shutil.which("bash")
    assert bash, "bash no disponible en el entorno de tests"
    subprocess.run([bash, "-n", str(SCRIPT)], check=True)


def test_storage_audit_is_strictly_read_only() -> None:
    text = _script_text()
    assert "SOLO LECTURA" in text
    for forbidden in ("put_object", "remove_object", "fput_object",
                      "delete_object", "make_bucket", "remove_bucket"):
        assert forbidden not in text, f"mutacion de almacen permitida: {forbidden}"
    assert "list_objects" in text


def test_storage_audit_reports_migration_gaps_both_directions() -> None:
    text = _script_text()
    # Huecos de migracion (MinIO sin Garage) y escrituras nuevas (Garage sin MinIO).
    assert "HUECOS DE MIGRACION" in text
    assert "NUEVOS EN GARAGE" in text
    assert "TAMANO DISTINTO" in text


def test_storage_audit_uses_backend_settings_for_live_side() -> None:
    text = _script_text()
    # El lado vivo sale de la config real del backend; el archivo es sobreescribible.
    assert "get_settings" in text
    assert "ARCHIVE_ENDPOINT" in text
    assert "ARCHIVE_ACCESS_KEY" in text
