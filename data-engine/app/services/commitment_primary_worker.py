"""Hijo aislado: descarga el activo EXACTO y extrae texto con limites de CPU/memoria.

Se ejecuta como `python -m app.services.commitment_primary_worker <url>` y escribe UN json en
stdout: {bytes_sha256, byte_size, content_type, final_url, pages}. La politica de red sigue
siendo fetch_public_url (IP fijada, SSRF, tope de bytes) con igualdad exacta de URL.
"""

from __future__ import annotations

import hashlib
import json
import resource
import sys


def main(url: str, mode: str = "pdf") -> int:
    from app.services.commitment_primary_pipeline import (
        MAX_BYTES,
        TIMEOUT_SECONDS,
        PrimarySourceError,
        _pdf_pages,
    )
    from app.services.public_fetch import fetch_public_url

    try:
        content, ctype, final_url = fetch_public_url(
            url, max_bytes=MAX_BYTES, timeout=TIMEOUT_SECONDS, allowed_url=lambda u: u == url
        )
        if final_url != url:
            raise PrimarySourceError("La descarga termino en una URL distinta de la registrada")
        want = "text/html" if mode == "html" else "application/pdf"
        if (ctype or "").split(";")[0].strip().lower() != want:
            raise PrimarySourceError(f"Content-Type no es {want}")
        if mode == "html":
            import base64

            sys.stdout.write(json.dumps({
                "bytes_sha256": hashlib.sha256(content).hexdigest(), "byte_size": len(content),
                "content_type": want, "final_url": final_url,
                "html_b64": base64.b64encode(content).decode()}))
            return 0
        if not content.startswith(b"%PDF"):
            raise PrimarySourceError("La fuente no es un PDF")
        pages = _pdf_pages(content)
    except PrimarySourceError as exc:
        sys.stdout.write(json.dumps({"error": str(exc)}))
        return 0
    except Exception:
        sys.stdout.write(json.dumps({"error": "No se pudo descargar o extraer la fuente oficial"}))
        return 0
    sys.stdout.write(
        json.dumps(
            {
                "bytes_sha256": hashlib.sha256(content).hexdigest(),
                "byte_size": len(content),
                "content_type": "application/pdf",
                "final_url": final_url,
                "pages": pages,
            }
        )
    )
    return 0


if __name__ == "__main__":
    cpu = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    mem = int(sys.argv[3]) if len(sys.argv) > 3 else 1_000_000_000
    resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
    resource.setrlimit(resource.RLIMIT_AS, (mem, mem))
    sys.exit(main(sys.argv[1], sys.argv[4] if len(sys.argv) > 4 else "pdf"))
