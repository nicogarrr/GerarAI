"""Genera tests/fixtures/docling_two_page.pdf: PDF minimo de 2 paginas con texto.

PDF artesanal (sin dependencias): solo objetos Catalog/Pages/Page/Font Type1
Helvetica con streams de contenido. pypdf lo parsea; sirve para testear el
fallback pypdf del pipeline de dos carriles sin descargar nada. Pocos KB.
"""

from __future__ import annotations

from pathlib import Path

PAGE_TEXTS = (
    "GerarAI two lane fixture page one. Revenue grew twelve percent with margin discipline.",
    "GerarAI two lane fixture page two. Risks include cyclicality and customer concentration.",
)


def _content_stream(text: str) -> bytes:
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    return f"BT /F1 18 Tf 72 720 Td ({escaped}) Tj ET".encode("latin-1")


def build_pdf(pages: tuple[str, ...] = PAGE_TEXTS) -> bytes:
    objects: list[bytes] = []
    n_pages = len(pages)
    # 1: Catalog, 2: Pages, luego por pagina (Page, Contents), N: Font.
    page_obj_nums = [3 + 2 * i for i in range(n_pages)]
    font_obj_num = 3 + 2 * n_pages
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    kids = " ".join(f"{num} 0 R" for num in page_obj_nums)
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {n_pages} >>".encode("latin-1"))
    for i, text in enumerate(pages):
        page_num = page_obj_nums[i]
        stream = _content_stream(text)
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Contents {page_num + 1} 0 R "
            f"/Resources << /Font << /F1 {font_obj_num} 0 R >> >> >>".encode("latin-1")
        )
        objects.append(
            f"<< /Length {len(stream)} >>\nstream\n".encode("latin-1") + stream + b"\nendstream"
        )
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode("latin-1") + body + b"\nendobj\n"
    xref_at = len(out)
    total = len(objects) + 1
    out += f"xref\n0 {total}\n".encode("latin-1")
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode("latin-1")
    out += (
        f"trailer\n<< /Size {total} /Root 1 0 R >>\n"
        f"startxref\n{xref_at}\n%%EOF".encode("latin-1")
    )
    return bytes(out)


def main() -> None:
    target = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "docling_two_page.pdf"
    target.write_bytes(build_pdf())
    print(f"wrote {target} ({target.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
