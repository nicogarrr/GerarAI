from app.services.commitment_coverage import UNIVERSE, coverage_for, universe_coverage


def test_universe_is_union_of_20_unique():
    assert len(UNIVERSE) == 20 and len(set(UNIVERSE)) == 20


def test_uber_checkable_and_unresolved_abstain():
    u = coverage_for("UBER")
    assert u.checkable_by_job and u.press_release_registered and u.transcript_assets_with_call_date == 1
    a = coverage_for("AAPL")
    assert not a.checkable_by_job and a.transcript_status == "no_listada_en_pagina_ir"
    assert "sin_activo_de_transcripcion_verificado" in a.pending
    z = coverage_for("NOEXISTE")
    assert z.transcript_status == "sin_fuente_resuelta"
    assert "resolver_fuente_oficial_de_transcripcion" in z.pending


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
    assert sum(r.checkable_by_job for r in rows) == 5


def test_checkable_flag_matches_real_job_targets():
    from app.services.commitment_source_check_job import job_target_tickers
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


def test_explicit_empty_universe_stays_empty():
    from app.services.commitment_coverage import coverage_with_checks
    assert universe_coverage(()) == [] and coverage_with_checks({}, ()) == []


def test_kkr_registered_with_honest_origin_and_checkable():
    from app.services.transcript_source_registry import get_entry
    k = get_entry("KKR").assets[0]
    assert k.origin == "url_dominio_oficial_por_busqueda" and k.call_date == "2026-07-30"
    c = coverage_for("KKR")
    assert c.checkable_by_job and c.transcript_assets_with_call_date == 1


def test_origins_reach_coverage_and_cb_is_ir_href():
    assert coverage_for("KKR").transcript_origins == ("url_dominio_oficial_por_busqueda",)
    assert coverage_for("CB").transcript_origins == ("href_ir_leido",)
    assert coverage_for("CB").checkable_by_job
    from app.services.commitment_coverage import coverage_with_checks
    assert coverage_with_checks({}, ("KKR",))[0]["transcript_origins"] == [
        "url_dominio_oficial_por_busqueda"]


def test_sources_with_urls_exposed_from_registry_only():
    from app.services.commitment_coverage import coverage_with_checks
    row = {r["ticker"]: r for r in coverage_with_checks({}, ("RXRX", "UBER", "AAPL"))}
    rx = row["RXRX"]["transcript_sources"][0]
    assert rx["format"] == "html" and rx["url"].startswith("https://www.recursion.com/")
    assert row["UBER"]["press_release_sources"][0]["url"].startswith("https://www.sec.gov/")
    assert row["AAPL"]["transcript_sources"] == [] and row["AAPL"]["press_release_sources"] == []


def test_rxrx_call_date_provenance_is_press_release_not_document():
    from app.services.commitment_coverage import coverage_with_checks
    src = coverage_with_checks({}, ("RXRX",))[0]["transcript_sources"][0]
    assert src["call_date_source"].startswith("https://ir.recursion.com/news-releases/")
    assert coverage_with_checks({}, ("KKR",))[0]["transcript_sources"][0][
        "call_date_source"] == "documento"


def test_consulted_pages_are_not_listed_not_unresolved():
    for t in ("CPT", "AAPL", "IBRX", "CGEO.L"):
        c = coverage_for(t)
        assert c.transcript_status == "no_listada_en_pagina_ir" and not c.checkable_by_job


def test_labels_are_user_friendly_origin_stays_in_metadata():
    for t in ("KKR", "RXRX", "CB"):
        src = coverage_for(t).transcript_sources[0]
        assert "resultado de busqueda" not in src["label"] and src["origin"]
