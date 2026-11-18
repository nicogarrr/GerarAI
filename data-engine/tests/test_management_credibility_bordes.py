"""Bordes de management_credibility_service: import_call_claims (creacion y
dedup), reconcile con promesa sin metrica y con periodo sin ano, y el parser
estatico _target (sin numero y cada familia de cualificador).
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.entities import (
    Base,
    CallClaim,
    Company,
    FinancialFact,
    ManagementPromise,
    Transcript,
)
from app.services.management_credibility_service import ManagementCredibilityService


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _company(db: Session) -> Company:
    company = Company(
        ticker="MCO",
        name="MCO",
        exchange="NYSE",
        currency="USD",
        sector="S",
        industry="I",
        company_type="holding",
        valuation_model="unassigned",
        special_sources=[],
        special_risks=[],
        factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


def _claims(db: Session, company: Company) -> None:
    transcript = Transcript(company_id=company.id, title="Q4 call", period="Q4 2025")
    db.add(transcript)
    db.flush()
    db.add_all(
        [
            CallClaim(
                transcript_id=transcript.id,
                speaker="CEO",
                speaker_role="ceo",
                claim="Revenue at least €200 in FY2026",
                claim_type="guidance",
                metric="revenue",
                period="FY2026",
            ),
            CallClaim(
                transcript_id=transcript.id,
                speaker="CFO",
                speaker_role="cfo",
                claim="Margin up to 15.5 in FY2026",
                claim_type="commitment",
                metric="margin",
                period="FY2026",
            ),
            CallClaim(
                transcript_id=transcript.id,
                speaker="CEO",
                speaker_role="ceo",
                claim="Hola sin categoria",
                claim_type="other",
                metric=None,
                period=None,
            ),
        ]
    )
    db.commit()


def test_import_call_claims_crea_promesas_solo_de_tipos_objetivo(db):
    company = _company(db)
    _claims(db, company)
    created = ManagementCredibilityService().import_call_claims(db, company)
    assert len(created) == 2
    by_metric = {row.metric: row for row in created}
    assert by_metric["revenue"].operator == ">="
    assert by_metric["revenue"].target_value == Decimal("200")
    assert by_metric["margin"].operator == "<="
    assert by_metric["margin"].target_value == Decimal("15.5")
    for row in created:
        assert row.status == "open"
        assert row.evidence[0]["speaker"] in {"CEO", "CFO"}
        assert row.metadata_["source"] == "call_claim"


def test_import_call_claims_no_duplica_en_segunda_pasada(db):
    company = _company(db)
    _claims(db, company)
    service = ManagementCredibilityService()
    first = service.import_call_claims(db, company)
    second = service.import_call_claims(db, company)
    assert [row.id for row in second] == [row.id for row in first]
    assert db.query(ManagementPromise).filter_by(company_id=company.id).count() == 2


def test_reconcile_salta_promesas_sin_metrica(db):
    company = _company(db)
    service = ManagementCredibilityService()
    service.register(
        db,
        company,
        promise="Algo sin metrica",
        promise_date=date(2024, 2, 1),
        expected_period="FY2025",
        metric=None,
        operator=None,
        target_value=None,
        unit=None,
    )
    [promise] = service.reconcile(db, company)
    assert promise.status == "open"
    assert promise.actual_fact_id is None


def test_reconcile_periodo_sin_ano_casa_por_periodo_exacto(db):
    company = _company(db)
    fact = FinancialFact(
        company_id=company.id,
        metric="revenue",
        value=Decimal("120"),
        unit="USD",
        period="T3",
        fiscal_year=None,
        fiscal_quarter="Q3",
        source_type="filing",
    )
    db.add(fact)
    service = ManagementCredibilityService()
    service.register(
        db,
        company,
        promise="Revenue >= 100 en T3",
        promise_date=date(2024, 2, 1),
        expected_period="T3",
        metric="revenue",
        operator=">=",
        target_value=Decimal("100"),
        unit="USD",
    )
    [promise] = service.reconcile(db, company)
    assert promise.status == "met"
    assert promise.actual_value == Decimal("120")


def test_target_sin_numero_devuelve_none():
    assert ManagementCredibilityService._target("sin cifras aqui") == (None, None)


@pytest.mark.parametrize(
    ("text", "operator", "target"),
    [
        ("Revenue at least $200", ">=", "200"),
        ("margin up to 15.5", "<=", "15.5"),
        ("growth of about 10", "==", "10"),
        ("revenue 300", "==", "300"),
    ],
)
def test_target_operadores_segun_cualificador(text, operator, target):
    assert ManagementCredibilityService._target(text) == (operator, Decimal(target))


def test_reconcile_periodo_solo_ano_sin_fy_ni_trimestre(db):
    company = _company(db)
    fact = FinancialFact(
        company_id=company.id,
        metric="revenue",
        value=Decimal("120"),
        unit="USD",
        period="FY2025",
        fiscal_year=2025,
        fiscal_quarter="FY",
        source_type="filing",
    )
    db.add(fact)
    service = ManagementCredibilityService()
    service.register(
        db,
        company,
        promise="Revenue >= 100 en 2025",
        promise_date=date(2024, 2, 1),
        expected_period="2025",
        metric="revenue",
        operator=">=",
        target_value=Decimal("100"),
        unit="USD",
    )
    [promise] = service.reconcile(db, company)
    assert promise.status == "met"
    assert promise.actual_value == Decimal("120")


def test_target_ignora_ano_inicial_y_respeta_cualificador():
    # MEDIDO: antes devolvia ("==", 2026): el ano del encabezado se tomaba como
    # objetivo y el veredicto comparaba el hecho contra 2026.
    operator, target = ManagementCredibilityService._target(
        "For 2026, we expect revenue of at least $5 billion"
    )
    assert operator == ">="
    assert target == Decimal("5000000000")


@pytest.mark.parametrize(
    ("text", "target"),
    [
        ("Revenue at least $200 million in FY2026", "200000000"),
        ("capex of approximately $1.2 billion", "1200000000"),
        ("hasta 300 mil millones de deuda", "300000000000"),
        # Un billon espanol son 10^12, no 10^9 (billion ingles).
        ("deuda de 2 billones", "2000000000000"),
        ("buybacks above 750 thousand", "750000"),
        ("Revenue at least €200 in FY2026", "200"),
        # Sobrevive al mutante k->1: la k son miles.
        ("5k employees", "5000"),
        ("5 MILLION", "5000000"),
    ],
)
def test_target_escala_magnitudes(text, target):
    _operator, parsed = ManagementCredibilityService._target(text)
    assert parsed == Decimal(target)


@pytest.mark.parametrize(
    ("text", "operator", "target"),
    [
        ("al menos 200 millones", ">=", "200000000"),
        ("hasta 200 millones de usuarios", "<=", "200000000"),
        # 'más de'/'menos de' son estrictos en espanol.
        ("más de 5 mil millones de ingresos en 2026", ">", "5000000000"),
        ("menos de 300 mn de capex", "<", "300000000"),
        ("aproximadamente 10 million subscribers", "==", "10000000"),
        ("less than $300mn of capex", "<=", "300000000"),
        ("capex below $1.5bn in FY2027", "<=", "1500000000"),
    ],
)
def test_target_cualificadores_es_y_abreviaturas(text, operator, target):
    assert ManagementCredibilityService._target(text) == (operator, Decimal(target))


@pytest.mark.parametrize(
    ("text", "target"),
    [
        # Coma decimal ES.
        ("ingresos de 2,5 mil millones", "2500000000"),
        ("ingresos de 2,5 millones", "2500000"),
        # Punto de millares ES.
        ("ingresos de 1.500 millones", "1500000000"),
        # Coma de millares EN.
        ("a total of $1,200 million", "1200000000"),
        # Decimal EN intacto.
        ("margin up to 15.5", "15.5"),
    ],
)
def test_target_separadores_es_y_en(text, target):
    _operator, parsed = ManagementCredibilityService._target(text)
    assert parsed == Decimal(target)


@pytest.mark.parametrize(
    "text",
    [
        # El numero del formulario no es un objetivo.
        "10-K filed",
        # Regresion aceptada y declarada: un ano pelado sin cualificador ni
        # magnitud se descarta; 'deliver 2000 vehicles' queda sin objetivo
        # antes que inventarlo.
        "deliver 2000 vehicles",
    ],
)
def test_target_sin_objetivo_inventado(text):
    assert ManagementCredibilityService._target(text) == (None, None)


def test_target_cualificador_salva_ano_pelado():
    assert ManagementCredibilityService._target("deliver at least 2000 vehicles") == (
        ">=",
        Decimal("2000"),
    )


def test_target_salta_trimestre_sin_cualificador_delante():
    # El 3 de Q3 no es el objetivo; manda la cifra real.
    assert ManagementCredibilityService._target("Q3 revenue of $1.2 billion") == (
        "==",
        Decimal("1200000000"),
    )


def test_target_semestre_y_medio_ano_no_son_objetivo():
    assert ManagementCredibilityService._target("2H26 revenue at least $3bn") == (
        ">=",
        Decimal("3000000000"),
    )
    assert ManagementCredibilityService._target("H1 revenue of $5 billion") == (
        "==",
        Decimal("5000000000"),
    )


def test_target_cualificador_gana_a_cifra_previa_sin_cualificador():
    # Aunque aparezca despues, la cifra con cualificador manda sobre cualquier
    # numero previo pelado.
    assert ManagementCredibilityService._target(
        "In 2026 we expect approximately $5.5 billion"
    ) == ("==", Decimal("5500000000"))


def test_target_rango_no_es_un_objetivo():
    # "between $4 and $5 billion": un rango no cabe en (operador, objetivo);
    # sin objetivo declarado antes que un == contra el extremo inferior.
    assert ManagementCredibilityService._target("EBITDA between $4 and $5 billion") == (
        None,
        None,
    )


@pytest.mark.parametrize(
    ("text", "target"),
    [
        # FAV: el idioma de la magnitud decide el separador (x1000 de por medio).
        ("$2.145 billion", "2145000000"),
        ("$0.250", "0.250"),
        ("1.250 millones", "1250000000"),
        ("1,250 million", "1250000000"),
        # Dos separadores: el ultimo es el decimal.
        ("revenue of $1,234,567.89", "1234567.89"),
        ("ingresos de 1.234.567,89", "1234567.89"),
    ],
)
def test_target_separador_segun_idioma_de_la_magnitud(text, target):
    _operator, parsed = ManagementCredibilityService._target(text)
    assert parsed == Decimal(target)


def test_target_ambiguo_sin_magnitud_es_none():
    # "12.000": decimal EN o millares ES; sin magnitud no se inventa la escala.
    assert ManagementCredibilityService._target("12.000") == (None, None)


def test_parse_number_rechaza_basura():
    from app.services.management_credibility_service import _parse_number

    assert _parse_number("abc") is None


def test_target_salta_trimestre_suelto():
    # Mata el mutante que quita el salto de FY/Q/H suelto: el 3 de 'Q 3' no es
    # el objetivo.
    assert ManagementCredibilityService._target("Q 3 revenue of 100") == (
        "==",
        Decimal("100"),
    )


def test_target_semestre_pegado_sin_cualificador():
    # Mata el mutante que quita _HALF_PREFIX_RE: el 2 de '2H26' no es el
    # objetivo aunque no haya cualificador que mande.
    assert ManagementCredibilityService._target("2H26 revenue of $3 billion") == (
        "==",
        Decimal("3000000000"),
    )


def test_target_cualificador_manda_sobre_cifra_previa_sin_cualificador():
    # Mata el mutante de 'el cualificador manda': 200 tiendas no es el
    # objetivo de la promesa de ingresos.
    assert ManagementCredibilityService._target(
        "200 stores and revenue at least $5 billion"
    ) == (">=", Decimal("5000000000"))


def test_target_ignora_el_digito_del_trimestre():
    # El 3 de "Q3" no es el objetivo; la cifra real es la de los satelites.
    assert ManagementCredibilityService._target(
        "In Q3 2026 we will launch 3 satellites"
    ) == ("==", Decimal("3"))


def test_target_ano_con_cualificador_si_cuenta():
    # Un ano solo se descarta cuando no lleva cualificador ni magnitud: una
    # cifra explicita tras 'above' es el objetivo aunque parezca ano.
    operator, target = ManagementCredibilityService._target("above 2026 units")
    assert operator == ">="
    assert target == Decimal("2026")


def test_import_normaliza_la_metrica(db):
    # MEDIDO: claim.metric cruda ('Revenue') se guardaba tal cual y nunca casaba
    # con el hecho ('revenue'), dejando la promesa abierta para siempre.
    company = _company(db)
    transcript = Transcript(company_id=company.id, title="Q4 call", period="Q4 2025")
    db.add(transcript)
    db.flush()
    db.add(
        CallClaim(
            transcript_id=transcript.id,
            speaker="CEO",
            speaker_role="ceo",
            claim="Revenue at least 200 in FY2026",
            claim_type="guidance",
            metric=" Revenue ",
            period="FY2026",
        )
    )
    db.commit()
    [row] = ManagementCredibilityService().import_call_claims(db, company)
    assert row.metric == "revenue"


def test_reconcile_ignora_hechos_no_reportados(db):
    # Un hecho estimado/derivado no puede dar un veredicto: la promesa queda
    # abierta hasta que exista la cifra reportada.
    company = _company(db)
    fact = FinancialFact(
        company_id=company.id,
        metric="revenue",
        value=Decimal("120"),
        unit="USD",
        period="FY2025",
        fiscal_year=2025,
        fiscal_quarter="FY",
        source_type="estimated",
        is_reported=False,
    )
    db.add(fact)
    service = ManagementCredibilityService()
    service.register(
        db,
        company,
        promise="Revenue >= 100 en FY2025",
        promise_date=date(2024, 2, 1),
        expected_period="FY2025",
        metric="revenue",
        operator=">=",
        target_value=Decimal("100"),
        unit="USD",
    )
    [promise] = service.reconcile(db, company)
    assert promise.status == "open"
    assert promise.actual_fact_id is None


def test_reconcile_aproximado_dentro_del_cinco_porciento_es_met(db):
    company = _company(db)
    fact = FinancialFact(
        company_id=company.id,
        metric="revenue",
        value=Decimal("103"),
        unit="USD",
        period="FY2025",
        fiscal_year=2025,
        fiscal_quarter="FY",
        source_type="filing",
    )
    db.add(fact)
    service = ManagementCredibilityService()
    service.register(
        db,
        company,
        promise="Revenue of approximately 100 in FY2025",
        promise_date=date(2024, 2, 1),
        expected_period="FY2025",
        metric="revenue",
        operator="==",
        target_value=Decimal("100"),
        unit="USD",
        approximate=True,
    )
    [promise] = service.reconcile(db, company)
    assert promise.status == "met"


def test_reconcile_igual_pelada_dentro_del_cinco_porciento_es_partial(db):
    # Sin cualificador aproximado, "==" no es 'met' por cercania: la cifra
    # exacta o parcial (auditoria FAV: 'Revenue of $5 billion' con 4,8 mil
    # millones no puede salir cumplida).
    company = _company(db)
    fact = FinancialFact(
        company_id=company.id,
        metric="revenue",
        value=Decimal("103"),
        unit="USD",
        period="FY2025",
        fiscal_year=2025,
        fiscal_quarter="FY",
        source_type="filing",
    )
    db.add(fact)
    service = ManagementCredibilityService()
    service.register(
        db,
        company,
        promise="Revenue of 100 in FY2025",
        promise_date=date(2024, 2, 1),
        expected_period="FY2025",
        metric="revenue",
        operator="==",
        target_value=Decimal("100"),
        unit="USD",
    )
    [promise] = service.reconcile(db, company)
    assert promise.status == "partial"


def test_reconcile_aproximado_fuera_del_cinco_porciento_es_missed(db):
    company = _company(db)
    fact = FinancialFact(
        company_id=company.id,
        metric="revenue",
        value=Decimal("90"),
        unit="USD",
        period="FY2025",
        fiscal_year=2025,
        fiscal_quarter="FY",
        source_type="filing",
    )
    db.add(fact)
    service = ManagementCredibilityService()
    service.register(
        db,
        company,
        promise="Revenue of approximately 100 in FY2025",
        promise_date=date(2024, 2, 1),
        expected_period="FY2025",
        metric="revenue",
        operator="==",
        target_value=Decimal("100"),
        unit="USD",
        approximate=True,
    )
    [promise] = service.reconcile(db, company)
    assert promise.status == "missed"


def test_import_marca_aproximada_solo_con_cualificador_aproximado(db):
    company = _company(db)
    transcript = Transcript(company_id=company.id, title="Q4 call", period="Q4 2025")
    db.add(transcript)
    db.flush()
    db.add_all(
        [
            CallClaim(
                transcript_id=transcript.id,
                speaker="CEO",
                speaker_role="ceo",
                claim="Revenue of about 100 in FY2026",
                claim_type="guidance",
                metric="revenue",
                period="FY2026",
            ),
            CallClaim(
                transcript_id=transcript.id,
                speaker="CFO",
                speaker_role="cfo",
                claim="Revenue of 100 in FY2026",
                claim_type="guidance",
                metric="revenue",
                period="FY2026",
            ),
        ]
    )
    db.commit()
    created = ManagementCredibilityService().import_call_claims(db, company)
    by_promise = {row.promise: row for row in created}
    assert by_promise["Revenue of about 100 in FY2026"].metadata_["approximate"] is True
    assert by_promise["Revenue of 100 in FY2026"].metadata_["approximate"] is False


def test_target_decimal_con_punto_y_magnitud_es():
    # Magnitud espanola con decimal EN: el punto no siempre es de millares.
    assert ManagementCredibilityService._target("margen de 15.5 millones") == (
        "==",
        Decimal("15500000"),
    )
