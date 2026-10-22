"""Cobertura dinamica desde BD (tenant) + job store. Datos SINTETICOS (tickers ficticios y reales
solo como identificadores; sin importes ni escrituras reales)."""
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, Position, WatchItem
from app.services.commitment_coverage import coverage_report, dynamic_universe
from app.services.commitment_source_check_job import JsonSourceCheckStore, SourceCheckRecord


def _co(db, t):
    c = Company(ticker=t, name=t, exchange="NYSE", currency="USD", sector="S", industry="I",
                company_type="holding", valuation_model="unassigned", special_sources=[],
                special_risks=[], factor_tags=[])
    db.add(c)
    db.commit()
    return c


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        s.info["tenant_id"] = "tenant-test"
        yield s


def test_universe_from_db_is_union_and_ignores_closed_positions(db):
    uber, bn, cl = _co(db, "UBER"), _co(db, "BN"), _co(db, "CLOSED")
    db.add_all([Position(company_id=uber.id, quantity=Decimal("1"), as_of=date(2030, 1, 1)),
                Position(company_id=cl.id, quantity=Decimal("0"), as_of=date(2030, 1, 1))])
    db.add(WatchItem(symbol="bn"))
    db.add(WatchItem(symbol="ZZZ"))
    db.commit()
    universe, flags = dynamic_universe(db)
    assert universe == ("BN", "UBER", "ZZZ")
    assert flags["UBER"] == (True, False) and flags["BN"] == (False, True)


def test_empty_db_gives_empty_universe_not_snapshot(db, tmp_path):
    rep = coverage_report(db, JsonSourceCheckStore(tmp_path / "s"))
    assert rep["universe_size"] == 0 and rep["companies"] == []
    assert rep["universe_source"] == "bd_tenant"


def test_report_links_real_store_and_marks_unresolved(db, tmp_path):
    uber = _co(db, "UBER")
    db.add(Position(company_id=uber.id, quantity=Decimal("1"), as_of=date(2030, 1, 1)))
    db.add(WatchItem(symbol="AAPL"))
    db.commit()
    store = JsonSourceCheckStore(tmp_path / "s")
    store.save([SourceCheckRecord(ticker="UBER", url="https://x.invalid/a", kind="transcript",
                                  period="Q2 2026", checked_on="2026-10-22",
                                  outcome="extraido", reason="texto_obtenido",
                                  content_sha256="a" * 64)])
    rep = coverage_report(db, store)
    rows = {r["ticker"]: r for r in rep["companies"]}
    assert rows["UBER"]["state"] == "fuente_obtenida" and rows["UBER"]["in_portfolio"]
    assert rows["AAPL"]["state"] == "sin_chequeo_posible" and rows["AAPL"]["in_watchlist"]
    assert all(r["universe_static_snapshot"] is False for r in rows.values())
    assert rep["history"]


def _seed(db, tmp_path):
    uber = _co(db, "uber")
    db.add(Position(company_id=uber.id, quantity=Decimal("1"), as_of=date(2030, 1, 1)))
    db.add_all([WatchItem(symbol=" bn "), ])
    db.commit()
    store = JsonSourceCheckStore(tmp_path / "s")
    rec = lambda t, u: SourceCheckRecord(  # noqa: E731
        ticker=t, url=u, kind="transcript", period="Q2 2026", checked_on="2026-10-22",
        outcome="extraido", reason="texto_obtenido", content_sha256="b" * 64)
    store.save([rec("UBER", "https://x.invalid/u"), rec("OTHER", "https://x.invalid/o")])
    return store


def test_normalized_and_history_filtered_to_universe(db, tmp_path):
    store = _seed(db, tmp_path)
    rep = coverage_report(db, store)
    assert [r["ticker"] for r in rep["companies"]] == ["BN", "UBER"]
    assert {h["ticker"] for h in rep["history"]} == {"UBER"}


def test_get_never_quarantines_and_recovers_from_history(db, tmp_path):
    store = _seed(db, tmp_path)
    (store.dir / "latest.json").write_text('{"truncated": ')
    fresh = JsonSourceCheckStore(tmp_path / "s")
    rep = coverage_report(db, fresh)
    assert (store.dir / "latest.json").exists()  # NO se movio: GET no escribe
    assert not list(store.dir.glob("latest.json.corrupt-*"))
    assert rep["store"]["latest"] == "corrupto" and rep["store"]["recovered_from_history"]
    rows = {r["ticker"]: r for r in rep["companies"]}
    assert rows["UBER"]["state"] == "fuente_obtenida"  # recuperado del historial
    assert coverage_report(db, fresh)["store"]["latest"] == "corrupto"  # persistente entre GET


def test_incident_persists_after_job_quarantine(db, tmp_path):
    store = _seed(db, tmp_path)
    (store.dir / "latest.json").write_text("{bad")
    JsonSourceCheckStore(tmp_path / "s").load()  # camino de escritura (job): cuarentena
    rep = coverage_report(db, JsonSourceCheckStore(tmp_path / "s"))
    assert rep["store"]["incident"]["file"].startswith("latest.json.corrupt-")
    assert rep["store"]["latest"] == "ausente" and rep["store"]["recovered_from_history"]


