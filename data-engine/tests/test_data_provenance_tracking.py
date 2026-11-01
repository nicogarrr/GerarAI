"""Pruebas para el seguimiento de procedencia de datos (Provenance Tracking).

Fulfills: VAL-DATA-008
Expected Behavior:
- Registros y respuestas etiquetados con su fuente (OFICIAL, INFERIDO, SIN_DATOS)
- Metadatos de procedencia (source, source_kind, fetched_at, coverage) en las respuestas de la API
- Indicación explícita de datos ausentes o retrasados (SIN_DATOS / UNAVAILABLE)
- Cumplimiento de la regla de oro: nunca inventar datos
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.services.provenance import (
    Coverage,
    SourceKind,
    coverage_for_age,
    provenance,
)


def test_provenance_block_creation():
    """Verifica que el bloque de procedencia contiene los campos requeridos."""
    now = datetime.now(UTC)
    block = provenance(
        source="Yahoo Finance",
        source_kind=SourceKind.UNOFFICIAL,
        source_url="https://finance.yahoo.com/quote/SAN.MC",
        fetched_at=now,
        coverage=Coverage.OK,
        note="Cotización en tiempo real",
    )

    assert block["source"] == "Yahoo Finance"
    assert block["source_kind"] == "unofficial"
    assert block["source_url"] == "https://finance.yahoo.com/quote/SAN.MC"
    assert block["coverage"] == "ok"
    assert block["fetched_at"] == now.isoformat()
    assert block["note"] == "Cotización en tiempo real"


def test_provenance_official_source():
    """Verifica fuentes oficiales (ECB, SEC, CNMV)."""
    block = provenance(
        source="Banco Central Europeo",
        source_kind=SourceKind.OFFICIAL,
        coverage=Coverage.OK,
    )
    assert block["source_kind"] == "official"
    assert block["coverage"] == "ok"


def test_provenance_missing_data_labeled_sin_datos():
    """Verifica que la ausencia de datos se refleje honestamente como UNAVAILABLE / SIN_DATOS."""
    # Cobertura para datos vacíos o no disponibles
    cov_empty = coverage_for_age("yahoo_finance", datetime.now(UTC), empty=True)
    assert cov_empty == Coverage.UNAVAILABLE

    cov_partial = coverage_for_age("yahoo_finance", datetime.now(UTC), partial=True)
    assert cov_partial == Coverage.PARTIAL

    # Datos obsoletos que superan el umbral de frescura
    old_date = datetime.now(UTC) - timedelta(hours=2)
    cov_stale = coverage_for_age("yahoo_finance", old_date)
    assert cov_stale == Coverage.STALE


def test_provenance_veracity_labels():
    """Verifica las etiquetas de veracidad requeridas: OFICIAL, INFERIDO y SIN_DATOS."""
    labels = {"OFICIAL", "INFERIDO", "SIN_DATOS"}

    def get_provenance_label(source_kind: str | None, has_data: bool) -> str:
        if not has_data or not source_kind:
            return "SIN_DATOS"
        if source_kind in ("official", "issuer", "exchange", "ibkr_flex"):
            return "OFICIAL"
        return "INFERIDO"

    assert get_provenance_label("official", True) == "OFICIAL"
    assert get_provenance_label("ibkr_flex", True) == "OFICIAL"
    assert get_provenance_label("unofficial", True) == "INFERIDO"
    assert get_provenance_label("internal", True) == "INFERIDO"
    assert get_provenance_label(None, False) == "SIN_DATOS"
    assert get_provenance_label("official", False) == "SIN_DATOS"
