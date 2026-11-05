"""Notas de analista estructuradas: validación, upsert idempotente, tenant y lectura.

Feature aprobada por Nico (4-nov-2026). Caso real de su ejemplo: BofA sube el
objetivo de PLTR por la «aceleración comercial». Todo sintético salvo la forma.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import AnalystNote
from app.models.entities import Tenant
from app.services.analyst_note_service import (
    AnalystNoteError,
    AnalystNoteInput,
    analyst_note_service,
    clean_note,
    dedupe_key,
    normalize_action,
)

T1, T2 = 1, 2
SVC = analyst_note_service
URL = "https://example.com/pltr-bofa"


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all([Tenant(id=T1, external_id="t1"), Tenant(id=T2, external_id="t2")])
        session.flush()
        yield session


def _note(**kw) -> AnalystNoteInput:
    base = dict(
        ticker="pltr",
        firm="BofA Securities",
        note_date=date(2026, 11, 4),
        action="main",
        source_type="news",
        analyst="Mariana Pérez Mora",
        rating_old="Buy",
        rating_new="Buy",
        pt_old=215,
        pt_new=255,
        price_at_note="190.5",
        key_arguments=["aceleración comercial en EE. UU."],
        sentiment="positive",
        quote="commercial acceleration continues",
        source_url=URL,
    )
    base.update(kw)
    return AnalystNoteInput(**base)  # type: ignore[arg-type]


def _count(db) -> int:
    return db.scalar(select(func.count()).select_from(AnalystNote)) or 0


def test_normaliza_acciones_de_yahoo_y_texto_libre():
    assert normalize_action("up") == "upgrade"
    assert normalize_action("down") == "downgrade"
    assert normalize_action("init") == "initiate"
    assert normalize_action("reit") == "reiterate"
    assert normalize_action("main") == "maintain"
    assert normalize_action("algo raro") == "other"
    assert normalize_action(None) == "other"


def test_guarda_la_tarjeta_minima_de_nico(db):
    row, created = SVC.upsert(db, T1, _note())
    assert created
    assert row.tenant_id == T1 and row.ticker == "PLTR" and row.action == "maintain"
    assert row.pt_old == Decimal("215") and row.pt_new == Decimal("255")
    assert row.price_at_note == Decimal("190.5")
    assert row.verification == "verificado"
    assert row.key_arguments == ["aceleración comercial en EE. UU."]
    assert row.driver_refs is None  # costura para el enlace con impulsores
    assert row.dedupe_key == dedupe_key(T1, "PLTR", "BofA Securities", date(2026, 11, 4), "maintain")


def test_guarda_todo_lo_demas_que_publique_la_fuente(db):
    row, _ = SVC.upsert(
        db,
        T1,
        _note(
            estimates={"2027": {"revenue_musd": 6100, "eps": 0.82}},
            valuation={"method": "DCF", "wacc": 0.09, "terminal_growth": 0.04},
            segment_assumptions={"us_commercial_growth": 0.55},
            bull_target=320,
            bear_target=110,
            bull_case="AIP se generaliza",
            bear_case="el gasto público se frena",
            catalysts=["resultados Q4"],
            risks=["valoración exigente"],
            changes_since_previous="sube el objetivo por el comercial",
            links=["https://example.com/otra", "http://inseguro.example.com"],
            extras={"price_target_history": [180, 215, 255]},
            driver_refs=["us_commercial"],
        ),
    )
    assert row.estimates["2027"]["eps"] == 0.82
    assert row.valuation["method"] == "DCF"
    assert row.bull_target == Decimal("320") and row.bear_target == Decimal("110")
    assert row.links == ["https://example.com/otra"]  # solo https públicas
    assert row.extras == {"price_target_history": [180, 215, 255]}
    assert row.driver_refs == ["us_commercial"]


def test_upsert_idempotente_no_duplica_ni_cambia(db):
    SVC.upsert(db, T1, _note())
    row, changed = SVC.upsert(db, T1, _note())
    assert not changed
    assert _count(db) == 1
    # Firma con otro alias y ticker en minúsculas: la misma nota.
    _, changed = SVC.upsert(db, T1, _note(ticker="PLTR "))
    assert not changed and _count(db) == 1
    assert row.firm_key == row.firm.lower()


def test_una_segunda_fuente_completa_sin_borrar(db):
    SVC.upsert(
        db, T1, _note(source_type="yahoo_upgrades_downgrades", quote=None, source_url=None, key_arguments=[])
    )
    row = db.scalar(select(AnalystNote))
    assert row is not None and row.verification == "fragmento"
    row, changed = SVC.upsert(db, T1, _note(catalysts=["AIPCon"]))
    assert changed
    assert row.verification == "verificado" and row.source_type == "news" and row.quote
    assert row.key_arguments == ["aceleración comercial en EE. UU."]
    assert row.catalysts == ["AIPCon"]
    # Un fragmento posterior no degrada la verificación ni borra la cita.
    row, _ = SVC.upsert(db, T1, _note(source_type="yahoo_upgrades_downgrades", quote=None, source_url=None))
    assert row.verification == "verificado" and row.quote == "commercial acceleration continues"
    assert _count(db) == 1


def test_otra_fuente_del_mismo_rango_queda_como_enlace(db):
    SVC.upsert(db, T1, _note())
    row, changed = SVC.upsert(db, T1, _note(source_url="https://example.org/misma-nota"))
    assert changed
    assert row.source_url == URL
    assert "https://example.org/misma-nota" in row.links


def test_redes_sociales_siempre_rumor_no_verificado(db):
    row, _ = SVC.upsert(db, T1, _note(source_type="social", verification="verificado"))
    assert row.verification == "rumor_no_verificado"


@pytest.mark.parametrize(
    ("kw", "motivo"),
    [
        ({"firm": " "}, "firma"),
        ({"ticker": ""}, "ticker"),
        ({"source_type": "blog"}, "tipo de fuente"),
        ({"sentiment": "eufórico"}, "sentimiento"),
        ({"source_url": "http://example.com/x"}, "https"),
        ({"verification": "verificado", "quote": None}, "cita"),
        ({"verification": "inventada"}, "verificación"),
        ({"note_date": "2026-11-04"}, "fecha"),
    ],
)
def test_falla_cerrado_con_motivo(db, kw, motivo):
    with pytest.raises(AnalystNoteError) as err:
        SVC.upsert(db, T1, _note(**kw))
    assert motivo in str(err.value)
    assert _count(db) == 0


def test_numeros_no_validos_quedan_vacios():
    data = clean_note(_note(pt_old="n/d", pt_new=float("nan"), price_at_note=-3, bull_target=True))
    assert data["pt_old"] is None and data["pt_new"] is None
    assert data["price_at_note"] is None and data["bull_target"] is None


def test_listas_y_textos_acotados():
    data = clean_note(_note(key_arguments=[f"arg {i}" for i in range(40)], quote="x" * 10_000))
    assert len(data["key_arguments"]) == 12
    assert len(data["quote"]) == 4000


def test_tenant_obligatorio_y_aislado(db):
    for bad in (None, 0, -1, "1"):
        with pytest.raises(AnalystNoteError):
            SVC.upsert(db, bad, _note())  # type: ignore[arg-type]
    SVC.upsert(db, T1, _note())
    SVC.upsert(db, T2, _note(pt_new=999))
    assert _count(db) == 2  # misma nota, dos tenants: dos filas
    assert [n.pt_new for n in SVC.list_notes(db, T1, "PLTR")] == [Decimal("255")]
    db.info["tenant_id"] = T1
    with pytest.raises(AnalystNoteError):
        SVC.list_notes(db, T2, "PLTR")


def test_lectura_mas_reciente_primero_y_por_firma_en_orden_del_ranking(db):
    SVC.upsert(db, T1, _note(firm="BofA Securities", note_date=date(2026, 8, 5), pt_new=215))
    SVC.upsert(db, T1, _note(firm="BofA Securities", note_date=date(2026, 11, 4)))
    SVC.upsert(db, T1, _note(firm="Morgan Stanley", note_date=date(2026, 10, 1), action="up"))
    SVC.upsert(db, T1, _note(firm="Jefferies", note_date=date(2026, 10, 2), action="down"))
    SVC.upsert(db, T1, _note(ticker="TSLA", firm="Morgan Stanley"))
    notes = SVC.list_notes(db, T1, "pltr")
    assert [n.note_date for n in notes] == sorted((n.note_date for n in notes), reverse=True)
    assert len(notes) == 4
    latest = SVC.latest_by_firm(db, T1, "PLTR", ["Morgan Stanley", "BofA Securities", "Sin Notas"])
    assert [(n.firm, n.note_date) for n in latest] == [
        ("Morgan Stanley", date(2026, 10, 1)),
        ("BofA Securities", date(2026, 11, 4)),
    ]
    two = SVC.latest_by_firm(db, T1, "PLTR", ["BofA Securities"], per_firm=2)
    assert len(two) == 2
