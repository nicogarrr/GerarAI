"""Companies House: una filial entra por su PSC, no por su nombre (hallazgo del auditor sobre #4765).

Antes: (1) una sociedad que respondía a la pista y llevaba el nombre propio del holding entraba en el
grupo sin mirar su PSC; (2) un PSC corporativo que solo compartía la palabra propia del holding
(«FAIRFAX PROPERTIES LTD») se aceptaba como la matriz. Ahora hace falta una señal positiva: una cadena
de PSC que llegue al holding (mismo nombre) o un PSC persona que dirige el holding según datos
verificados. Lo que no la tiene se enseña como «sin verificar», con su motivo, y no da cifras."""
from __future__ import annotations

import asyncio

from app.services import companies_house_evidence as ev
from tests.test_companies_house import FFH_PEOPLE, _client, _replay

HOLDING = "Fairfax Financial Holdings Limited"
PSC = "api.company-information.service.gov.uk/company/{n}/persons-with-significant-control?items_per_page=50 application/json"


def test_sin_senal_de_psc_la_filial_por_nombre_no_entra_y_se_ve_por_que() -> None:
    client, _ = _client()
    result = asyncio.run(ev.group_accounts(client, holding_name=HOLDING, hints=["Brit", "Allied World"]))
    numbers = {r["company_number"] for r in result["members"]}
    assert "08821629" not in numbers and "15884169" not in numbers
    unverified = {u["company_number"]: u for u in result["unverified"]}
    assert "08821629" in unverified and unverified["08821629"]["why"]


def test_psc_homonimo_no_es_la_matriz() -> None:
    log = _replay()
    log[PSC.format(n="08821629")] = {"status": 200, "json": {"items": [{
        "kind": "corporate-entity-person-with-significant-control", "name": "Fairfax Properties Ltd",
        "identification": {"country_registered": "Ontario", "registration_number": "999"}}]}}
    client, _ = _client(log)
    result = asyncio.run(ev.group_accounts(client, holding_name=HOLDING, hints=["Brit"], people=FFH_PEOPLE))
    assert "08821629" not in {r["company_number"] for r in result["members"]}
    why = {u["company_number"]: u["why"] for u in result["unverified"]}["08821629"]
    assert "Fairfax Properties" in why


def test_psc_con_el_nombre_exacto_del_holding_si_es_la_matriz() -> None:
    log = _replay()
    log[PSC.format(n="08821629")] = {"status": 200, "json": {"items": [{
        "kind": "corporate-entity-person-with-significant-control", "name": "FAIRFAX FINANCIAL HOLDINGS LIMITED",
        "identification": {"country_registered": "Canada", "registration_number": "123"}}]}}
    client, _ = _client(log)
    result = asyncio.run(ev.group_accounts(client, holding_name=HOLDING, hints=["Brit"]))
    assert "08821629" in {r["company_number"] for r in result["members"]}


def test_persona_del_psc_debe_coincidir_entera() -> None:
    walk = ev._Walk(client=None, token="FAIRFAX", people=("Prem Watsa",))  # type: ignore[arg-type]
    assert ev._psc_person_of_holding(walk, [{"kind": "individual-person-with-significant-control",
                                             "name": "Mr Vivian Prem Watsa"}])
    assert ev._psc_person_of_holding(walk, [{"kind": "individual-person-with-significant-control",
                                             "name": "Mr John Watsa"}]) is None
