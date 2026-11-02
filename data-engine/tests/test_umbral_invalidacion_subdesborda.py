"""Criterio de invalidación con un umbral tan pequeño que el float lo redondea
a cero («1e-400»): se guardaba como 0 sin avisar, un criterio distinto del que
escribió el usuario. Ahora se rechaza igual que «1e400» (#4170)."""

import pytest

from app.services.thesis_invalidation_rules import normalize_rules


def _rule(threshold):
    return [{"metric": "precio", "operator": "<", "threshold": threshold}]


@pytest.mark.parametrize("threshold", ["1e-400", "-1e-400", "0.1E-999"])
def test_umbral_que_se_redondea_a_cero_se_rechaza(threshold):
    with pytest.raises(ValueError) as exc:
        normalize_rules(_rule(threshold))
    assert "Criterio 1" in str(exc.value)


@pytest.mark.parametrize("threshold", ["0", "0.0", "-0", 0, "0e-400"])
def test_cero_de_verdad_se_sigue_aceptando(threshold):
    assert normalize_rules(_rule(threshold))[0]["threshold"] == 0


def test_umbral_pequeno_pero_representable_se_acepta():
    assert normalize_rules(_rule("1e-300"))[0]["threshold"] == 1e-300
