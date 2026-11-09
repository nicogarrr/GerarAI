"""Una tesis cortada a medias no se sirve como hecha: se reanuda pidiendo solo lo que falta.

Antes: si la 2.ª llamada al modelo fallaba (ASTS y CPT, 8-nov-2026), la tesis con solo las secciones
1–8 se guardaba y la siguiente lectura la devolvía como «cached» para siempre, con 9–15 vacías.
"""
from __future__ import annotations

import asyncio
import json

from app.services.expert_team import thesis_v2 as T
from tests.test_thesis_v2 import _ctx, _reply


def test_error_a_medias_se_reanuda_solo_con_lo_que_falta():
    ctx = _ctx()
    calls = {"n": 0}
    good = _reply(ctx, False)

    async def flaky(system, user, max_tokens, task):
        calls["n"] += 1
        if task.endswith("_b"):
            raise TimeoutError
        return await good(system, user, max_tokens, task)

    half = asyncio.run(T.write_thesis(reasoner=flaky, ctx=ctx))
    part_a = {k for k, _t, p, _tn in T.active_sections(ctx) if p == "a"}
    # El plazo agotado en la parte b ya no deja la tesis en «error»: la parte a se conserva y la b queda N/D.
    assert half.status == "partial" and set(half.sections) == part_a
    assert set(half.missing) == {k for k, *_ in T.active_sections(ctx)} - part_a
    cached = {"fingerprint": half.fingerprint, "sections": half.sections, "status": half.status}

    asked: list[set[str]] = []

    async def rec(system, user, max_tokens, task):
        asked.append({s["clave"] for s in json.loads(user)["secciones"]})
        return await good(system, user, max_tokens, task)

    done = asyncio.run(T.write_thesis(reasoner=rec, ctx=ctx, cached=cached))
    assert done.status == "ok" and done.llm_calls == 1
    assert asked and not (asked[0] & part_a)
    assert {k for k, *_ in T.active_sections(ctx)} == set(done.sections)


def test_tesis_completa_sigue_saliendo_de_cache():
    ctx = _ctx()
    res = asyncio.run(T.write_thesis(reasoner=_reply(ctx, False), ctx=ctx))

    async def boom(*a):  # noqa: ANN002
        raise AssertionError("no debe llamar al modelo")

    again = asyncio.run(T.write_thesis(reasoner=boom, ctx=ctx, cached={"fingerprint": res.fingerprint,
                                                                         "sections": res.sections, "status": "ok"}))
    assert again.status == "cached" and again.llm_calls == 0
