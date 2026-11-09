"""Regla caja-deuda-v1: la deuda neta del punto de partida con saldos del mismo balance (pura)."""
from app.valuation import balance_bridge as bb


def c(metric, value_m, period, source="SEC"):
    return {"metric": metric, "value": value_m * 1e6, "period": period, "source_type": source}


def test_sti_de_otro_cierre_no_se_suma():
    # CB: inversiones a corto de 2019 con la caja de 2026 (antes 3.010 + 2.835 = 5.845).
    point = {"cash_and_equivalents": c("cash_and_equivalents", 3010, "2026-09-30:Q3"),
             "short_term_investments": c("short_term_investments", 2835, "2019-09-30:Q3")}
    v, cite, warn = bb.short_term_investments(point)
    assert v == 0.0 and cite is None
    assert warn and "2019-09-30" in warn and "2026-09-30" in warn


def test_sti_del_mismo_cierre_se_suma():
    point = {"cash_and_equivalents": c("cash_and_equivalents", 120.065, "2026-06-30:Q2"),
             "short_term_investments": c("short_term_investments", 420.039, "2026-06-30:Q2")}
    v, cite, warn = bb.short_term_investments(point)
    assert abs(v - 420.039) < 1e-9 and cite is not None and warn is None


def test_sti_cero_viejo_sin_aviso():
    point = {"cash_and_equivalents": c("cash_and_equivalents", 550, "2026-09-30:Q3"),
             "short_term_investments": c("short_term_investments", 0, "2022-12-31:FY")}
    assert bb.short_term_investments(point) == (0.0, None, None)


def test_deuda_primaria_se_usa_tal_cual():
    point = {"cash_and_equivalents": c("cash_and_equivalents", 100, "2026-09-30:Q3"),
             "total_debt": c("total_debt", 1167, "2026-09-30:Q3")}
    v, cite, inside, warns = bb.financial_debt(point, ifrs=False)
    assert v == 1167 and not inside and warns == []


def test_deuda_primaria_de_otro_cierre_avisa_con_fechas():
    point = {"cash_and_equivalents": c("cash_and_equivalents", 100, "2026-09-30:Q3"),
             "total_debt": c("total_debt", 500, "2025-12-31:FY")}
    v, _, _, warns = bb.financial_debt(point, ifrs=False)
    assert v == 500 and any("2025-12-31" in w and "2026-09-30" in w for w in warns)


def test_agregador_us_gaap_resta_arrendamientos_operativos_del_mismo_cierre():
    # ABCL/NAUT: la «deuda» de Yahoo es exactamente el pasivo por arrendamiento operativo del 10-K.
    lease_fy = c("operating_lease_liabilities", 143.218, "2025-12-31:FY")
    point = {"cash_and_equivalents": c("cash_and_equivalents", 120, "2026-06-30:Q2"),
             "total_debt": c("total_debt", 143.218, "2025-12-31:FY", "YAHOO_FUNDAMENTALS"),
             # último dato del punto: comparativa de un 10-Q (solo no corriente) y de otro cierre
             "operating_lease_liabilities": c("operating_lease_liabilities", 129.9, "2026-06-30:Q2")}
    seen = []

    def lease_at(period):
        seen.append(period)
        return lease_fy if period == "2025-12-31:FY" else None

    v, cite, inside, warns = bb.financial_debt(point, ifrs=False, lease_at=lease_at)
    assert seen == ["2025-12-31:FY"]
    assert v == 0.0 and not inside
    assert cite["source_type"] == "DERIVED" and cite["rule"] == bb.RULE and len(cite["inputs"]) == 2
    assert "143.22" in cite["formula"]


def test_agregador_us_gaap_resto_positivo():
    # IBRX: 518,1 M de Yahoo − 41,0 M de arrendamiento operativo del 10-K = 477,1 M.
    point = {"cash_and_equivalents": c("cash_and_equivalents", 76, "2026-06-30:Q2"),
             "total_debt": c("total_debt", 518.075, "2025-12-31:FY", "YAHOO_FUNDAMENTALS")}
    lease = c("operating_lease_liabilities", 40.982, "2025-12-31:FY")
    v, _, _, _ = bb.financial_debt(point, ifrs=False, lease_at=lambda p: lease)
    assert abs(v - 477.093) < 1e-6


def test_agregador_sin_arrendamiento_primario_se_usa_con_aviso():
    point = {"cash_and_equivalents": c("cash_and_equivalents", 21202, "2026-06-30:Q2"),
             "total_debt": c("total_debt", 54538, "2025-12-31:FY", "YAHOO_FUNDAMENTALS")}
    v, cite, inside, warns = bb.financial_debt(point, ifrs=False, lease_at=lambda p: None)
    assert v == 54538 and cite["source_type"] == "YAHOO_FUNDAMENTALS" and not inside
    assert any("puede incluir" in w for w in warns)


def test_arrendamiento_mayor_que_la_deuda_no_se_resta():
    point = {"cash_and_equivalents": c("cash_and_equivalents", 10, "2025-12-31:FY"),
             "total_debt": c("total_debt", 20, "2025-12-31:FY", "YAHOO_FUNDAMENTALS")}
    lease = c("operating_lease_liabilities", 30, "2025-12-31:FY")
    v, _, _, _ = bb.financial_debt(point, ifrs=False, lease_at=lambda p: lease)
    assert v == 20


def test_arrendamiento_de_agregador_no_se_resta():
    point = {"cash_and_equivalents": c("cash_and_equivalents", 10, "2025-12-31:FY"),
             "total_debt": c("total_debt", 20, "2025-12-31:FY", "YAHOO_FUNDAMENTALS"),
             "operating_lease_liabilities": c("operating_lease_liabilities", 20, "2025-12-31:FY", "YAHOO_FUNDAMENTALS")}
    v, _, _, _ = bb.financial_debt(point, ifrs=False)
    assert v == 20


def test_ifrs_agregador_arrendamientos_una_sola_vez():
    # TSM/AIR.PA: el total de Yahoo ya trae los arrendamientos IFRS 16; no se suman otra vez.
    point = {"cash_and_equivalents": c("cash_and_equivalents", 14128, "2025-12-31:FY", "ESEF"),
             "total_debt": c("total_debt", 11023, "2025-12-31:FY", "YAHOO_FUNDAMENTALS")}
    v, _, inside, warns = bb.financial_debt(point, ifrs=True)
    assert v == 11023 and inside and warns


def test_sin_deuda_devuelve_none():
    assert bb.financial_debt({"cash_and_equivalents": c("cash_and_equivalents", 1, "2025-12-31:FY")}, ifrs=False)[0] is None
