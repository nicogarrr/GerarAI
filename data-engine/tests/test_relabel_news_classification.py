"""Script de reetiquetado historico de NewsEvent: logica pura + end-to-end."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.core.database import SessionLocal, init_db
from app.models import Company, NewsEvent
from scripts.relabel_news_classification import (
    _plan_row,
    _recompute,
    main,
)

# ---------- logica pura ----------

def test_recompute_insignia_vigente():
    # Selloff contestado: la opinion sobre una venta excesiva ya no afirma
    # deterioro (regla contested-selloff); sin otra senal negativa -> neutral.
    assert _recompute(
        "ASTS sell-off may have punished the stock beyond fundamentals", ""
    ) == {"event_type": "general_news", "impact_direction": "neutral"}
    assert _recompute("Apple beats expectations with record revenue", "")[
        "impact_direction"
    ] == "positive"
    assert _recompute("SEEDC plunges after downgrade", "")[
        "impact_direction"
    ] == "negative"
    # Motivo: primer tipo material que casa, o general_news.
    assert _recompute("SEEDC signs contract award with DoD", "")[
        "event_type"
    ] == "contract"
    assert _recompute("SEEDC raises guidance for 2026", "")["event_type"] == "earnings"
    assert _recompute("Notas varias del sector", "")["event_type"] == "general_news"


def test_plan_row_solo_si_cambia():
    # nosemgrep: gerarai-orm-fake-simplenamespace -- _plan_row es una funcion pura que solo lee atributos; no hay consulta ORM ni gate
    stale = SimpleNamespace(
        id=1, tenant_id=None, company_id=7,
        title="Apple beats expectations with record revenue", summary="",
        event_type="general_news", impact_direction="negative",
    )
    plan = _plan_row(stale)
    assert plan is not None
    assert plan["expected"]["impact_direction"] == "negative"
    assert plan["new"]["impact_direction"] == "positive"
    # El texto base queda en expected: si cambia antes del apply, se salta.
    assert plan["expected"]["title"] == stale.title
    # Fila ya vigente: no se toca (idempotente).
    # nosemgrep: gerarai-orm-fake-simplenamespace -- _plan_row es una funcion pura que solo lee atributos; no hay consulta ORM ni gate
    fresh = SimpleNamespace(
        id=2, tenant_id=None, company_id=7,
        title="Apple beats expectations with record revenue", summary="",
        event_type="earnings", impact_direction="positive",
    )
    assert _plan_row(fresh) is None


# ---------- end-to-end con BD ----------

@pytest.fixture
def db_rows():
    init_db()
    db = SessionLocal()
    for stale in db.scalars(select(NewsEvent)).all():
        db.delete(stale)
    company = db.scalar(select(Company).where(Company.ticker == "SEEDC"))
    if company is None:
        db.add(Company(
            ticker="SEEDC", name="Seed Co", exchange="NASDAQ", currency="USD",
            sector="Technology", industry="Software", company_type="tech",
            valuation_model="standard_dcf", special_sources=[], special_risks=[], factor_tags=[],
        ))
        db.commit()
        company = db.scalar(select(Company).where(Company.ticker == "SEEDC"))
    yield db, company
    db.close()


def _add_row(db, company, title, *, direction, event_type="general_news", source="RSS"):
    row = NewsEvent(
        company_id=company.id if company else None,
        title=title,
        summary=title,
        source=source,
        event_type=event_type,
        impact_direction=direction,
    )
    db.add(row)
    db.commit()
    return row


def test_dry_run_no_escribe(db_rows, capsys):
    db, company = db_rows
    row = _add_row(db, company, "SEEDC beats expectations", direction="negative")
    assert main([]) == 0
    db.expire_all()
    assert db.get(NewsEvent, row.id).impact_direction == "negative"
    out = capsys.readouterr().out
    assert "DRY-RUN" in out and "filas a reetiquetar: 1" in out


def test_apply_reetiqueta_y_respeta_manual_e_idempotencia(db_rows, tmp_path, capsys):
    db, company = db_rows
    row = _add_row(db, company, "SEEDC beats expectations", direction="negative")
    manual = _add_row(db, company, "SEEDC beats expectations", direction="negative",
                      source="manual")
    plan = tmp_path / "plan.json"
    backup = tmp_path / "backup.json"
    assert main(["--plan", str(plan)]) == 0
    assert main(["--apply", "--plan", str(plan), "--backup", str(backup)]) == 0
    db.expire_all()
    assert db.get(NewsEvent, row.id).impact_direction == "positive"
    # La nota manual del usuario nunca se reescribe.
    assert db.get(NewsEvent, manual.id).impact_direction == "negative"
    payload = json.loads(backup.read_text(encoding="utf-8"))
    assert len(payload) == 1
    assert payload[0]["expected"]["impact_direction"] == "negative"
    assert payload[0]["new"]["impact_direction"] == "positive"
    # Backup exclusivo: un segundo apply con la misma ruta falla ANTES de la BD.
    with pytest.raises(FileExistsError):
        main(["--apply", "--plan", str(plan), "--backup", str(backup)])
    # Idempotente: un nuevo plan tras aplicar no encuentra cambios.
    capsys.readouterr()
    plan2 = tmp_path / "plan2.json"
    assert main(["--plan", str(plan2)]) == 0
    assert "filas a reetiquetar: 0" in capsys.readouterr().out


def test_apply_salta_fila_cambiada_desde_el_plan(db_rows, tmp_path):
    db, company = db_rows
    row = _add_row(db, company, "SEEDC beats expectations", direction="negative")
    plan = tmp_path / "plan.json"
    assert main(["--plan", str(plan)]) == 0
    # La fila cambia entre el preview y el apply: no se pisa.
    db.get(NewsEvent, row.id).title = "Titulo editado a mano"
    db.commit()
    assert main(["--apply", "--plan", str(plan), "--backup", str(tmp_path / "b.json")]) == 0
    db.expire_all()
    assert db.get(NewsEvent, row.id).impact_direction == "negative"


def test_rollback_restaura_con_precondicion(db_rows, tmp_path, capsys):
    db, company = db_rows
    row = _add_row(db, company, "SEEDC beats expectations", direction="negative")
    plan = tmp_path / "plan.json"
    backup = tmp_path / "backup.json"
    assert main(["--plan", str(plan)]) == 0
    assert main(["--apply", "--plan", str(plan), "--backup", str(backup)]) == 0
    # Preview del rollback: no escribe.
    assert main(["--rollback", str(backup)]) == 0
    db.expire_all()
    assert db.get(NewsEvent, row.id).impact_direction == "positive"
    assert "DRY-RUN" in capsys.readouterr().out
    assert main(["--rollback", str(backup), "--apply"]) == 0
    db.expire_all()
    assert db.get(NewsEvent, row.id).impact_direction == "negative"
    # Precondicion: una fila editada despues del plan no se restaura.
    assert main(["--apply", "--plan", str(plan), "--backup", str(tmp_path / "b2.json")]) == 0
    db.get(NewsEvent, row.id).impact_direction = "mixed"
    db.commit()
    assert main(["--rollback", str(backup), "--apply"]) == 0
    db.expire_all()
    assert db.get(NewsEvent, row.id).impact_direction == "mixed"
