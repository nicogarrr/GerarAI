"""Guardas de extracción e inferencia con fallos locales, sin llamadas LLM."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.services import inferred_input_llm_service
from app.services import sector_inputs as svc
from app.services.inferred_input_service import InferredInputService


@pytest.mark.parametrize(
    "meta,published,expected",
    [
        ({"period_of_report": "2024-12-31"}, None, 2024),
        ({"report_date": "bad"}, datetime(2026, 2, 1), 2025),
        ({}, datetime(2026, 9, 1), 2026),
        ({}, None, None),
    ],
)
def test_ejercicio_por_periodo_y_fecha(meta, published, expected):
    assert svc.fiscal_year_of(SimpleNamespace(metadata_=meta, published_at=published)) == expected


def test_filas_ascendentes_ratio_sin_prefijo_y_limites():
    assert svc.extract_combined_ratio("nothing") is None
    assert svc.extract_combined_ratio("Combined ratio 151 %") is None
    assert svc.extract_combined_ratio("2024 2025 Combined ratio 85 % 90 %")["value"] == 0.9
    assert svc.extract_combined_ratio("Combined ratio 85 %")["value"] == 0.85
    assert svc.extract_noi("in thousands Net operating income $0,000") is None


def test_inferencia_fallida_hace_rollback_y_explica_razon(monkeypatch):
    db = Mock()
    company = SimpleNamespace(id=1, ticker="TEST")
    monkeypatch.setattr(InferredInputService, "latest_valid", lambda *args: None)

    class QuotaError(Exception):
        reason = "quota"

    async def fail(*args, **kwargs):
        raise QuotaError("no budget")

    monkeypatch.setattr(inferred_input_llm_service, "infer_input", fail)
    assert svc.prepare_sector_inputs(db, company, {"missing_inputs": ["combined_ratio"]}) == {
        "combined_ratio": "omitido:quota"
    }
    db.rollback.assert_called_once_with()
    db.commit.assert_not_called()


def test_procedencia_ausente_en_hecho_y_documento():
    db = Mock()
    assert svc.extract_provenance(db, None) is None
    db.get.assert_not_called()
    db.get.return_value = None
    assert svc.extract_provenance(db, 1) is None
    db.get.side_effect = [SimpleNamespace(source_type=svc.EXTRACT_SOURCE_TYPE, source_id=2), None]
    assert svc.extract_provenance(db, 1) is None
