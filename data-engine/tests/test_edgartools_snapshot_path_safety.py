"""Snapshot edgartools: traversal de rutas y fuga de texto de excepciones.

- read_companyfacts/read_submissions: un CIK no numerico ("../../..") no debe
  salir del directorio del snapshot (py/path-injection, alertas 194/195).
- read_filing_xml: accession no numerico o filename con separadores/".." no
  debe leer fuera de filings/.
- Un information table malformado no filtra texto de la excepcion al payload
  (py/stack-trace-exposure, alerta 196).
"""

from __future__ import annotations

import json
from pathlib import Path

from app.services.connectors import edgartools_client
from app.services.edgartools_ingestion_service import (
    _thirteenf_filings_from_submissions,
    refresh_13f_from_edgartools,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "edgartools"
SUBMISSIONS = json.loads((FIXTURES / "submissions" / "CIK0001234567.json").read_text(encoding="utf-8"))


def _root(tmp_path: Path) -> Path:
    (tmp_path / "submissions").mkdir()
    (tmp_path / "companyfacts").mkdir()
    (tmp_path / "filings").mkdir()
    return tmp_path


def test_cik_no_numerico_no_escapa_del_snapshot(tmp_path):
    root = _root(tmp_path)
    # Contrato: un CIK no numerico nunca llega al filesystem (defensa en
    # profundidad: ademas el segmento "CIK..." no existe como directorio, asi
    # que el kernel resolvia ENOENT incluso sin la validacion).
    for sub in ("submissions", "companyfacts"):
        (tmp_path / sub / "x.json").write_text(json.dumps({"filtrado": True}), encoding="utf-8")
    assert edgartools_client.read_submissions("../../x", root) is None
    assert edgartools_client.read_companyfacts("../../x", root) is None
    assert edgartools_client.read_submissions("../../../etc", root) is None
    assert edgartools_client.read_submissions("1234567", root) is None  # sin fichero: None normal


def test_cik_numerico_sigue_leyendo(tmp_path):
    root = _root(tmp_path)
    destino = root / "submissions" / "CIK0001234567.json"
    destino.write_text(json.dumps({"ok": True}), encoding="utf-8")
    assert edgartools_client.read_submissions("1234567", root) == {"ok": True}
    assert edgartools_client.read_submissions("0001234567", root) == {"ok": True}


def test_filing_xml_rechaza_traversal(tmp_path):
    root = _root(tmp_path)
    (tmp_path / "filings" / "00012345670001").mkdir()
    (tmp_path / "filings" / "00012345670001" / "form4.xml").write_text("<ok/>", encoding="utf-8")
    # Marcas alcanzables solo con traversal: demuestran el acceso en rojo.
    (root / "filings" / "manifest.json").write_text("<manifest/>", encoding="utf-8")
    (root / "form4.xml").write_text("<root/>", encoding="utf-8")
    assert edgartools_client.read_filing_xml("0001234567-00-01", "form4.xml", root) == "<ok/>"
    assert edgartools_client.read_filing_xml("0001234567-00-01", "../manifest.json", root) is None
    assert edgartools_client.read_filing_xml("0001234567-00-01", "..\\manifest.json", root) is None
    assert edgartools_client.read_filing_xml("0001234567-00-01", "../../etc/passwd", root) is None
    assert edgartools_client.read_filing_xml("..", "form4.xml", root) is None


def test_information_table_malformado_no_filtra_excepcion():
    accession = _thirteenf_filings_from_submissions(SUBMISSIONS, limit=8)[0]["accession_number"]
    out = refresh_13f_from_edgartools(
        "0001234567",
        force=True,
        submissions=SUBMISSIONS,
        infotable_xml={accession: "<broken><xml"},
    )
    assert out["errors"], "el XML roto debia producir una entrada de error"
    for entry in out["errors"]:
        texto = json.dumps(entry)
        assert "ParseError" not in texto
        assert "<broken>" not in texto
        assert entry["error"] == "information_table_parse_error"


def test_filing_xml_rechaza_symlinks(tmp_path):
    root = _root(tmp_path)
    fuera = tmp_path.parent / f"{tmp_path.name}_fuera"
    fuera.mkdir()
    (fuera / "externo.xml").write_text("<externo/>", encoding="utf-8")
    dir_fuera = fuera / "dir_externo"
    dir_fuera.mkdir()
    (dir_fuera / "form4.xml").write_text("<externo_dir/>", encoding="utf-8")
    (root / "filings" / "00012345670001").mkdir()
    # Symlink de FICHERO dentro del snapshot apuntando fuera.
    (root / "filings" / "00012345670001" / "form4.xml").symlink_to(fuera / "externo.xml")
    assert edgartools_client.read_filing_xml("0001234567-00-01", "form4.xml", root) is None
    # Symlink de DIRECTORIO: la carpeta del accession apunta fuera.
    (root / "filings" / "00012345670002").symlink_to(dir_fuera, target_is_directory=True)
    assert edgartools_client.read_filing_xml("0001234567-00-02", "form4.xml", root) is None


def test_json_symlink_fuera_del_root_rechazado(tmp_path):
    root = _root(tmp_path)
    fuera = tmp_path.parent / f"{tmp_path.name}_fuera2.json"
    fuera.write_text(json.dumps({"externo": True}), encoding="utf-8")
    (root / "submissions" / "CIK0001234567.json").symlink_to(fuera)
    assert edgartools_client.read_submissions("1234567", root) is None
    (root / "manifest.json").symlink_to(fuera)
    assert edgartools_client.read_manifest(root) is None


def test_filing_xml_filename_vacio_rechazado(tmp_path):
    root = _root(tmp_path)
    assert edgartools_client.read_filing_xml("0001234567-00-01", "", root) is None


def test_filings_entero_symlink_externo_rechazado(tmp_path):
    """Si ``filings`` es un symlink a un dir externo, su destino NO es raiz
    autorizada: la lectura debe rechazarse (escape reproducido en review)."""
    root = _root(tmp_path)
    (root / "filings").rmdir()
    externo = tmp_path.parent / f"{tmp_path.name}_filings_externo"
    (externo / "00012345670001").mkdir(parents=True)
    (externo / "00012345670001" / "safe.xml").write_text("<ajeno/>", encoding="utf-8")
    (root / "filings").symlink_to(externo, target_is_directory=True)
    assert edgartools_client.read_filing_xml("0001234567-00-01", "safe.xml", root) is None


def test_filings_real_dentro_del_root_sigue_leyendo(tmp_path):
    root = _root(tmp_path)
    (root / "filings" / "00012345670001").mkdir()
    (root / "filings" / "00012345670001" / "form4.xml").write_text("<ok/>", encoding="utf-8")
    assert edgartools_client.read_filing_xml("0001234567-00-01", "form4.xml", root) == "<ok/>"


def test_filing_xml_directorio_o_fifo_devuelve_none(tmp_path):
    """Un 'filename' que existe pero es directorio o FIFO no es un fichero:
    None limpio, sin IsADirectoryError ni bloqueo de apertura."""
    import os
    import stat as stat_mod

    root = _root(tmp_path)
    folder = root / "filings" / "00012345670001"
    folder.mkdir()
    (folder / "folder.xml").mkdir()  # directorio con nombre de fichero
    assert edgartools_client.read_filing_xml("0001234567-00-01", "folder.xml", root) is None
    os.mkfifo(folder / "pipe.xml")  # FIFO: sin O_NONBLOCK la apertura bloquea
    assert stat_mod.S_ISFIFO(os.stat(folder / "pipe.xml").st_mode)
    assert edgartools_client.read_filing_xml("0001234567-00-01", "pipe.xml", root) is None


def test_json_directorio_en_lugar_de_fichero_devuelve_none(tmp_path):
    root = _root(tmp_path)
    (root / "submissions" / "CIK0001234567.json").mkdir()  # dir con nombre de JSON
    assert edgartools_client.read_submissions("1234567", root) is None
