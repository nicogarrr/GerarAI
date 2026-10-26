"""Construye snapshots del factsheet del S&P 500 (S&P Dow Jones Indices).

El S&P 500 lo administra S&P Dow Jones Indices: su factsheet mensual publica en
un solo bloque los "Index Characteristics" que sostienen la concentracion top-10
(WEIGHT TOP 10 CONSTITUENTS [%], WEIGHT LARGEST CONSTITUENT [%], NUMBER OF
CONSTITUENTS, capitalizaciones) y fecha el documento con "AS OF <mes> <dia>,
<ano>". Ese "AS OF" es el vintage del snapshot: a partir de el se puede
responder, antes no.

Se ejecuta UNA vez donde hay red y el resultado viaja con la app
(``SP500_FACTSHEET_SNAPSHOT_DIR``), igual que ``build_sec_snapshots.py`` con
``SEC_SNAPSHOT_DIR``. En la VM de Oracle Cloud no hace falta red: la IP esta
baneada por la SEC y aqui no se pide nada a ningun proveedor.

Uso:
    python scripts/build_sp500_factsheet_snapshots.py \
        --source-file /tmp/fs-sp-500.pdf \
        --source-url https://www.spglobal.com/spdji/en/indices/equity/sp-500/ \
        --synced-at 2026-10-01T09:00:00Z \
        --out data/sp500_factsheet_snapshots

Salida (versionada, con fuente):
    <out>/manifest.json                     -> {"snapshots": {"factsheets/<id>.json":
                                                  {"as_of", "synced_at", "sha256"}}, ...}
    <out>/factsheets/sp500-2026-08-31.json  -> el snapshot en si

El parser es DELIBERADAMENTE estricto y falla cerrado: si no encuentra la
ancla de etiquetas, si el numero de valores no es el esperado, si la fecha del
documento no cuadra con ``--as-of`` o si alguna invariante del indice se
incumple, no escribe nada. Un snapshot no escrito es "sin datos con motivo";
un snapshot mal escrito es un numero falso con fecha correcta.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import UTC, date, datetime
from pathlib import Path

if __package__ in (None, ""):  # ejecucion como script: anadir la raiz al path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.connectors.sp500_factsheet import (  # noqa: E402
    FACTSHEET_DIRNAME,
    INDEX_NAME,
    MANIFEST_NAME,
    SOURCE_LICENSE,
    SOURCE_SCOPE,
    SOURCE_TIER,
    clear_cache,
)

PARSER_NAME = "build_sp500_factsheet_snapshots"
PARSER_VERSION = "1"
# La pagina de "Index Characteristics" del factsheet imprime las 8 etiquetas y
# despues, en este orden, los 7 valores. El contrato es posicional y se valida
# con invariantes (ver _validate): si el proveedor cambia el maquetado, el
# script falla en vez de emparejar numeros con la etiqueta de al lado.
LABEL_ANCHOR = "WEIGHT TOP 10 CONSTITUENTS [%]"
VALUE_ORDER = (
    "constituents",
    "mean_total_market_cap_usd_m",
    "largest_total_market_cap_usd_m",
    "smallest_total_market_cap_usd_m",
    "median_total_market_cap_usd_m",
    "weight_largest_pct",
    "weight_top_ten_pct",
)
NUMBER = re.compile(r"-?\d[\d,]*(?:\.\d+)?")
AS_OF = re.compile(r"AS OF ([A-Z]{3,9})\.?\s+(\d{1,2}),\s*(\d{4})")
MONTHS = {name.upper(): index for index, name in enumerate(
    ["January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"], start=1)}


class FactsheetError(RuntimeError):
    """El documento no se pudo leer con confianza: no se escribe snapshot."""


def document_text(source: Path) -> str:
    """Texto plano del factsheet: PDF (pypdf) o HTML/TXT."""
    return document_text_from_bytes(source.read_bytes(), source)


def document_text_from_bytes(raw: bytes, name: Path) -> str:
    """Como document_text() pero sobre bytes ya descargados."""
    if name.suffix.lower() == ".pdf" or raw[:5] == b"%PDF-":
        try:
            from pypdf import PdfReader
        except ImportError as exc:  # pragma: no cover - depende del entorno
            raise FactsheetError("pypdf no instalado: instala pypdf o pasa --source-file .txt") from exc
        import io

        try:
            return "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(raw)).pages)
        except Exception as exc:  # noqa: BLE001 - pypdf lanza excepciones propias
            raise FactsheetError(f"PDF ilegible ({type(exc).__name__})") from exc
    text = raw.decode("utf-8", "replace")
    if name.suffix.lower() in {".html", ".htm"}:
        text = re.sub(r"(?is)<(script|style).*?</\1>", " ", text)
        text = re.sub(r"(?s)<[^>]+>", " ", text)
    return text


def _leading_numbers(text: str) -> list[str]:
    """Numeros inmediatamente posteriores al ancla, en la misma racha de texto.

    Corta en cuanto aparece una palabra: asi ``37.8 AS OF AUGUST 31, 2026`` da
    [37.8] y no se cuela el 31 de la fecha como si fuera un valor del indice.
    """
    numbers: list[str] = []
    cursor = 0
    for match in NUMBER.finditer(text):
        between = text[cursor:match.start()]
        if between.strip():
            break
        numbers.append(match.group(0).replace(",", ""))
        cursor = match.end()
    return numbers


def _as_of_from(text: str) -> date:
    match = AS_OF.search(text)
    if not match:
        raise FactsheetError("el documento no declara 'AS OF <mes> <dia>, <ano>'")
    month = MONTHS.get(match.group(1).upper())
    if month is None:
        raise FactsheetError(f"mes no reconocido en 'AS OF': {match.group(1)!r}")
    try:
        return date(int(match.group(3)), month, int(match.group(2)))
    except ValueError as exc:
        raise FactsheetError(f"'AS OF' con fecha inexistente: {match.group(0)!r}") from exc


def _validate(metrics: dict[str, float]) -> None:
    """Invariantes del S&P 500. Su fallo significa maqueta distinta, no indice raro."""
    if not 450 <= metrics["constituents"] <= 600:
        raise FactsheetError(f"numero de constituyentes fuera de rango: {metrics['constituents']}")
    if not metrics["smallest_total_market_cap_usd_m"] <= metrics["median_total_market_cap_usd_m"] <= metrics["largest_total_market_cap_usd_m"]:
        raise FactsheetError("capitalizaciones incoherentes (smallest <= median <= largest)")
    if not 0 < metrics["mean_total_market_cap_usd_m"] <= metrics["largest_total_market_cap_usd_m"]:
        raise FactsheetError("capitalizacion media incoherente")
    if not 0 < metrics["weight_largest_pct"] <= metrics["weight_top_ten_pct"] <= 100:
        raise FactsheetError("pesos incoherentes (0 < mayor <= top-10 <= 100)")


def extract_index_characteristics(text: str) -> tuple[dict[str, float], date]:
    """(metricas agregadas del indice, AS OF del documento) o FactsheetError."""
    anchor = text.find(LABEL_ANCHOR)
    if anchor < 0:
        raise FactsheetError(f"no se encuentra el ancla {LABEL_ANCHOR!r} (maquetado distinto)")
    tail = text[anchor + len(LABEL_ANCHOR):]
    numbers = _leading_numbers(tail)
    if len(numbers) != len(VALUE_ORDER):
        raise FactsheetError(
            f"se esperaban {len(VALUE_ORDER)} valores tras el ancla y hay {len(numbers)}: {numbers}"
        )
    metrics = {key: float(value) for key, value in zip(VALUE_ORDER, numbers, strict=True)}
    metrics["constituents"] = float(metrics["constituents"])
    _validate(metrics)
    return metrics, _as_of_from(tail)


def snapshot_id(as_of: date, index_name: str = INDEX_NAME) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", index_name.lower()).strip("-")
    return f"{slug}-{as_of.isoformat()}"


def build_snapshot(
    text: str,
    *,
    synced_at: datetime,
    source_url: str,
    source: str = f"{INDEX_NAME} Index Factsheet (S&P Dow Jones Indices)",
    index_name: str = INDEX_NAME,
    document_sha256: str | None = None,
    retrieved_from: str | None = None,
    expected_as_of: date | None = None,
) -> dict:
    metrics, as_of = extract_index_characteristics(text)
    if expected_as_of is not None and expected_as_of != as_of:
        raise FactsheetError(
            f"el documento dice AS OF {as_of.isoformat()} y se pidio {expected_as_of.isoformat()}"
        )
    if synced_at.tzinfo is None:
        raise FactsheetError("synced_at sin zona horaria: el reloj de ingesta es obligatorio")
    if synced_at.astimezone(UTC).date() < as_of:
        raise FactsheetError("synced_at anterior al AS OF del documento: imposible")
    return {
        "index": index_name,
        "as_of": as_of.isoformat(),
        "synced_at": synced_at.astimezone(UTC).isoformat(),
        "source": source,
        "source_url": source_url,
        "source_tier": SOURCE_TIER,
        "source_license": SOURCE_LICENSE,
        "source_scope": SOURCE_SCOPE,
        "retrieved_from": retrieved_from or source_url,
        "metrics": {key: (int(value) if key == "constituents" else value) for key, value in metrics.items()},
        "parser": {
            "name": PARSER_NAME,
            "version": PARSER_VERSION,
            "anchor": LABEL_ANCHOR,
            "document_sha256": document_sha256,
        },
    }


def write_snapshot(out: Path, payload: dict) -> Path:
    """Escribe el snapshot y actualiza el manifest (append, sha256 declarado)."""
    relative = f"{FACTSHEET_DIRNAME}/{snapshot_id(date.fromisoformat(payload['as_of']), payload['index'])}.json"
    path = out / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1, sort_keys=True))
    manifest_path = out / MANIFEST_NAME
    manifest: dict = {}
    if manifest_path.exists():
        try:
            loaded = json.loads(manifest_path.read_text())
        except (OSError, ValueError):
            loaded = {}
        manifest = loaded if isinstance(loaded, dict) else {}
    declared = manifest.get("snapshots")
    # Append: los snapshots anteriores siguen declarados, con su sha256.
    declared = {**declared} if isinstance(declared, dict) else {}
    declared[relative] = {
        "as_of": payload["as_of"],
        "synced_at": payload["synced_at"],
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }
    manifest["snapshots"] = declared
    manifest.update({
        "index": payload["index"],
        "source": payload["source"],
        "source_url": payload["source_url"],
        "source_tier": payload["source_tier"],
        "source_license": payload["source_license"],
        "source_scope": payload["source_scope"],
        "synced_at": payload["synced_at"],
        "built_by": f"{PARSER_NAME}/{PARSER_VERSION}",
    })
    manifest_path.write_text(json.dumps(manifest, indent=1, sort_keys=True))
    clear_cache()
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-file", help="Factsheet local (.pdf/.html/.txt).")
    parser.add_argument("--source-url", help="URL publica del factsheet: se usa como cita, y como "
                                            "destino de descarga si no hay --source-file.")
    parser.add_argument("--retrieved-from", help="URL de la que se descargo el fichero si no es la "
                                                 "canonica (declarado aparte, nunca implicito).")
    parser.add_argument("--fetched-at", help="ISO-8601 con zona; si falta, ahora en UTC.")
    parser.add_argument("--as-of", help="Comprobar el AS OF del documento contra esta fecha (YYYY-MM-DD).")
    parser.add_argument("--index-name", default=INDEX_NAME)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    if not args.source_file and not args.source_url:
        parser.error("hace falta --source-file o --source-url")

    synced_at = (
        datetime.fromisoformat(args.fetched_at.replace("Z", "+00:00")) if args.fetched_at else datetime.now(UTC)
    )
    if synced_at.tzinfo is None:
        parser.error("--fetched-at necesita zona horaria (p.ej. 2026-10-01T09:00:00Z)")

    citation = args.source_url or ""
    retrieved_from = args.retrieved_from or args.source_url
    if args.source_file:
        source_path = Path(args.source_file)
        if not source_path.is_file():
            parser.error(f"no existe el fichero: {source_path}")
        raw = source_path.read_bytes()
    else:
        import httpx

        # spglobal.com responde 403 a clientes automaticos: la descarga se hace
        # a mano (el factsheet es publico) y se pasa el fichero. Si aun asi se
        # intenta por red, el error lo dice claro en vez de escribir un snapshot.
        headers = {"User-Agent": "Mozilla/5.0 (compatible; GerarAI/0.1) Research snapshot builder"}
        response = httpx.get(args.source_url, timeout=60, follow_redirects=True, headers=headers)
        response.raise_for_status()
        raw = response.content

    try:
        text = document_text_from_bytes(raw, Path(args.source_file or "factsheet.pdf"))
        payload = build_snapshot(
            text,
            synced_at=synced_at,
            source_url=citation or f"file://{Path(args.source_file).resolve()}",
            index_name=args.index_name,
            document_sha256=hashlib.sha256(raw).hexdigest(),
            retrieved_from=retrieved_from,
            expected_as_of=date.fromisoformat(args.as_of) if args.as_of else None,
        )
    except FactsheetError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 2
    path = write_snapshot(Path(args.out), payload)
    print(f"OK as_of={payload['as_of']} synced_at={payload['synced_at']} -> {path}")
    print(f"   top-10 weight = {payload['metrics']['weight_top_ten_pct']}% | "
          f"largest = {payload['metrics']['weight_largest_pct']}% | "
          f"constituents = {payload['metrics']['constituents']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
