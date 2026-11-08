"""El Recopilador ya no tira los impulsores bien citados por uno mal citado (que no se pierda nada).

Antes (8-nov-2026, ERF con el modelo de la app): dos respuestas con algún impulsor mal citado → «rejected»
y 0 impulsores; el escéptico se quedaba sin inventario («no_data»).
"""
from app.services.expert_team import recopilador as R
from app.services.expert_team.ledger import EvidenceLedger


def _ledger():
    led = EvidenceLedger()
    ev = led.add(expert=R.RECOPILADOR_NAME, tool="company_documents", source={"url": "https://sec.gov/a", "document_id": "1"},
                 data={"text": "The company signed a definitive agreement with a large carrier."})
    return led, ev.id


def _driver(key, eid, quote):
    return {"driver_key": key, "category": "contrato", "name": key, "status": "firmado", "source_type": "filing",
            "evidence": "oficial", "source_url": "https://sec.gov/a", "source_quote": quote, "citations": [eid],
            "economics": {}}


def test_parcial_guarda_los_bien_citados_y_explica_los_demas():
    led, eid = _ledger()
    parsed = {"drivers": [_driver("bueno", eid, "signed a definitive agreement"),
                          _driver("malo", eid, "frase que no está en el documento")]}
    items, problems = R.parse_inventory(parsed, led)
    assert items == [] and problems  # sin «partial» sigue siendo fail-closed
    items, problems = R.parse_inventory(parsed, led, partial=True)
    assert [i.driver_key for i in items] == ["bueno"]
    assert any(p.startswith("malo: ") for p in problems)
