import asyncio
import json
from types import SimpleNamespace

import pytest

from app.services import public_headline_translation as service
from app.services.news_headline_translation import headline_numbers_match as _hnm


class Provider:
    name = 'fake'
    def __init__(self, text='Apple anuncia resultados 2026'):
        self.text = text
        self.calls = 0
    async def complete(self, request):
        self.calls += 1
        assert request.metadata['tenant_id'] == '1'
        assert 'untrusted DATA' in request.messages[0].content
        return SimpleNamespace(text=json.dumps({'text':self.text}),degraded=False,warnings=())

@pytest.fixture(autouse=True)
def clear(monkeypatch):
    service._cache.clear()
    monkeypatch.setattr(service,'reserve_quota',lambda *a,**k:{'allowed':True})


def test_cache_tenant_and_original():
    async def run():
        db=SimpleNamespace(info={'tenant_id':1})
        p=Provider()
        one=await service.translate_external_headline(db,'Apple reports earnings 2026',provider=p)
        two=await service.translate_external_headline(db,'Apple reports earnings 2026',provider=p)
        assert one==two and one['status']=='translated' and p.calls==1
        assert one['original']=='Apple reports earnings 2026'
        db.info['tenant_id']=2
        assert (await service.translate_external_headline(db,'Apple reports earnings 2026',provider=p))['status']=='unavailable'
        assert p.calls==2
    asyncio.run(run())


def test_bad_output_cooldown_and_quota(monkeypatch):
    async def run():
        db=SimpleNamespace(info={'tenant_id':1})
        p=Provider('Apple anuncia resultados 2027')
        assert (await service.translate_external_headline(db,'Apple reports earnings 2026',provider=p))['status']=='unavailable'
        await service.translate_external_headline(db,'Apple reports earnings 2026',provider=p)
        assert p.calls==1
        monkeypatch.setattr(service,'reserve_quota',lambda *a,**k:{'allowed':False})
        await service.translate_external_headline(db,'Apple reports results',provider=p)
        assert p.calls==1
    asyncio.run(run())


def test_free_provider_never_uses_cascade_or_paid_override(monkeypatch):
    from app.core.config import Settings
    settings=Settings(llm_provider='cascade',opencode_go_model='deepseek-v4.1-flash-free',llm_model_overrides={'x':'paid'},opencode_go_fallback_model='paid')
    monkeypatch.setattr(service,'get_settings',lambda:settings)
    captured=[]
    monkeypatch.setattr(service,'create_llm_provider',lambda value:captured.append(value) or Provider())
    assert service.free_provider()[0].name=='fake'
    assert captured[0].llm_provider=='opencode-go'
    assert captured[0].llm_model_overrides=={} and captured[0].opencode_go_fallback_model==''
    monkeypatch.setattr(service,'_resolved_verified_free_model',lambda *_:None)
    assert service.free_provider()==(None,None)


def test_spanish_skips_and_unscoped_denied():
    async def run():
        p=Provider()
        assert (await service.translate_external_headline(SimpleNamespace(info={'tenant_id':1}),'La empresa anuncia resultados',provider=p))['status']=='not_needed'
        assert p.calls==0
        with pytest.raises(PermissionError):
            await service.translate_external_headline(SimpleNamespace(info={}), 'Apple reports earnings',provider=p)
    asyncio.run(run())


class ChainProvider:
    """Proveedor de cadena: falla o devuelve salida controlada, y registra el orden."""

    def __init__(self, name, behavior):
        self.name = name
        self.behavior = behavior
        self.calls = []

    async def complete(self, request):
        self.calls.append(request.model)
        if self.behavior == 'raise':
            raise RuntimeError('provider down')
        if self.behavior == 'bad_numbers':
            return SimpleNamespace(text=json.dumps({'text': 'Apple anuncia resultados 2027'}), degraded=False, warnings=())
        return SimpleNamespace(text=json.dumps({'text': 'Apple anuncia resultados 2026'}), degraded=False, warnings=())


def test_chain_order_first_valid_wins(monkeypatch):
    async def run():
        db = SimpleNamespace(info={'tenant_id': 1})
        opencode = ChainProvider('opencode-go', 'raise')
        groq = ChainProvider('groq', 'ok')
        gemini = ChainProvider('gemini', 'ok')
        monkeypatch.setattr(service, 'free_provider_chain',
                            lambda: [(opencode, 'deepseek-v4.1-flash-free'), (groq, 'openai/gpt-oss-120b'), (gemini, 'gemini-3.5-flash-lite')])
        result = await service.translate_external_headline(db, 'Apple reports earnings 2026')
        assert result['status'] == 'translated' and result['text'] == 'Apple anuncia resultados 2026'
        # OpenCode falló, Groq ganó: Gemini ni se llama.
        assert opencode.calls == ['deepseek-v4.1-flash-free']
        assert groq.calls == ['openai/gpt-oss-120b']
        assert gemini.calls == []
    asyncio.run(run())


