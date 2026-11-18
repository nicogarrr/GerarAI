from app.valuation.engines.sector_specific import _cap_warnings, _capped_pb, _pb_sensitivity_rows


def test_pb_cap_is_recorded_not_hidden():
    caps: list[dict] = []
    assert _capped_pb("bull", 5.0, caps) == 3.0
    assert _capped_pb("bear", 0.1, caps) == 0.25
    assert _capped_pb("base", 1.4, caps) == 1.4
    assert [(c["scenario"], c["bound"]) for c in caps] == [("bull", "ceiling"), ("bear", "floor")]
    warnings = _cap_warnings(caps)
    assert [w["code"] for w in warnings] == ["pb_cap_applied", "pb_cap_applied"]
    assert "5,00x" in warnings[0]["detail"] and "techo" in warnings[0]["detail"]
    assert "suelo" in warnings[1]["detail"]


def test_no_cap_no_warning():
    caps: list[dict] = []
    _capped_pb("base", 1.8, caps)
    assert caps == [] and _cap_warnings(caps) == []


def test_sensitivity_flags_capped_rows():
    rows = _pb_sensitivity_rows(book_per_share=10, roe=0.40, cost_of_equity=0.10, growth=0.03)["rows"]
    assert all("pb_cap_applied" in r for r in rows)
    assert rows[0]["pb_cap_applied"] is True and rows[0]["justified_pb"] == 3.0


def test_reit_nav_floor_and_cap_rate_floor_are_warned():
    from app.valuation.engines.sector_specific import reit_nav_warnings

    specs = {"bear": (100.0, 0.08), "base": (200.0, 0.06), "bull": (212.0, 0.001)}
    codes = [(w["code"], w["scenario"]) for w in reit_nav_warnings(specs, 5000.0, 0.005)]
    assert ("nav_floored_at_zero", "bear") in codes and ("nav_floored_at_zero", "base") in codes
    assert ("nav_floored_at_zero", "bull") not in codes
    assert ("cap_rate_floor_applied", "bull") in codes
    assert reit_nav_warnings({"base": (200.0, 0.05)}, 100.0, 0.05) == []


def test_spanish_number_format():
    from app.valuation.engines.sector_specific import _es

    assert _es(1234567.891, 0) == "1.234.568"
    assert _es(-5000.0, 0) == "-5.000"
    assert _es(5.0) == "5,00"
    assert _es(-0.4, 0) == "0"
    assert _es(-0.001) == "0,00"
