from app.services.commitment_coverage import UNIVERSE, coverage_for, universe_coverage


def test_universe_is_union_of_20_unique():
    assert len(UNIVERSE) == 20 and len(set(UNIVERSE)) == 20


def test_uber_checkable_and_unresolved_abstain():
    u = coverage_for("UBER")
    assert u.checkable_by_job and u.press_release_registered and u.transcript_assets_with_call_date == 1
    a = coverage_for("AAPL")
    assert not a.checkable_by_job and a.transcript_status == "sin_fuente_resuelta"
    assert "resolver_fuente_oficial_de_transcripcion" in a.pending


def test_bn_has_asset_but_no_date_not_checkable():
    b = coverage_for("BN")
    assert b.transcript_assets == 1 and not b.checkable_by_job
    assert "leer_fecha_de_llamada_del_documento" in b.pending


def test_every_ticker_reports_honest_pending():
    rows = universe_coverage()
    assert all(r.pending or r.checkable_by_job for r in rows)
    assert sum(r.checkable_by_job for r in rows) == 1