def test_chain_all_fail_returns_unavailable_never_invented(monkeypatch):
    async def run():
        db = SimpleNamespace(info={'tenant_id': 1})
        chain = [(ChainProvider('opencode-go', 'raise'), 'm1'),
                 (ChainProvider('groq', 'raise'), 'm2'),
                 (ChainProvider('gemini', 'raise'), 'm3')]
        monkeypatch.setattr(service, 'free_provider_chain', lambda: chain)
        result = await service.translate_external_headline(db, 'Apple reports earnings 2026')
        assert result['status'] == 'unavailable' and result['text'] is None
        assert result['original'] == 'Apple reports earnings 2026'
        assert all(p.calls for p, _ in chain)
    asyncio.run(run())


def test_chain_invalid_output_falls_through(monkeypatch):
    async def run():
        db = SimpleNamespace(info={'tenant_id': 1})
        bad = ChainProvider('opencode-go', 'bad_numbers')
        good = ChainProvider('groq', 'ok')
        monkeypatch.setattr(service, 'free_provider_chain', lambda: [(bad, 'm1'), (good, 'm2')])
        result = await service.translate_external_headline(db, 'Apple reports earnings 2026')
        # Cifra cambiada por el primero (2027): se rechaza y gana el segundo.
        assert result['status'] == 'translated' and result['text'] == 'Apple anuncia resultados 2026'
        assert bad.calls == ['m1'] and good.calls == ['m2']
    asyncio.run(run())


def test_chain_empty_is_unavailable(monkeypatch):
    async def run():
        db = SimpleNamespace(info={'tenant_id': 1})
        monkeypatch.setattr(service, 'free_provider_chain', lambda: [])
        result = await service.translate_external_headline(db, 'Apple reports earnings 2026')
        assert result['status'] == 'unavailable' and result['text'] is None
    asyncio.run(run())


def test_needs_translation_language_marks():
    n = service.needs_translation
    # Español claro: sin botón / not_needed.
    assert not n('La empresa anuncia resultados')
    assert not n('CPT eleva el dividendo tras superar las expectativas de ingresos')
    # Objeción del auditor (19-oct-2026): titulares españoles sin marcas de
    # lista tampoco son traducibles; no gasta presupuesto del proveedor.
    assert not n('Inditex bate previsiones')
    assert not n('Iberdrola eleva beneficio')
    assert not n('BBVA gana 5.000 millones')
    # Inglés con marcas: se ofrece.
    assert n('Apple reports earnings after the bell')
    # Acentos: el front usa lookarounds Unicode para igualar el \b de Python
    # (objeción del auditor, 19-oct-2026); estas cadenas fijan la paridad.
    assert not n('Las compañías del Ibex suben')
    assert not n('Energías renovables lideran el Ibex')
    assert not n('Las economías emergentes crecen')
    assert not n('Ñandú Capital invierte')
    # Sin marcas de ningún idioma: solo con señal latina-inglesa explícita
    # (Title Case de >=3 palabras, convención de prensa anglosajona).
    assert n('Meta Llama Beats Rivals Again')
    assert n('Müller Sachs Group Holdings')
    # Alfabetos no latinos siempre.
    assert n('Εταιρεία ανακοινώνει αποτελέσματα')


def test_nearly_identical_output_is_not_marked_translated():
    async def run():
        original = 'Apple reports earnings after the bell'
        # El modelo devuelve el texto sin traducir (idéntico): no se acepta.
        service._cache.clear()
        identical = await service.translate_external_headline(
            SimpleNamespace(info={'tenant_id': 1}), original, provider=Provider(text=original))
        assert identical['status'] == 'unavailable'
        # Casi idéntico (solo cambia puntuación/mayúsculas): tampoco.
        service._cache.clear()
        near = await service.translate_external_headline(
            SimpleNamespace(info={'tenant_id': 1}), original,
            provider=Provider(text='Apple reports earnings after the bell.'))
        assert near['status'] == 'unavailable'
        # Una traducción real sí se acepta.
        service._cache.clear()
        real = await service.translate_external_headline(
            SimpleNamespace(info={'tenant_id': 1}), original,
            provider=Provider(text='Apple informa de resultados tras el cierre'))
        assert real['status'] == 'translated'
    asyncio.run(run())


