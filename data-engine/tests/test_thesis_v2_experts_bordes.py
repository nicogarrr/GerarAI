"""Bordes de serialización, fuentes y marcadores del equipo de expertos."""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models import DeclaredInputValue, Tenant
from app.models.entities import Base, Company
from app.services.expert_team import thesis_v2_experts as svc
from app.services.value_driver_service import ValueDriverService


def test_jsonable_y_fingerprint_ignoran_claves_privadas():
    class Other:
        def __str__(self):
            return "other"

    data = {
        "_private": "secret",
        3: (Decimal("1.25"), date(2026, 1, 2), Other()),
        "set": {"only"},
        "frozen": frozenset(["one"]),
    }
    assert svc._jsonable(data) == {"3": [1.25, "2026-01-02", "other"], "set": ["only"], "frozen": ["one"]}
    assert svc.block_fingerprint({"x": 1, "_private": 9}) == svc.block_fingerprint({"x": 1})
    assert svc.block_fingerprint({"x": 2}) != svc.block_fingerprint({"x": 1})


def test_pipeline_invalido_y_version_reemplazada():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            db.add(Tenant(id=1, external_id="expert-borders"))
            db.flush()
            db.info["tenant_id"] = 1
            c = Company(
                ticker="EXPERTTEST",
                name="Test",
                exchange="TEST",
                currency="USD",
                company_type="operating",
                valuation_model="unassigned",
            )
            db.add(c)
            db.flush()
            assert svc.store_pipeline(db, c.id, None) is False
            assert svc.store_pipeline(db, c.id, {"stages": []}) is False
            assert svc.store_pipeline(db, c.id, {"stages": [{"name": "one"}]}, today=date(2026, 1, 1)) is True
            assert svc.store_pipeline(db, c.id, {"stages": [{"name": "two"}]}, today=date(2026, 1, 2)) is True
            rows = db.scalars(select(DeclaredInputValue).order_by(DeclaredInputValue.id)).all()
            assert len(rows) == 2
            assert rows[0].superseded_at is not None and rows[1].superseded_at is None
            assert rows[1].metadata_["stages"] == [{"name": "two"}]
            assert rows[1].as_of == date(2026, 1, 2)
    finally:
        engine.dispose()


def test_drivers_sin_tenant_error_y_con_fuentes(monkeypatch):
    assert svc._drivers(None, 1, None) == []
    assert svc._drivers(None, 1, True) == []

    def broken(self, *args, **kwargs):
        raise RuntimeError("unavailable")

    monkeypatch.setattr(ValueDriverService, "current", broken)
    assert svc._drivers(None, 1, 1) == []
    row = SimpleNamespace(
        driver_key="d",
        name="Driver",
        category="growth",
        status="open",
        treatment="none",
        timing="2027",
        source_url="https://example.test/source",
        source_quote="q" * 700,
        reason_if_not_valued="no contract",
    )
    monkeypatch.setattr(ValueDriverService, "current", lambda *args, **kwargs: {"d": row})
    assert svc._drivers(None, 1, 1) == [
        {
            "clave": "d",
            "nombre": "Driver",
            "categoria": "growth",
            "estado": "open",
            "tratamiento": "none",
            "plazo": "2027",
            "fuente": "https://example.test/source",
            "cita": "q" * 600,
            "por_que_no_se_valora": "no contract",
        }
    ]


def test_block_vacio_y_payload_fallback(monkeypatch):
    monkeypatch.setattr(svc, "_latest", lambda db, cid: None)
    monkeypatch.setattr(svc, "_drivers", lambda *args: [])
    monkeypatch.setattr(svc, "_analyst_inputs", lambda *args: [])
    assert svc.expert_block(None, SimpleNamespace(id=1), 1) is None
    assert "no dejó inventario" in svc.expert_payload(None)
    assert svc.expert_markers(None) == {}


def test_marcadores_rango_payload_y_tabla_huerfana():
    a = {
        "input": "x",
        "firma": "Firm",
        "base": -2,
        "bajo": None,
        "alto": None,
        "unidad": "USD",
        "fuente": "u",
        "cita": "quote",
        "fecha": None,
    }
    b = {**a, "base": 3, "bajo": 2, "alto": 4, "unidad": "multiple"}
    block = {
        "supuestos_de_analistas": [a, b],
        "esceptico": [
            {
                "driver_key": "orphan",
                "hace_falta_creer": "belief",
                "postura": "open",
                "dato_que_lo_cierra": "evidence",
                "fuente": "source",
            }
        ],
    }
    markers = svc.expert_markers(block)
    assert markers == {
        "expertos.analista.1.valor": "−2,00 USD",
        "expertos.analista.2.valor": "3,0x",
        "expertos.analista.2.rango": "2,0x–4,0x",
    }
    payload = svc.expert_payload(block)
    assert payload["supuestos_de_analistas"][1]["rango"] == "{{expertos.analista.2.rango}}"
    assert "base" not in payload["supuestos_de_analistas"][1]
    table = svc.experts_table(block)
    assert table["rows"] == [["orphan", "", "belief", "open", "evidence"]]
    assert table["links"] == ["source"]
    assert svc._fmt(None, None) == "N/D"
    assert svc._fmt(1, None) == "1,00"