def test_unreadable_store_does_not_raise(db, tmp_path):
    store = _seed(db, tmp_path)
    (store.dir / "latest.json").unlink()
    (store.dir / "latest.json").mkdir()  # ilegible (OSError al leer)
    (store.dir / "history.jsonl").unlink()
    rep = coverage_report(db, JsonSourceCheckStore(tmp_path / "s"))
    assert rep["store"]["latest"] == "ilegible"
    assert all(r["state"] in {"estado_del_almacen_no_fiable", "sin_chequeo_posible"}
               for r in rep["companies"])


def test_relative_store_dir_is_anchored_not_cwd(monkeypatch, tmp_path):
    from app.services.commitment_source_check_job import resolve_store_dir
    a = resolve_store_dir("./storage/source_checks")
    monkeypatch.chdir(tmp_path)
    assert resolve_store_dir("./storage/source_checks") == a and a.is_absolute()


def test_first_run_is_normal_not_failure(db, tmp_path):
    _co(db, "UBER")
    db.add(WatchItem(symbol="UBER"))
    db.commit()
    rep = coverage_report(db, JsonSourceCheckStore(tmp_path / "nuevo"))
    assert rep["store"]["first_run"] is True
    assert {r["state"] for r in rep["companies"]} == {"sin_ejecuciones_aun"}


def test_partial_latest_after_quarantine_completes_from_history_keeping_outcome(db, tmp_path):
    store = _seed(db, tmp_path)
    err = SourceCheckRecord(ticker="BN", url="https://x.invalid/bn", kind="transcript",
                            period="Q2 2026", checked_on="2026-10-22", outcome="error",
                            reason="TimeoutError")
    store.save([err])
    data = store.load()
    (store.dir / "latest.json").write_text(
        __import__("json").dumps({"https://x.invalid/u": data["https://x.invalid/u"]}))
    rep = coverage_report(db, JsonSourceCheckStore(tmp_path / "s"))
    rows = {r["ticker"]: r for r in rep["companies"]}
    assert rows["BN"]["state"] == "ultimo_chequeo_con_error"  # no "nunca_chequeado", no "ok"
    assert rows["BN"]["from_history"] is True and rows["UBER"]["from_history"] is False
    assert rep["store"]["recovered_urls"] == 2


def test_incident_labeled_historical_after_healing(db, tmp_path):
    store = _seed(db, tmp_path)
    (store.dir / "latest.json").write_text("{bad")
    JsonSourceCheckStore(tmp_path / "s").load()
    assert coverage_report(db, JsonSourceCheckStore(tmp_path / "s"))["store"]["incident"][
        "status"] == "activo_o_sin_sanar"
    healed = JsonSourceCheckStore(tmp_path / "s")
    healed.save([SourceCheckRecord(ticker="UBER", url="https://x.invalid/u", kind="transcript",
                                   period="Q2 2026", checked_on="2026-10-23", outcome="extraido",
                                   reason="texto_obtenido", content_sha256="c" * 64),
                 SourceCheckRecord(ticker="OTHER", url="https://x.invalid/o", kind="transcript",
                                   period="Q2 2026", checked_on="2026-10-23", outcome="extraido",
                                   reason="texto_obtenido", content_sha256="c" * 64)])
    st = coverage_report(db, JsonSourceCheckStore(tmp_path / "s"))["store"]
    assert st["incident"]["status"] == "historico_sanado" and st["latest"] == "ok"


def test_eviction_is_retention_not_recovery_and_does_not_flag_incident(db, tmp_path):
    from app.services import commitment_source_check_job as mod

    uber = _co(db, "UBER")
    db.add(Position(company_id=uber.id, quantity=Decimal("1"), as_of=date(2030, 1, 1)))
    db.commit()
    store = JsonSourceCheckStore(tmp_path / "s")
    recs = [SourceCheckRecord(ticker="UBER" if i == 0 else f"T{i}", url=f"https://x.invalid/{i}",
                              kind="transcript", period="Q2 2026",
                              checked_on=f"2026-01-{(i % 28) + 1:02d}" if i else "2026-10-22",
                              outcome="extraido", reason="texto_obtenido",
                              content_sha256="d" * 64) for i in range(mod.MAX_RECORDS + 5)]
    store.save(recs)
    assert len(store.load()) == mod.MAX_RECORDS
    rep = coverage_report(db, JsonSourceCheckStore(tmp_path / "s"))
    assert rep["store"]["recovered_urls"] == 0 and not rep["store"]["recovered_from_history"]
    assert rep["store"]["incident"] is None
    assert rep["companies"][0]["state"] == "fuente_obtenida"
    assert rep["companies"][0]["last_checked_on"] == "2026-10-22"


