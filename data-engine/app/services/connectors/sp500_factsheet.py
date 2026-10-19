"""Factsheet del S&P 500 (S&P Dow Jones Indices) como snapshot en disco, con vintage.

Por que un snapshot y no una llamada en caliente: el S&P 500 lo administra
S&P Dow Jones Indices, y su factsheet mensual publica en un solo bloque los
"Index Characteristics" que sostienen la concentracion top-10 (WEIGHT TOP 10
CONSTITUENTS [%], WEIGHT LARGEST CONSTITUENT [%], NUMBER OF CONSTITUENTS). El
documento lleva su propio "AS OF <fecha de mes>", asi que el dato nace
fechado: un snapshot solo puede responder para fechas >= su ``as_of``, y para
fechas anteriores devuelve "sin datos" con motivo, jamas el presente aplicado
al pasado. Esa es la unica forma de que la concentracion top-10 deje de estar
permanentemente no disponible sin introducir look-ahead.

Mismo patron que ``SEC_SNAPSHOT_DIR``: el documento se descarga una vez donde
hay red (``scripts/build_sp500_factsheet_snapshots.py``) y en produccion se
lee de disco. La IP de la VM de Oracle Cloud esta baneada por la SEC, pero aqui
no hay trafico a proveedor: ni en el build del snapshot de mercado ni en el
GET de ``/api/market/regime`` (que solo lee el snapshot ya persistido).

Solo se persisten caracteristicas AGREGADAS del indice y su cita. El listado
de pesos por constituyente que publica el proveedor no se copia ni se sirve:
no es gratis, y un agregado con fuente es lo que se puede defender.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import date, datetime
from pathlib import Path
from typing import Any

INDEX_NAME = "S&P 500"
# Opt-in explicito, igual que sec_snapshot_dir: sin la variable de entorno no
# hay snapshot y la metrica responde "sin datos" con motivo. Un directorio por
# defecto haria que un fichero desplegadoiese por vintage valido cualquier dia.
SNAPSHOT_DIR_ENV = "SP500_FACTSHEET_SNAPSHOT_DIR"
MANIFEST_NAME = "manifest.json"
FACTSHEET_DIRNAME = "factsheets"
# Tier de procedencia: el proveedor del indice es la fuente primaria de la
# composicion y de los pesos del S&P 500 (no es un agregador ni un estimativa).
SOURCE_TIER = "index_provider_official"
SOURCE_SCOPE = "aggregate_index_characteristics_only"
SOURCE_LICENSE = (
    "Factsheet de S&P Dow Jones Indices, descarga publica sin clave; el documento "
    "se marca 'FOR USE WITH INSTITUTIONS ONLY, NOT FOR USE WITH RETAIL INVESTORS' "
    "y S&P DJI se reserva la redistribucion. Aqui solo se guardan caracteristicas "
    "agregadas del indice con su cita, nunca el documento ni los pesos por "
    "constituyente."
)

# Motivos de no disponibilidad: son el contrato que consumen los tests y el
# informe; cambiar uno sin actualizar la politica rompe la trazabilidad.
REASON_DIR_NOT_CONFIGURED = "snapshot_dir_not_configured"
REASON_NO_SNAPSHOT = "no_snapshot_in_disk"
REASON_VINTAGE_AFTER = "snapshot_vintage_after_requested_date"
REASON_INTEGRITY = "snapshot_integrity_failed"
REASON_INVALID_DATE = "requested_date_invalid"

REQUIRED_KEYS = ("as_of", "synced_at", "source", "source_url", "source_tier", "metrics")

# Cache en memoria indexada por la firma de los ficheros (mtime + tamano): el
# actor diario relee sin coste, y un snapshot reconstruido se ve en la misma
# llamada siguiente. La clave incluye el directorio, asi que dos despliegues
# con directorios distintos no se contaminan.
_CACHE: dict[str, tuple[tuple, list[dict[str, Any]], list[str]]] = {}


def snapshot_dir() -> Path | None:
    """Directorio de snapshots configurado, o None si no hay ninguno."""
    raw = os.getenv(SNAPSHOT_DIR_ENV, "").strip()
    return Path(raw) if raw else None


def clear_cache() -> None:
    """Olvida la cache en memoria (tests y reconstruccion de snapshots)."""
    _CACHE.clear()


def _signature(path: Path) -> tuple[int, int] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return (stat.st_mtime_ns, stat.st_size)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _as_date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _as_datetime(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _positive(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    return number if 0.0 < number <= 100.0 else None


def _valid_payload(payload: Any, path: Path, declared: dict[str, Any]) -> dict[str, Any] | None:
    """Payload utilizable o None. Fail closed: mejor sin dato que dato dudoso."""
    if not isinstance(payload, dict) or any(key not in payload for key in REQUIRED_KEYS):
        return None
    as_of, synced_at = _as_date(payload["as_of"]), _as_datetime(payload["synced_at"])
    metrics = payload.get("metrics")
    if as_of is None or synced_at is None or synced_at.tzinfo is None or not isinstance(metrics, dict):
        return None
    if not str(payload.get("source") or "") or not str(payload.get("source_url") or ""):
        return None
    # El manifest manda: un fichero sin sha256 declarado, o con un sha256 que no
    # casa, es una subida parcial de un sync anterior y no se sirve.
    expected = declared.get("sha256")
    if not expected or expected != _sha256(path):
        return None
    declared_as_of = _as_date(declared.get("as_of"))
    if declared_as_of is not None and declared_as_of != as_of:
        return None
    return {**payload, "as_of": as_of, "synced_at": synced_at, "metrics": metrics, "path": str(path)}


def top_ten_weight_pct(payload: dict[str, Any]) -> float | None:
    """Peso publicado de los 10 mayores constituyentes, o None si no lo publica.

    None es una respuesta, no un fallo: una fuente que solo da composicion (sin
    pesos) no permite calcular concentracion, y el metodo no rellena el hueco.
    """
    metrics = payload.get("metrics")
    if not isinstance(metrics, dict):
        return None
    return _positive(metrics.get("weight_top_ten_pct"))


def _index(root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """(snapshots validos de mas nuevo a mas viejo, problemas de integridad)."""
    manifest = root / MANIFEST_NAME
    factsheets = root / FACTSHEET_DIRNAME
    entries = sorted(p for p in factsheets.glob("*.json") if p.is_file()) if factsheets.is_dir() else []
    signature = (
        _signature(manifest),
        tuple((p.name, _signature(p)) for p in entries),
    )
    cached = _CACHE.get(str(root))
    if cached and cached[0] == signature:
        return cached[1], cached[2]
    problems: list[str] = []
    manifest_data: Any = None
    if manifest.is_file():
        try:
            manifest_data = json.loads(manifest.read_text())
        except (OSError, ValueError) as exc:
            problems.append(f"{MANIFEST_NAME} ilegible: {type(exc).__name__}")
    elif entries:
        # Hay ficheros y no hay manifest: ninguno puede declararse con sha256.
        problems.append(f"{MANIFEST_NAME} ausente: ningun snapshot puede declararse")
    declared = {}
    if isinstance(manifest_data, dict) and isinstance(manifest_data.get("snapshots"), dict):
        declared = manifest_data["snapshots"]
    elif manifest_data is not None:
        problems.append(f"{MANIFEST_NAME} sin dict 'snapshots'")
    snapshots: list[dict[str, Any]] = []
    for path in entries:
        relative = f"{FACTSHEET_DIRNAME}/{path.name}"
        entry = declared.get(relative)
        if not isinstance(entry, dict):
            problems.append(f"{relative} no declarado en el manifest")
            continue
        try:
            payload = json.loads(path.read_text())
        except (OSError, ValueError) as exc:
            problems.append(f"{relative} ilegible: {type(exc).__name__}")
            continue
        valid = _valid_payload(payload, path, entry)
        if valid is None:
            problems.append(f"{relative} no supera la validacion de procedencia")
            continue
        snapshots.append(valid)
    snapshots.sort(key=lambda item: item["as_of"], reverse=True)
    _CACHE[str(root)] = (signature, snapshots, problems)
    return snapshots, problems


def read_factsheet(requested: date | None) -> dict[str, Any]:
    """Snapshot vigente para ``requested`` (el de ``as_of`` mas reciente <= fecha).

    Contrato: nunca devuelve un snapshot con vintage posterior a la fecha
    pedida. Si el unico snapshot en disco es posterior, la respuesta es no
    disponible con ``snapshot_vintage_after_requested_date`` y las fechas de
    ambos lados para que el motivo sea trazable.
    """
    root = snapshot_dir()
    # Sin fecha no hay vintage que resolver, diga lo que diga el directorio:
    # la fecha se valida primero para que el motivo sea el correcto.
    if not isinstance(requested, date) or isinstance(requested, datetime):
        return {
            "available": False,
            "index": INDEX_NAME,
            "reason": REASON_INVALID_DATE,
            "detail": "fecha de consulta ausente o invalida: sin fecha no hay vintage",
            "snapshot_dir": str(root) if root else None,
        }
    if root is None:
        return {
            "available": False,
            "index": INDEX_NAME,
            "reason": REASON_DIR_NOT_CONFIGURED,
            "detail": f"{SNAPSHOT_DIR_ENV} sin definir: no hay snapshot que leer",
            "snapshot_dir": None,
        }
    snapshots, problems = _index(root)
    if not snapshots:
        return {
            "available": False,
            "index": INDEX_NAME,
            "reason": REASON_INTEGRITY if problems else REASON_NO_SNAPSHOT,
            "detail": "; ".join(problems) if problems else "Sin factsheet del S&P 500 disponible",
            "snapshot_dir": str(root),
            "integrity_problems": problems,
        }
    eligible = [item for item in snapshots if item["as_of"] <= requested]
    if not eligible:
        newest = snapshots[0]
        return {
            "available": False,
            "index": INDEX_NAME,
            "reason": REASON_VINTAGE_AFTER,
            "detail": (
                f"el snapshot en disco es de {newest['as_of'].isoformat()} y la fecha pedida es "
                f"anterior: no se aplica el presente al pasado"
            ),
            "snapshot_dir": str(root),
            "requested_date": requested.isoformat(),
            "snapshot_as_of": newest["as_of"].isoformat(),
            "snapshot_source": newest.get("source"),
            "snapshot_source_url": newest.get("source_url"),
            "snapshot_source_tier": newest.get("source_tier"),
            "snapshot_synced_at": newest["synced_at"].isoformat(),
            "snapshots_in_disk": [item["as_of"].isoformat() for item in snapshots],
        }
    chosen = eligible[0]
    return {
        "available": True,
        "index": INDEX_NAME,
        "requested_date": requested.isoformat(),
        "snapshot_as_of": chosen["as_of"].isoformat(),
        "snapshot_dir": str(root),
        "payload": chosen,
    }
