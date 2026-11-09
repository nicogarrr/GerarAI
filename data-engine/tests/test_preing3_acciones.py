"""Acciones vigentes (regla «acciones-vigentes-v1», 9-nov-2026): portada con todas las clases y Up-C sin doble
cómputo. Caso real que la motivó: ASTS valorada con 256 M (media diluida de 2025) cuando la portada del 10-Q
de agosto de 2026 dice 389 M (A 299,8 + B 11,2 + C 78,2), y además restando 504 M de minoritarios que SON las
unidades de las clases B y C."""
from __future__ import annotations

import pytest

from app.valuation import current_shares as cs

ASTS = {"CommonClassAMember": 299.789305, "CommonClassBMember": 11.215111, "CommonClassCMember": 78.163078}
META = {"CommonClassAMember": 2214.472367, "CommonClassBMember": 341.768886}


def _meta(members, as_of="2026-08-06", **extra):
    return {"class_shares_provenance": {"concept": "dei:EntityCommonStockSharesOutstanding", "as_of": as_of,
                                        "members": {k: str(v) for k, v in members.items()}, **extra}}


def test_class_members_only_from_the_same_cover():
    assert cs.class_members(_meta(ASTS), "2026-08-06:DEI") == pytest.approx(ASTS)
    assert cs.is_class_sum(_meta(ASTS), "2026-08-06:DEI")
    # Otra portada (otra fecha): no se mezcla.
    assert cs.class_members(_meta(ASTS), "2026-11-06:DEI") is None
    assert not cs.is_class_sum(_meta(ASTS), "2026-11-06:DEI")
    # Clases convertidas a la cotizada con un ratio (BRK): es un total, pero no son unidades 1:1.
    brk = _meta({"CommonClassAMember": 0.5, "CommonClassBMember": 1300.0}, conversion_ratios={"A": "1500"})
    assert cs.is_class_sum(brk, "2026-08-06:DEI") and cs.class_members(brk, "2026-08-06:DEI") is None
    assert cs.class_members(None, "2026-08-06:DEI") is None


def test_up_c_detected_when_paired_classes_match_minorities():
    got = cs.up_c(ASTS, minority_interest=503.561, total_equity=2392.3)
    assert got is not None
    assert got["listed_class"] == "CommonClassAMember"
    assert got["paired_classes"] == ["CommonClassBMember", "CommonClassCMember"]
    assert got["paired_shares"] == pytest.approx(89.378, abs=1e-3)
    assert got["share_of_paired_classes"] == pytest.approx(0.2297, abs=1e-3)
    # Sin patrimonio: la parte de los minoritarios en el beneficio (−119 / −461 = 26 %).
    assert cs.up_c(ASTS, minority_interest=503.6, total_equity=None, ni_minority=-119.1, ni_total=-461.0) is not None


def test_dual_class_without_minorities_is_not_up_c():
    # META / GOOGL: clases B económicas, sin minoritarios → se suman todas y no hay nada que restar.
    assert cs.up_c(META, minority_interest=0.0, total_equity=200_000.0) is None
    assert cs.up_c(META, minority_interest=None, total_equity=None) is None


def test_minorities_unrelated_to_the_classes_are_not_up_c():
    # Minoritarios pequeños (1 %) frente a un 13 % de clase B: no son las unidades canjeables.
    assert cs.up_c(META, minority_interest=2_000.0, total_equity=200_000.0) is None
    # Una sola clase relevante (< 2 % en las demás): nada que emparejar.
    assert cs.up_c({"A": 1000.0, "B": 5.0}, minority_interest=10.0, total_equity=1000.0) is None


def test_cover_check_guards():
    assert cs.cover_check(389.2, 256.0, by_class=True) is None          # suma de clases: total por construcción
    assert cs.cover_check(389.2, 256.0, by_class=False) is None         # ampliación tras el cierre: vale
    assert "una sola clase" in cs.cover_check(150.0, 256.0, by_class=False)
    assert "escala" in cs.cover_check(900.0, 256.0, by_class=False)
    assert cs.cover_check(None, 256.0, by_class=False) == "sin portada"
    assert cs.cover_check(389.2, None, by_class=False) is None


def test_short_class_names():
    assert cs.short("CommonClassBMember") == "B" and cs.short("CapitalClassCMember") == "C"