def test_evicted_ticker_is_out_of_retention_not_never_checked(db, tmp_path):
    from app.services import commitment_source_check_job as mod

    _co(db, "BN")
    db.add(WatchItem(symbol="BN"))
    db.commit()
    store = JsonSourceCheckStore(tmp_path / "s")
    old = SourceCheckRecord(ticker="BN", url="https://x.invalid/z", kind="transcript",
                            period="Q2 2026", checked_on="2025-01-01", outcome="extraido",
                            reason="texto_obtenido", content_sha256="e" * 64)
    fill = [SourceCheckRecord(ticker=f"T{i}", url=f"https://x.invalid/{i}", kind="transcript",
                              period="Q2 2026", checked_on="2026-10-22", outcome="extraido",
                              reason="texto_obtenido", content_sha256="e" * 64)
            for i in range(mod.MAX_RECORDS)]
    store.save([old, *fill])
    rep = coverage_report(db, JsonSourceCheckStore(tmp_path / "s"))
    assert rep["companies"][0]["state"] == "estado_fuera_retencion"
    assert "BN" in rep["store"]["evicted_tickers"] and rep["store"]["at_retention_cap"]


def test_record_carries_origin_and_format(tmp_path):
    store = JsonSourceCheckStore(tmp_path / "s")
    store.save([SourceCheckRecord(ticker="KKR", url="https://x.invalid/k", kind="transcript",
                                  period="Q2 2026", checked_on="2026-10-22", outcome="extraido",
                                  reason="texto_obtenido", content_sha256="f" * 64,
                                  origin="url_dominio_oficial_por_busqueda", format="pdf")])
    item = store.read_history(limit=1)[0]
    assert item["origin"] == "url_dominio_oficial_por_busqueda" and item["format"] == "pdf"


def test_management_commitments_covers_union_without_amounts(db):
    from app.api.routes.portfolio import management_commitments

    held, only_watch, closed = _co(db, "UBER"), _co(db, "KKR"), _co(db, "OLD")
    db.add_all([Position(company_id=held.id, quantity=Decimal("5"), as_of=date(2030, 1, 1)),
                Position(company_id=closed.id, quantity=Decimal("0"), as_of=date(2030, 1, 1))])
    db.add_all([WatchItem(symbol="kkr"), WatchItem(symbol="NOCO"), WatchItem(symbol="UBER")])
    db.commit()
    assert only_watch.id
    data = management_commitments(db)
    rows = {c["ticker"]: c for c in data["companies"]}
    assert set(rows) == {"UBER", "KKR", "NOCO"}  # OLD (posicion cerrada) fuera
    assert rows["UBER"]["in_portfolio"] and rows["UBER"]["in_watchlist"]
    assert rows["KKR"]["in_watchlist"] and not rows["KKR"]["in_portfolio"]
    assert rows["NOCO"]["company_in_db"] is False and rows["NOCO"]["counts"]["total"] == 0
    assert data["universe_count"] == 3 and data["held_count"] == 1 and data["watchlist_count"] == 3
    blob = str(data)
    assert "quantity" not in blob and "5" not in {k for c in data["companies"] for k in c}


def test_company_identity_is_deterministic_trimmed_and_ambiguity_not_guessed(db):
    from app.api.routes.portfolio import management_commitments

    _co(db, "UBER")
    _co(db, " kkr ")        # unica coincidencia normalizada: se usa
    _co(db, "abc")          # dos candidatas no canonicas: ambigua
    _co(db, "ABC ")
    db.add_all([WatchItem(symbol=" uber "), WatchItem(symbol="KKR"), WatchItem(symbol="ABC")])
    db.commit()
    rows = {c["ticker"]: c for c in management_commitments(db)["companies"]}
    assert rows["UBER"]["company_in_db"] and not rows["UBER"]["company_identity_ambiguous"]
    assert rows["KKR"]["company_in_db"] and rows["KKR"]["name"] == " kkr "
    assert rows["ABC"]["company_in_db"] is False and rows["ABC"]["company_identity_ambiguous"]


def test_held_company_identity_is_position_company_id_not_canonical_name(db):
    from app.api.routes.portfolio import management_commitments
    from app.models.entities import ManagementPromise

    owned = _co(db, " uber ")   # la que tiene la posicion real
    canon = _co(db, "UBER")     # canonica ajena, no poseida
    db.add(Position(company_id=owned.id, quantity=Decimal("2"), as_of=date(2030, 1, 1)))
    db.commit()
    for comp, text in ((owned, "promesa de la poseida"), (canon, "promesa ajena")):
        db.add(ManagementPromise(company_id=comp.id, promise=text, status="candidate",
                                 promise_date=date(2030, 1, 1), expected_period="FY2030"))
    db.commit()
    row = management_commitments(db)["companies"][0]
    assert row["ticker"] == "UBER" and row["name"] == " uber "
    assert [i["promise"] for i in row["items"]] == ["promesa de la poseida"]


def test_two_held_companies_same_normalized_ticker_is_ambiguous(db):
    from app.api.routes.portfolio import management_commitments

    a, b = _co(db, "kkr"), _co(db, "KKR ")
    db.add_all([Position(company_id=a.id, quantity=Decimal("1"), as_of=date(2030, 1, 1)),
                Position(company_id=b.id, quantity=Decimal("1"), as_of=date(2030, 1, 1))])
    db.commit()
    row = management_commitments(db)["companies"][0]
    assert row["company_identity_ambiguous"] and not row["company_in_db"] and row["items"] == []
