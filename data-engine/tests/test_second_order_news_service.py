from datetime import UTC, datetime

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models.entities import Base, Company, NewsEvent
from app.services import second_order_news_service as service


def test_second_order_is_read_only_and_marks_source_claim_unverified(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.info["tenant_id"] = "tenant-test"
        db.add_all([
            Company(ticker="GRID", name="Grid Co", exchange="NYSE", currency="USD",
                    sector="Utilities", industry="Electric Utilities", company_type="holding",
                    valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[]),
            Company(ticker="OIL", name="Oil Co", exchange="NYSE", currency="USD",
                    sector="Energy", industry="Oil & Gas", company_type="holding",
                    valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[]),
            Company(ticker="SEC", name="Sector Only Co", exchange="NYSE", currency="USD",
                    sector="Oil & Gas", industry="Refining", company_type="holding",
                    valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[]),
            Company(ticker="UNR", name="Unknown Co", exchange="NYSE", currency="USD",
                    sector="Unknown", industry="Unknown", company_type="holding",
                    valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[]),
            NewsEvent(title="Electric trucks require 350 TWh of electrification",
                      summary="A claim about electric trucks", source="GDELT", url="https://example.test/story",
                      date=datetime(2026, 9, 27, tzinfo=UTC),
                      metadata_={"date_source": "source"}),
        ])
        db.commit()
        monkeypatch.setattr(service, "_jev_marker", lambda theme: {
            "direction": None, "confidence": None, "backend": None,
        })
        event = db.query(NewsEvent).one()
        result = service.analyze_second_order(db, event)
        assert result["status"] == "hipótesis_no_verificadas"
        assert result["source_verified"] is False
        assert "350 TWh" in result["source_claim"]
        assert result["source"]["published_at"] is not None
        assert {item["ticker"] for item in result["candidates"]} == {"GRID", "OIL"}
        assert all(item["reason"] for item in result["candidates"])
        assert result["limited_to"] == 10
        assert all(item["status"] == "hipótesis_no_verificada" for item in result["candidates"])
        assert all(item["sources"][0]["url"] == "https://example.test/story" for item in result["candidates"])
        assert not db.dirty and not db.new


def test_unknown_or_unsourced_news_stays_without_candidates(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.info["tenant_id"] = "tenant-test"
        event = NewsEvent(title="Nothing relevant", summary="Generic update", source="manual",
                          metadata_={"date_source": "ingested_at_fallback"})
        db.add(event)
        db.commit()
        monkeypatch.setenv("SECOND_ORDER_LLM_ENABLED", "0")
        result = service.analyze_second_order(db, event, use_llm=True)
        assert result["status"] == "sin_datos"
        assert result["candidates"] == []
        assert result["source"]["published_at"] is None
        assert result["mode"] == "determinista"
        assert "desactivado" in result["note"]


def test_jev_absent_never_calls_old_ungated_client(monkeypatch):
    monkeypatch.setattr(service, "_normalized", lambda text: text.lower())
    marker = service._jev_marker(service.Theme(exposure="Power", direction="incierta", chain=[
        service.CausalStep(cause="A", effect="B")]))
    assert marker["direction"] is None


def test_llm_quota_is_tenant_scoped_and_reports_limit(monkeypatch):
    from types import SimpleNamespace

    from app.services import asts_llm_quota as quota_store
    from app.services import second_order_quota as quota

    # El contador de respaldo local es del modulo que aloja la cuenta compartida.
    monkeypatch.setattr(quota_store, "_LOCAL", {})
    config = SimpleNamespace(is_production=False, second_order_llm_calls_per_minute=2,
                             second_order_llm_calls_per_day=3)
    assert quota.reserve_llm_call("tenant-one", config)["allowed"] is True
    assert quota.reserve_llm_call("tenant-one", config)["minute_used"] == 2
    exceeded = quota.reserve_llm_call("tenant-one", config)
    assert exceeded["allowed"] is False
    assert exceeded["minute_used"] == 2
    assert quota.reserve_llm_call("tenant-two", config)["allowed"] is True
    from pytest import raises
    with raises(RuntimeError, match="verified tenant"):
        quota.reserve_llm_call(None, config)


def test_llm_cap_falls_back_honestly_without_call(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.info["tenant_id"] = "tenant-test"
        event = NewsEvent(title="Electric trucks", summary="Electrification", source="manual",
                          metadata_={"date_source": "source"})
        db.add(event)
        db.commit()
        monkeypatch.setenv("SECOND_ORDER_LLM_ENABLED", "1")
        monkeypatch.setattr(service, "reserve_llm_call", lambda *_args: {
            "allowed": False, "minute_used": 4, "minute_limit": 4,
            "day_used": 4, "day_limit": 100,
        })
        monkeypatch.setattr(service, "_extract_with_llm", lambda text: (_ for _ in ()).throw(
            AssertionError("LLM must not be called")))
        result = service.analyze_second_order(db, event, use_llm=True)
        assert result["mode"] == "determinista"
        assert "tope alcanzado" in result["note"]
        assert result["llm_quota"]["minute_used"] == 4


def test_candidate_query_prefilters_universe(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.info["tenant_id"] = "tenant-test"
        db.add_all([
            Company(ticker="COP", name="Copper Co", exchange="NYSE", currency="USD",
                    sector="Unknown", industry="Unknown", company_type="holding",
                    valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=["Copper"]),
            Company(ticker="XYZ", name="Other Co", exchange="NYSE", currency="USD",
                    sector="Energy", industry="Oil", company_type="holding",
                    valuation_model="unassigned", special_sources=[], special_risks=[], factor_tags=[]),
        ])
        db.commit()
        matches = service._matching_companies(db, "copper")
        assert [company.ticker for company in matches] == ["COP"]


def test_llm_request_pins_free_model_even_with_paid_override(monkeypatch):
    import asyncio
    from types import SimpleNamespace

    captured = []

    class Provider:
        name = "opencode-go"
        model_router = SimpleNamespace(resolve=lambda request: request.model)

        async def complete(self, request):
            captured.append(request)
            return SimpleNamespace(text='{"themes": []}')

    monkeypatch.setattr(service, "create_llm_provider", lambda: Provider())
    result, _ = asyncio.run(service._extract_with_llm("Una noticia general"))
    assert result.themes == []
    assert captured[0].model == "deepseek-v4.1-flash"
    result, _ = asyncio.run(service._extract_with_llm("Una noticia", context="- Ticker: ASTS"))
    assert "ASTS" in captured[1].messages[-1].content
    assert "Noticia:" in captured[1].messages[-1].content


def _company_db(*companies):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    db.info["tenant_id"] = "tenant-test"
    db.add_all(companies)
    db.commit()
    return db


def _mk_company(ticker, sector=None, industry=None, tags=None):
    return Company(ticker=ticker, name=f"{ticker} Co", exchange="NYSE", currency="USD",
                   sector=sector, industry=industry, company_type="holding",
                   valuation_model="unassigned", special_sources=[], special_risks=[],
                   factor_tags=tags or [])


def test_prefilter_keeps_accented_sector_match():
    """Exposure sin tilde debe encontrar Company.sector con tilde: el filtro
    SQL no puede excluir filas que la normalización Python emparejaría."""
    db = _company_db(_mk_company("ELEC", sector="Electrificación"))
    try:
        matches = service._matching_companies(db, "Electrificacion")
        assert [c.ticker for c in matches] == ["ELEC"]
    finally:
        db.close()


def test_prefilter_keeps_accented_factor_tag_match():
    db = _company_db(_mk_company("TAGS", sector="Other", tags=["Gestión logística"]))
    try:
        matches = service._matching_companies(db, "gestion logistica")
        assert [c.ticker for c in matches] == ["TAGS"]
        # Y el cotejo Python confirma la igualdad normalizada exacta.
        confirmed = [c for c in matches
                     if any(service._normalized(v) == service._normalized("gestion logistica")
                            for _, v in service._company_exposures(c))]
        assert [c.ticker for c in confirmed] == ["TAGS"]
    finally:
        db.close()


def test_prefilter_is_superset_of_python_match():
    """Propiedad: toda empresa que Python emparejaría queda dentro del
    prefilter SQL (sin exclusiones por tilde/puntuación ni por límite)."""
    db = _company_db(
        _mk_company("ACC", sector="Electrificación"),
        _mk_company("PUN", industry="Oil & Gas"),
        _mk_company("OUT", sector="Consumer Staples"),
    )
    try:
        for exposure in ("Electrificacion", "oil   gas"):
            norm = service._normalized(exposure)
            expected = [c.ticker for c in db.query(Company).all()
                        if any(service._normalized(v) == norm
                               for _, v in service._company_exposures(c))]
            got = {c.ticker for c in service._matching_companies(db, exposure)}
            assert set(expected) <= got, (exposure, expected, got)
    finally:
        db.close()


def test_prefilter_folds_uppercase_accents_sqlite():
    """SQLite lower() es ASCII-only: 'Árbol' no baja a 'árbol'. El fold SQL
    debe reemplazar mayúsculas acentuadas ANTES del lower (casos del auditor:
    'Árbol', 'Ñu', 'Éxito', 'ÁREA')."""
    db = _company_db(
        _mk_company("ARB", sector="Árbol"),
        _mk_company("NU", industry="Ñu"),
        _mk_company("EXI", tags=["Éxito"]),
        _mk_company("AREA", sector="ÁREA"),
    )
    try:
        assert {c.ticker for c in service._matching_companies(db, "arbol")} == {"ARB"}
        assert {c.ticker for c in service._matching_companies(db, "nu")} == {"NU"}
        assert {c.ticker for c in service._matching_companies(db, "exito")} == {"EXI"}
        assert {c.ticker for c in service._matching_companies(db, "area")} == {"AREA"}
    finally:
        db.close()


def _llm_event(db):
    event = NewsEvent(title="Electric trucks", summary="Electrification", source="manual",
                      metadata_={"date_source": "source"})
    db.add(event)
    db.commit()
    return event


def _scripted_provider(monkeypatch, *texts):
    from types import SimpleNamespace

    calls = []

    class Provider:
        name = "opencode-go"
        model_router = SimpleNamespace(resolve=lambda request: request.model)

        async def complete(self, request):
            calls.append(request)
            return SimpleNamespace(text=texts[len(calls) - 1])

    monkeypatch.setattr(service, "create_llm_provider", lambda: Provider())
    return calls


GOOD = ('{"themes": [{"exposure": "Copper", "direction": "beneficiada", '
        '"chain": [{"cause": "Mas camiones electricos", "effect": "Mas demanda de cobre"}]}]}')
CJK = ('{"themes": [{"exposure": "Copper", "direction": "beneficiada", '
       '"chain": [{"cause": "\u4e2d\u6587\u6a21\u578b", "effect": "demanda"}]}]}')


def test_cjk_output_retries_once_reserving_a_second_quota_call(monkeypatch):
    reservations = []
    monkeypatch.setenv("SECOND_ORDER_LLM_ENABLED", "1")
    monkeypatch.setattr(service, "reserve_llm_call", lambda *_a: reservations.append(1) or {
        "allowed": True, "minute_used": len(reservations), "minute_limit": 4,
        "day_used": len(reservations), "day_limit": 100})
    calls = _scripted_provider(monkeypatch, CJK, GOOD)
    with _company_db() as db:
        result = service.analyze_second_order(db, _llm_event(db), use_llm=True)
    assert result["mode"] == "llm" and len(calls) == 2 and len(reservations) == 2
    assert result["llm_quota"]["minute_used"] == 2
    assert result["themes"][0]["chain"][0]["cause"].startswith("Mas camiones")


def test_retry_without_quota_degrades_to_deterministic(monkeypatch):
    seen = []

    def reserve(*_a):
        seen.append(1)
        return {"allowed": len(seen) == 1, "minute_used": len(seen), "minute_limit": 1,
                "day_used": len(seen), "day_limit": 100}

    monkeypatch.setenv("SECOND_ORDER_LLM_ENABLED", "1")
    monkeypatch.setattr(service, "reserve_llm_call", reserve)
    calls = _scripted_provider(monkeypatch, CJK, GOOD)
    with _company_db() as db:
        result = service.analyze_second_order(db, _llm_event(db), use_llm=True)
    assert result["mode"] == "determinista" and len(calls) == 1
    assert "se usa el camino determinista" in result["note"]


def test_double_cjk_output_degrades_to_deterministic(monkeypatch):
    monkeypatch.setenv("SECOND_ORDER_LLM_ENABLED", "1")
    monkeypatch.setattr(service, "reserve_llm_call", lambda *_a: {
        "allowed": True, "minute_used": 1, "minute_limit": 4, "day_used": 1, "day_limit": 100})
    calls = _scripted_provider(monkeypatch, CJK, CJK)
    with _company_db() as db:
        result = service.analyze_second_order(db, _llm_event(db), use_llm=True)
    assert result["mode"] == "determinista" and len(calls) == 2


def test_no_transaction_is_held_during_either_llm_call(monkeypatch):
    from types import SimpleNamespace as NS

    monkeypatch.setenv("SECOND_ORDER_LLM_ENABLED", "1")
    monkeypatch.setattr(service, "reserve_llm_call", lambda *_a: {
        "allowed": True, "minute_used": 1, "minute_limit": 4, "day_used": 1, "day_limit": 100})
    with _company_db(_mk_company("CPR", sector="Copper")) as db:
        _llm_event(db)
        # Como en la ruta: el evento llega cargado por un SELECT que abre transaccion.
        event = db.scalars(select(NewsEvent)).one()
        event_id = event.id
        assert db.in_transaction()
        seen = []
        texts = [CJK, GOOD]

        class Provider:
            name = "opencode-go"
            model_router = NS(resolve=lambda request: request.model)

            async def complete(self, request):
                seen.append(db.in_transaction())
                return NS(text=texts[len(seen) - 1])

        monkeypatch.setattr(service, "create_llm_provider", lambda: Provider())
        result = service.analyze_second_order(db, event, use_llm=True)
    assert seen == [False, False]
    assert result["mode"] == "llm" and result["source"]["name"] == "manual"
    assert result["news_event_id"] == event_id


def _allow_quota(monkeypatch):
    monkeypatch.setenv("SECOND_ORDER_LLM_ENABLED", "1")
    monkeypatch.setattr(service, "reserve_llm_call", lambda *_a: {
        "allowed": True, "minute_used": 1, "minute_limit": 4, "day_used": 1, "day_limit": 100})


def test_single_theme_capped_at_two_with_concrete_reason(monkeypatch):
    companies = [_mk_company(f"C{i:02d}", industry="Copper") for i in range(12)]
    companies.append(_mk_company("SEC", sector="Copper"))  # solo sector: descartado
    _allow_quota(monkeypatch)
    _scripted_provider(monkeypatch, GOOD)
    with _company_db(*companies) as db:
        result = service.analyze_second_order(db, _llm_event(db), use_llm=True)
    assert result["mode"] == "llm"
    assert len(result["candidates"]) == 2
    assert result["limited_to"] == 10
    assert "SEC" not in {item["ticker"] for item in result["candidates"]}
    assert all("Copper" in item["reason"] for item in result["candidates"])
    assert all(item["status"] == "hipótesis_no_verificada" for item in result["candidates"])


def test_sector_only_match_yields_no_candidates(monkeypatch):
    _allow_quota(monkeypatch)
    _scripted_provider(monkeypatch, GOOD)
    with _company_db(_mk_company("CPR", sector="Copper")) as db:
        result = service.analyze_second_order(db, _llm_event(db), use_llm=True)
    assert result["mode"] == "llm"
    assert result["candidates"] == []
    assert result["status"] == "sin_datos"


def _tenant_company_db(*, with_peer: bool):
    from app.models.entities import PeerRelationship, Tenant

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    tenant = Tenant(external_id="ctx-tenant", name="Ctx")
    asts = _mk_company("ASTS", sector="Technology", industry="Communication Equipment")
    gsat = _mk_company("GSAT", sector="Technology", industry="Communication Equipment")
    db.add_all([tenant, asts, gsat])
    db.flush()
    if with_peer:
        db.add(PeerRelationship(tenant_id=tenant.id, company_id=asts.id,
                                peer_company_id=gsat.id, selected=True))
    db.commit()
    db.info["tenant_id"] = tenant.id
    return db, asts


def test_company_context_and_peers_reach_the_llm_prompt(monkeypatch):
    _allow_quota(monkeypatch)
    calls = _scripted_provider(monkeypatch, GOOD)
    db, asts = _tenant_company_db(with_peer=True)
    try:
        event = NewsEvent(title="Demanda colectiva contra ASTS", summary="Bufete anuncia demanda",
                          source="manual", company_id=asts.id,
                          metadata_={"date_source": "source"})
        db.add(event)
        db.commit()
        result = service.analyze_second_order(db, event, use_llm=True)
    finally:
        db.close()
    assert result["mode"] == "llm"
    prompt = calls[0].messages[-1].content
    assert "ASTS" in prompt and "Communication Equipment" in prompt
    assert "GSAT" in prompt
    assert "sin relaciones conocidas" not in prompt


def test_company_context_says_no_known_relations(monkeypatch):
    _allow_quota(monkeypatch)
    calls = _scripted_provider(monkeypatch, GOOD)
    db, asts = _tenant_company_db(with_peer=False)
    try:
        event = NewsEvent(title="Demanda colectiva contra ASTS", summary="Bufete anuncia demanda",
                          source="manual", company_id=asts.id,
                          metadata_={"date_source": "source"})
        db.add(event)
        db.commit()
        result = service.analyze_second_order(db, event, use_llm=True)
    finally:
        db.close()
    assert result["mode"] == "llm"
    assert "sin relaciones conocidas" in calls[0].messages[-1].content


def test_generated_display_title_is_not_treated_as_source_claim():
    with _company_db() as db:
        event = NewsEvent(title="ASTS Company update New ITU filing", summary="",
                          source="manual",
                          metadata_={"date_source": "source", "headline_from_source": False,
                                     "source_headline": "ASTS ITU filing submitted"})
        db.add(event)
        db.commit()
        result = service.analyze_second_order(db, event)
    assert "ASTS ITU filing submitted" in result["source_claim"]
    assert "Company update" not in result["source_claim"]


def test_specific_indirect_candidates_are_unique_and_exclude_subject(monkeypatch):
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.info['tenant_id'] = 1
        subject = Company(ticker='ASTS',name='AST SpaceMobile',exchange='NASDAQ',company_type='operating',valuation_model='unassigned',industry='Satellite Communications',factor_tags=['speculative','pre_fcf','Satellite Communications'])
        peer = Company(ticker='PEER',name='Satellite peer',exchange='NASDAQ',company_type='operating',valuation_model='unassigned',industry='Satellite Communications',factor_tags=['Satellite Communications','Copper'])
        noise = Company(ticker='BIO',name='Unrelated biotech',exchange='NASDAQ',company_type='operating',valuation_model='unassigned',industry='Biotechnology',factor_tags=['speculative','pre_fcf'])
        db.add_all([subject,peer,noise]);db.flush()
        event = NewsEvent(company_id=subject.id,title='Satellite news',summary='',source='test')
        db.add(event);db.commit()
        chain = [service.CausalStep(cause='Source claim',effect='Possible economic consequence')]
        monkeypatch.setattr(service,'_fallback',lambda _:service.Extraction(themes=[service.Theme(exposure=exposure,direction='incierta',chain=chain) for exposure in ['speculative','pre_fcf','Satellite Communications','Copper','Satellite Communications']]))
        monkeypatch.setattr(service,'_jev_marker',lambda _:dict(direction=None,confidence=None,backend=None))
        result=service.analyze_second_order(db,event)
        assert [row['ticker'] for row in result['candidates']]==['PEER']
        assert all(row['status']=='hipótesis_no_verificada' and row['reason'] for row in result['candidates'])
        assert result['source_verified'] is False
        assert not db.new and not db.dirty
        context=service._company_context(db,subject.id,1)
        assert 'speculative' not in context and 'pre_fcf' not in context


def test_generic_exposures_cannot_be_only_matching_reason():
    for tag in ['speculative','PRE_FCF','pre-fcf','pre_revenue','growth','high_beta']:
        assert service._specific_exposure(tag) is False
    assert service._specific_exposure('Property & Casualty Insurance') is True
    assert service._specific_exposure('Satellite Communications') is True


def test_real_public_headlines_local_replay_preserves_indirect_hypotheses(monkeypatch):
    # Actual public headlines, not asserted to be stored NewsEvent IDs or verified claims.
    # https://www.streetinsider.com/Reuters/Honda+plans+highway+test+of+wireless+charging+for+moving+trucks/27144605.html
    # https://electrek.co/2026/10/12/electric-trucks-meet-hydro-power-at-one-of-canadas-busiest-ports/
    db = _company_db(_mk_company('GRID', industry='Electric Utilities'),
                     _mk_company('OIL', industry='Oil & Gas'),
                     _mk_company('BIO', industry='Biotechnology', tags=['speculative','pre_fcf']))
    monkeypatch.setattr(service, '_jev_marker', lambda _:dict(direction=None,confidence=None,backend=None))
    try:
        for title, summary, source in [
            ('Honda plans highway test of wireless charging for moving trucks',
             'Honda developed technology that can wirelessly charge electric trucks while being driven.', 'Reuters via StreetInsider'),
            ("Electric trucks meet hydro power at one of Canada's busiest ports", '', 'Electrek'),
        ]:
            event = NewsEvent(title=title,summary=summary,source=source)
            db.add(event);db.commit()
            result = service.analyze_second_order(db,event)
            assert {row['ticker'] for row in result['candidates']} == {'GRID','OIL'}
            assert all(row['status']=='hipótesis_no_verificada' for row in result['candidates'])
            assert not db.new and not db.dirty
    finally:
        db.close()


def test_duplicate_themes_do_not_consume_unique_candidate_limit(monkeypatch):
    db = _company_db(*[_mk_company(f'CO{i:02}',industry='Electric Utilities') for i in range(15)])
    try:
        event = NewsEvent(title='Electric trucks',source='test')
        db.add(event);db.commit()
        theme=service.Theme(exposure='Electric Utilities',direction='incierta',chain=[service.CausalStep(cause='Source claim',effect='Possible effect')])
        monkeypatch.setattr(service,'_fallback',lambda _:service.Extraction(themes=[theme,theme,theme]))
        monkeypatch.setattr(service,'_jev_marker',lambda _:dict(direction=None,confidence=None,backend=None))
        result=service.analyze_second_order(db,event)
        tickers=[row['ticker'] for row in result['candidates']]
        assert len(tickers)==len(set(tickers))==service.CANDIDATES_PER_THEME==2
    finally:
        db.close()


def test_asts_insurance_first_does_not_starve_specific_themes(monkeypatch):
    from types import SimpleNamespace
    companies = [_mk_company(f"INS{i:02}",industry="Insurance") for i in range(15)]
    # Insert Z before A deliberately: richer exact evidence must win, not alphabet.
    companies += [_mk_company("ZSPACE",industry="Space Launch",tags=["Space Launch"]),
                  _mk_company("ALAUNCH",industry="Space Launch"),
                  _mk_company("BLAUNCH",industry="Space Launch"),
                  _mk_company("ZSAT",industry="Satellite",tags=["Satellite"]),
                  _mk_company("ASAT",industry="Satellite"),
                  _mk_company("BSAT",industry="Satellite"),
                  _mk_company("ZLAW",industry="Litigation Finance",tags=["Litigation Finance"]),
                  _mk_company("ASTS",industry="Satellite",tags=["Satellite","speculative","pre_fcf"])]
    with _company_db(*companies) as db:
        event = _llm_event(db)
        event.company_id = companies[-1].id
        db.commit()
        extraction=service.Extraction(themes=[service.Theme(exposure=exposure,direction="incierta",chain=[service.CausalStep(cause="Noticia ASTS: alegación no verificada",effect="Posible efecto indirecto por verificar")]) for exposure in ["Insurance","Space Launch","Satellite","Legal","Litigation Finance","Satellite"]])
        monkeypatch.setenv("SECOND_ORDER_LLM_ENABLED","1")
        monkeypatch.setattr(service,"reserve_llm_call",lambda *_:{"allowed":True})
        async def extract(*args,**kwargs):
            return extraction,SimpleNamespace(model="space-bunny-free")
        monkeypatch.setattr(service,"_extract_with_llm",extract)
        monkeypatch.setattr(service,"_jev_marker",lambda _:dict(direction=None,confidence=None,backend=None))
        result=service.analyze_second_order(db,event,use_llm=True)
        tickers=[row["ticker"] for row in result["candidates"]]
        assert tickers == ["ZSPACE","ZSAT","ZLAW","ALAUNCH","ASAT"]
        assert not any(t.startswith("INS") for t in tickers) and "ASTS" not in tickers
        assert len(tickers)==len(set(tickers))
        for exposure in ["Space Launch","Satellite","Litigation Finance"]:
            assert sum(row["exposure"]["value"]==exposure for row in result["candidates"])<=2
        assert result["mode"]=="llm" and result["source_verified"] is False
        assert result["warning"] and result["per_theme_limit"]==2 and result["limited_to"]==10
        assert all(row["reason"] and row["status"]=="hipótesis_no_verificada" for row in result["candidates"])
        assert result["candidates"][0]["selection_basis"]["score"]==3
        assert result["candidates"][-2]["selection_basis"]["score"]==1


def test_total_cap_remains_ten_with_many_specific_themes(monkeypatch):
    companies=[_mk_company(f"CO{i:02}",industry=f"Specific Industry {i//2}") for i in range(16)]
    with _company_db(*companies) as db:
        event=_llm_event(db)
        themes=[service.Theme(exposure=f"Specific Industry {i}",direction="incierta",chain=[service.CausalStep(cause="Source",effect="Hypothesis")]) for i in range(8)]
        monkeypatch.setattr(service,"_fallback",lambda _:service.Extraction(themes=themes))
        monkeypatch.setattr(service,"_jev_marker",lambda _:dict(direction=None,confidence=None,backend=None))
        result=service.analyze_second_order(db,event)
        assert len(result["candidates"])==10
        # Eight different themes each get one place before the first gets a second.
        assert len({row["exposure"]["value"] for row in result["candidates"][:8]})==8


def test_extraction_request_uses_registered_prompt_and_traces_it(monkeypatch):
    import asyncio

    import pytest

    from app.services import prompt_registry

    seen = []

    class Router:
        def resolve(self, request):
            seen.append(request)
            return "paid-model-x"  # corta antes de llamar al proveedor

    class Provider:
        name = "test"
        model_router = Router()

    monkeypatch.setattr(service, "create_llm_provider", lambda: Provider())
    with pytest.raises(RuntimeError, match="owner-approved"):
        asyncio.run(service._extract_with_llm("noticia"))
    resolved = prompt_registry.get_prompt("second_order_news_service", allow_remote=False)
    assert seen[0].messages[0].content == resolved.text
    assert seen[0].metadata == resolved.trace_metadata()
