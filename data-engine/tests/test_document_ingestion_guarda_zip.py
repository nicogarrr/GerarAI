"""Ingesta de documentos: la guarda OOXML rechaza ZIPs malformados o enganosos.

Todos los ficheros son ZIPs sinteticos construidos al vuelo (un DOCX/XLSX es un
ZIP): se parte de uno valido (zipfile) y se corrompe a proposito UN aspecto por
test, parcheando los bytes del directorio central o de la cabecera local. Sin
red, sin disco y sin ficheros de fixture.

NO prueba (declarado): un zip bomb real de gigabytes (los limites de expansion
ya los cubre test_document_ingestion_zip_bomb.py), ni la lectura posterior con
python-docx/openpyxl (la guarda se prueba por llamada directa).
"""

from __future__ import annotations

import struct
import zipfile
from io import BytesIO

import pytest

from app.services.document_ingestion_service import guard_ooxml_zip

CONTENIDO = b"Datos de prueba para el flujo deflate de la guarda OOXML. " * 8


def _zip_base() -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("xl/worksheets/sheet1.xml", CONTENIDO)
    return buffer.getvalue()


def _pos_central(content: bytes) -> int:
    pos = content.find(b"PK\x01\x02")
    assert pos > 0
    return pos


def _offset_local(content: bytes) -> int:
    """Offset de la cabecera local segun el directorio central."""
    cd = _pos_central(content)
    return struct.unpack_from("<I", content, cd + 42)[0]


def test_zip_cifrado_rechazado():
    """El flag de cifrado (bit 0) del directorio central basta para rechazar."""
    content = bytearray(_zip_base())
    cd = _pos_central(content)
    struct.pack_into("<H", content, cd + 8, 1)  # general purpose flag: cifrado
    with pytest.raises(ValueError, match="cifrado"):
        guard_ooxml_zip(bytes(content))


def test_metodo_de_compresion_no_admitido_rechazado():
    """BZIP2 es un ZIP legitimo pero la guarda solo admite STORED/DEFLATED."""
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_BZIP2) as zf:
        zf.writestr("a.txt", CONTENIDO)
    with pytest.raises(ValueError, match="metodo de compresion"):
        guard_ooxml_zip(buffer.getvalue())


def test_offset_de_cabecera_corrupto_rechazado():
    """El offset de la cabecera local apunta fuera del fichero."""
    content = bytearray(_zip_base())
    cd = _pos_central(content)
    struct.pack_into("<I", content, cd + 42, len(content) + 1000)
    with pytest.raises(ValueError, match="cabecera ZIP corrupta"):
        guard_ooxml_zip(bytes(content))


def test_cabecera_local_inconsistente_rechazada():
    """La cabecera local dice STORED y el directorio central DEFLATED."""
    content = bytearray(_zip_base())
    local = _offset_local(content)
    struct.pack_into("<H", content, local + 8, zipfile.ZIP_STORED)
    with pytest.raises(ValueError, match="cabecera ZIP inconsistente"):
        guard_ooxml_zip(bytes(content))


def test_datos_truncados_rechazados():
    """El directorio central declara un flujo comprimido mayor que el fichero."""
    content = bytearray(_zip_base())
    cd = _pos_central(content)
    struct.pack_into("<I", content, cd + 20, len(content) * 4)  # compress_size
    with pytest.raises(ValueError, match="datos ZIP truncados"):
        guard_ooxml_zip(bytes(content))


def test_flujo_deflate_con_datos_sobrantes_rechazado():
    """Tras el final real del DEFLATE hay basura dentro del tamano declarado:
    unused_data delata la incoherencia (se insertan 2 bytes y se ajustan el
    directorio central y el EOCD para que zipfile siga parseando)."""
    content = bytearray(_zip_base())
    cd = _pos_central(content)
    csize = struct.unpack_from("<I", content, cd + 20)[0]
    local = _offset_local(content)
    nombre, extra = struct.unpack_from("<2H", content, local + 26)
    inicio_datos = local + 30 + nombre + extra
    fin_datos = inicio_datos + csize
    # 2 bytes de basura al final del flujo, antes del directorio central.
    content[fin_datos:fin_datos] = b"XX"
    cd += 2
    struct.pack_into("<I", content, cd + 20, csize + 2)
    eocd = content.rfind(b"PK\x05\x06")
    assert eocd > 0
    cd_offset = struct.unpack_from("<I", content, eocd + 16)[0]
    struct.pack_into("<I", content, eocd + 16, cd_offset + 2)
    with pytest.raises(ValueError, match="flujo ZIP incompleto o inconsistente"):
        guard_ooxml_zip(bytes(content))


def test_flujo_deflate_corrupto_rechazado():
    """El primer byte del flujo DEFLATE declara un tipo de bloque reservado:
    zlib.error se traduce a un ValueError declarado (nunca una excepcion
    interna). Determinista: 0xFF como primer byte siempre rompe el flujo."""
    content = bytearray(_zip_base())
    local = _offset_local(content)
    nombre, extra = struct.unpack_from("<2H", content, local + 26)
    inicio_datos = local + 30 + nombre + extra
    content[inicio_datos] = 0xFF  # BFINAL=1, BTYPE=11 (reservado)
    with pytest.raises(ValueError, match="flujo ZIP corrupto"):
        guard_ooxml_zip(bytes(content))


def test_zip_valido_pasa_la_guarda():
    """Control: el ZIP base (deflate normal) pasa, y tambien uno STORED."""
    guard_ooxml_zip(_zip_base())
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as zf:
        zf.writestr("a.txt", CONTENIDO)
    guard_ooxml_zip(buffer.getvalue())