def test_headline_numbers_dates_relaxed_everything_else_strict():
    from app.services.news_headline_translation import headline_numbers_match as ok

    # Fechas, años y trimestres: las palabras vecinas cambian al traducir.
    assert ok("Apple Announces Oct. 28 Event for Touch-Screen MacBook Pro", "Apple anuncia un evento el 28 de octubre para el MacBook Pro")
    assert ok("Transcript : ASML Holding N.V., Q3 2026 Pre Recorded Earnings Call, Oct 14, 2026", "Transcripción: ASML Holding N.V., llamada del Q3 2026, 14 de octubre de 2026")
    assert not ok("Apple Announces Oct. 28 Event", "Apple anuncia un evento el 29 de octubre")
    assert not ok("Apple Announces Oct. 28 Event", "Apple anuncia un evento el 28 de octubre con un 5% más")
    # Cualquier otro numero: firma estricta, la direccion no puede invertirse.
    assert not ok("Tesla shares fall 8%", "Las acciones de Tesla suben un 8%")
    assert not ok("Fed cuts rates by 0.25%", "La Fed sube los tipos un 0.25%")
    assert not ok("Down 5%", "Sube 5%")
    assert not ok("Revenue 12 million USD", "Ingresos 12 billion USD")
    assert not ok("FCF 12 USD", "FCF 12 EUR")
    assert not ok("growth -12%", "crecimiento 12%")


def test_headline_direction_must_survive_translation():
    from app.services.news_headline_translation import headline_numbers_match as ok

    assert not ok("Dividend raised on Oct 28", "Dividendo recortado el 28 de octubre")
    assert not ok("Q3 profit falls", "El beneficio del Q3 sube")
    assert not ok("Dividend raised on Oct 28", "Dividendo el 28 de octubre")  # sin direccion: no se acepta
    assert ok("Dividend raised on Oct 28", "Dividendo aumentado el 28 de octubre")
    assert ok("Q3 profit falls", "El beneficio del Q3 baja")
    assert ok("Apple Announces Oct. 28 Event", "Apple anuncia un evento el 28 de octubre")


def test_headline_with_percent_and_single_direction_is_accepted_but_not_swapped():
    from app.services.news_headline_translation import headline_numbers_match as ok

    assert ok("Amazon Soars 5%", "Amazon se dispara un 5%")
    assert ok("Tesla shares fall 8%", "Las acciones de Tesla caen un 8%")
    # Direccion invertida, cifra cambiada o dimension cambiada: se rechaza.
    assert not ok("Tesla shares fall 8%", "Las acciones de Tesla suben un 8%")
    assert not ok("Tesla shares fall 8%", "Las acciones de Tesla caen un 5%")
    assert not ok("Tesla shares fall $8", "Las acciones de Tesla caen 8 euros")
    # Dos movimientos: las cifras no pueden intercambiarse entre empresas.
    assert not ok("Amazon falls 5% while Apple rises 8%", "Amazon sube un 8% mientras Apple cae un 5%")


def test_headline_relaxed_route_rejects_crossed_figures_negations_and_clauses():
    from app.services.news_headline_translation import headline_numbers_match as ok

    # Una sola clausula, una cifra, un sentido: se acepta.
    assert ok("Amazon Soars 5%", "Amazon se dispara un 5%")
    assert ok("Tesla shares fall 8%", "Las acciones de Tesla caen un 8%")
    # Dos cifras con el mismo sentido o cifras cruzadas: se rechaza.
    assert not ok("Amazon soars 5%, Apple gains 8%", "Apple se dispara un 5%, Amazon gana un 8%")
    assert not ok("Shares fall 8% after revenue drops 5%", "Las acciones caen un 5% tras bajar los ingresos un 8%")
    # Dos clausulas con conector: la entidad podria cruzarse.
    assert not ok("Amazon soars while Apple gains 5%", "Apple se dispara mientras Amazon gana un 5%")
    assert not ok("Amazon Soars 5% as Morgan Stanley Names It a Top Pick", "Morgan Stanley se dispara un 5% mientras nombra a Amazon")
    # Negaciones en la ruta relajada.
    assert not ok("Tesla shares fall 8%", "Las acciones de Tesla no caen un 8%")
    assert not ok("Tesla shares do not fall 8%", "Las acciones de Tesla caen un 8%")
    assert not ok("Tesla shares don't fall 8%", "Las acciones de Tesla no caen un 8%")


def test_negation_does_not_block_headlines_the_strict_route_already_accepted():
    from app.services.news_headline_translation import headline_numbers_match as ok

    # Sin cifras ni fechas la ruta estricta (firma vacia) y la polaridad deciden, como en main.
    assert ok("Fed not expected to cut rates", "Se espera que la Fed no recorte los tipos")
    assert ok("Ford says no layoffs planned", "Ford dice que no hay despidos previstos")
    assert ok("stocks rise without Fed help", "las acciones suben sin ayuda de la Fed")
    assert ok("Dividend does not rise on Oct 28", "El dividendo no aumenta el 28 de octubre")






