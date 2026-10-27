"""Local OCR only. Image text is data, never prompts, paths or executable input."""
from __future__ import annotations

import csv
import hashlib
import io
import os
import re
import shutil
import subprocess
import threading
from decimal import Decimal, InvalidOperation

_OCR_SLOT = threading.BoundedSemaphore(1)

MAX_IMAGE_BYTES = 2 * 1024 * 1024
MAX_IMAGE_PIXELS = 12_000_000
QUANTITY_HEADERS = {"cantidad", "quantity", "position", "shares", "acciones", "titulos", "títulos", "unidades"}


def strict_quantity(raw: str) -> str | None:
    """Reject ambiguous thousands/decimal notation instead of silently multiplying holdings."""
    if not re.fullmatch(r"\d+(?:[.,]\d+)?", raw):
        return None
    if re.search(r"[.,]\d{3}$", raw):
        return None
    try:
        value = Decimal(raw.replace(",", "."))
    except InvalidOperation:
        return None
    return str(value) if value.is_finite() and 0 < value <= 1_000_000_000 else None


def parse_tsv(text: str) -> list[dict]:
    groups: dict[tuple, list[dict]] = {}
    for word in csv.DictReader(io.StringIO(text), delimiter="\t"):
        if word.get("level") != "5" or not word.get("text", "").strip():
            continue
        key = tuple(word[k] for k in ("page_num", "block_num", "par_num", "line_num"))
        groups.setdefault(key, []).append(word)
    header_x = None
    rows = []
    for words in groups.values():
        words.sort(key=lambda w: int(w["left"]))
        headers = [w for w in words if w["text"].lower().strip(":") in QUANTITY_HEADERS]
        if headers:
            header_x = int(headers[0]["left"])
            continue
        raw = " ".join(w["text"] for w in words)[:500]
        if header_x is None:
            continue
        # A row is only a candidate. Even high-confidence OCR needs explicit review.
        numbers = [w for w in words if abs(int(w["left"]) - header_x) < 70]
        quantity_word = numbers[0] if len(numbers) == 1 else None
        quantity = strict_quantity(quantity_word["text"]) if quantity_word else None
        identity = " ".join(w["text"] for w in words if int(w["left"]) < header_x - 70)
        if not identity or not any(c.isalpha() for c in identity):
            continue
        currency_words = [w for w in words if w["text"] in {"USD", "EUR", "GBP", "CAD", "CHF", "JPY", "HKD", "AUD"}]
        currency = currency_words[0]["text"] if len(currency_words) == 1 else None
        confidence = min(float(w["conf"]) for w in words)
        if quantity_word and float(quantity_word["conf"]) < 70:
            quantity = None
        rows.append({"raw": raw, "identity": identity[:160], "quantity": quantity,
                     "currency": currency, "needs_review": True,
                     "warning": "Revisa instrumento, cantidad y divisa" if quantity and currency else "Cantidad o divisa ilegible/ambigua: corrige antes de continuar",
                     "confidence": round(confidence, 1)})
        if len(rows) >= 60:
            break
    return rows


def extract_image(data: bytes) -> dict:
    from PIL import Image, ImageOps, UnidentifiedImageError

    if not data or len(data) > MAX_IMAGE_BYTES:
        raise ValueError("La imagen debe ocupar como máximo 2 MB")
    if not shutil.which("tesseract"):
        raise RuntimeError("No se pudo iniciar la lectura local. Usa un fichero o la entrada manual")
    try:
        with Image.open(io.BytesIO(data)) as source:
            if source.format not in {"PNG", "JPEG", "WEBP"} or getattr(source, "n_frames", 1) != 1:
                raise ValueError("Usa una imagen PNG, JPEG o WebP sin animación")
            if source.width * source.height > MAX_IMAGE_PIXELS or min(source.size) < 100:
                raise ValueError("La imagen debe tener entre 100 píxeles de lado y 12 megapíxeles")
            source.load()
            image = ImageOps.exif_transpose(source).convert("L")
            mean_pixel = image.resize((1, 1)).getpixel((0, 0))
            if isinstance(mean_pixel, (int, float)) and mean_pixel < 128:
                image = ImageOps.invert(image)
            image = ImageOps.autocontrast(image)
            output = io.BytesIO()
            image.save(output, format="PNG")
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError) as exc:
        raise ValueError("No se puede leer esta imagen; prueba con otra captura") from exc
    # No shell, no filename supplied by user, no temporary image, bounded time/thread count.
    if not _OCR_SLOT.acquire(blocking=False):
        raise RuntimeError("Hay otra captura en lectura. Vuelve a intentarlo en unos segundos")
    try:
        result = subprocess.run(
            ["tesseract", "stdin", "stdout", "-l", "eng", "--psm", "6", "tsv"],
            input=output.getvalue(), capture_output=True, timeout=12, check=True,
            env={**os.environ, "OMP_THREAD_LIMIT": "1"},
        )
    except (subprocess.SubprocessError, OSError) as exc:
        raise RuntimeError("No se pudo leer la captura. Prueba con un recorte más nítido o importa un fichero") from exc
    finally:
        _OCR_SLOT.release()
    if len(result.stdout) > 2_000_000:
        raise ValueError("La captura contiene demasiado texto. Recorta solo la tabla de posiciones")
    rows = parse_tsv(result.stdout.decode("utf-8", errors="replace"))
    return {"image_hash": hashlib.sha256(data).hexdigest(), "rows": rows,
            "message": "Selecciona explícitamente cada instrumento y revisa las filas. Los precios de la captura no se importan." if rows else "No se reconocieron filas con cabecera de cantidad. Recorta la tabla incluyendo la cabecera o usa un fichero/manual.",
            "cash": None, "margin": None}
