from app.services.commitment_coverage import UNIVERSE, coverage_for, universe_coverage


def test_universe_is_union_of_20_unique():
    assert len(UNIVERSE) == 20 and len(set(UNIVERSE)) == 20


def test_uber_checkable_and_unresolved_abstain():
    u = coverage_for("UBER")
    assert u.checkable_by_job and u.press_release_registered and u.transcript_assets_with_call_date == 1
    a = coverage_for("AAPL")
    assert not a.checkable_by_job and a.transcript_status == "sin_fuente_resuelta"
    assert "resolver_fuente_oficial_de_transcripcion" in a.pending


def test_bn_date_read_from_document_is_checkable():
    b = coverage_for("BN")
    assert b.transcript_assets == 1 and b.transcript_assets_with_call_date == 1
    assert b.checkable_by_job and "leer_fecha_de_llamada_del_documento" not in b.pending


def test_meta_assets_without_date_not_checkable():
    m = coverage_for("META")
    assert m.transcript_assets == 2 and not m.checkable_by_job


def test_every_ticker_reports_honest_pending():
    rows = universe_coverage()
    assert all(r.pending or r.checkable_by_job for r in rows)
    assert sum(r.checkable_by_job for r in rows) == 2


def test_checkable_flag_matches_real_job_targets():
    from app.services.commitment_coverage import job_target_tickers
    assert {r.ticker for r in universe_coverage() if r.checkable_by_job} == (
        job_target_tickers() & set(UNIVERSE))


def test_coverage_with_checks_states_and_static_flag():
    from app.services.commitment_coverage import coverage_with_checks
    latest = {"u1": {"ticker": "UBER", "outcome": "extraido", "checked_on": "2026-10-22"},
              "u2": {"ticker": "UBER", "outcome": "error", "checked_on": "2026-10-22"}}
    rows = {r["ticker"]: r for r in coverage_with_checks(latest)}
    assert rows["UBER"]["state"] == "ultimo_chequeo_con_error"
    assert rows["BN"]["state"] == "nunca_chequeado"
    assert rows["AAPL"]["state"] == "sin_chequeo_posible"
    assert all(r["universe_static_snapshot"] for r in rows.values())
    ok = coverage_with_checks({"u": {"ticker": "UBER", "outcome": "extraido",
                                     "checked_on": "2026-10-22"}})
    assert {r["ticker"]: r["state"] for r in ok}["UBER"] == "fuente_obtenida"