def test_equivalencia_billion_millones_caso_real_capturado():
    o = "Meta Raises 2026 Capex Guidance To $72 Billion Amid AI Push"
    t = "Meta eleva su previsión de capex para 2026 a 72.000 millones de dólares en medio de su impulso en IA"
    assert _hnm(o, t)


@pytest.mark.parametrize("o,t", [
    ("Meta Raises Capex To $72 Billion", "Meta eleva el capex a 27.000 millones de dólares"),
    ("Meta Raises Capex To $72 Billion", "Meta eleva el capex a 72.000 millones de euros"),
    ("Meta Raises Capex To $72 Billion", "Meta eleva el capex a 72 millones de dólares"),
    ("Meta Raises Capex To $72 Billion", "Meta eleva el capex a 72 billones de dólares"),
    ("Meta Raises Capex To $72 Billion", "Meta eleva el capex a 72.5 millones de dólares"),
    ("Meta Raises Capex To $72 Billion", "Meta recorta el capex a 72.000 millones de dólares"),
    ("Meta Raises Capex To $72 Billion, Apple $3 Billion", "Meta eleva el capex a 3.000 millones de dólares, Apple 72.000 millones de dólares"),
    ("Meta Raises 2026 Capex To $72 Billion", "Meta eleva el capex de 2027 a 72.000 millones de dólares"),
])
def test_equivalencia_billion_millones_rechaza_no_equivalentes(o, t):
    assert not _hnm(o, t)


def test_equivalencia_mil_millones_y_decimales():
    assert _hnm("Meta Raises Capex To $1.5 Billion", "Meta eleva el capex a 1.500 millones de dólares")
    assert _hnm("Meta Raises Capex To $72 Billion", "Meta eleva el capex a 72 mil millones de dólares")
    assert _hnm("Meta Raises Capex To $72 Million", "Meta eleva el capex a 72 millones de dólares")


@pytest.mark.parametrize("o,t", [
    ("Meta Raises Capex To US$72 Billion", "Meta eleva el capex a 72.000 millones de dólares"),
    ("Meta Raises Capex To $72 Billion", "Meta eleva el capex a 72.000 millones de dólares estadounidenses"),
    ("Meta Raises Capex To $72 Billion", "Meta eleva el capex a 72.000 millones de dólares canadienses"),
    ("Meta Raises Capex To C$72 Billion", "Meta eleva el capex a 72.000 millones de dólares"),
    ("Meta Raises Capex To A$72 Billion", "Meta eleva el capex a 72.000 millones de dólares"),
    ("Meta Raises Capex To $72 Billion USD", "Meta eleva el capex a 72.000 millones de dólares"),
    ("Meta Raises Capex To $72 Billion CAD", "Meta eleva el capex a 72.000 millones de dólares"),
    ("Meta Raises Capex To $72 Billion", "Meta eleva el capex a 72.000 millones de dólares australianos"),
    ("Meta Raises Capex To $72 Billion", "Meta eleva el capex a 72.000 millones de USD"),
])
def test_equivalencia_rechaza_calificadores_de_divisa(o, t):
    assert not _hnm(o, t)


def test_equivalencia_genericos_ambos_lados_se_mantiene():
    assert _hnm("Meta Raises Capex To $72 Billion", "Meta eleva el capex a 72.000 millones de dólares")


@pytest.mark.parametrize("o,t", [
    ("Meta Does Not Raise Capex To $72 Billion", "Meta eleva el capex a 72.000 millones de dólares"),
    ("Meta Raises Capex To $72 Billion", "Meta no eleva el capex a 72.000 millones de dólares"),
    ("Meta Raises Capex To $72 Billion Without Debt", "Meta eleva el capex a 72.000 millones de dólares"),
    ("Meta Raises Capex To $72 Billion", "Meta eleva el capex a 72.000 millones de dólares sin deuda"),
])
def test_equivalencia_falla_cerrado_con_negacion(o, t):
    assert not _hnm(o, t)


def test_request_uses_registered_prompt_and_keeps_tenant_metadata():
    from app.services import prompt_registry

    seen = []

    class Capturing(Provider):
        async def complete(self, request):
            seen.append(request)
            return await super().complete(request)

    async def run():
        db = SimpleNamespace(info={'tenant_id': 1})
        await service.translate_external_headline(db, 'Apple reports earnings 2026', provider=Capturing())
    asyncio.run(run())
    resolved = prompt_registry.get_prompt('public_headline_translation', allow_remote=False)
    assert seen[0].messages[0].content == resolved.text
    assert seen[0].metadata == {**resolved.trace_metadata(), 'tenant_id': '1'}
