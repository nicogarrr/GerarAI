"""Segunda tanda de bordes de screener_service: guardas puras de SafeFormula,
guardas de CustomMetricService.create, create_screen/claim_screen_name, poda
del cache de cobertura, re-run que desactiva matches (con alertas DESACTIVADAS:
el camino ReviewAlertService.emit_alert queda fuera de alcance a proposito),
run() con definicion rota, y helpers estaticos.
"""

from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import (
    CalculatedMetric,
    Company,
    CustomMetricDefinition,
    FinancialFact,
    SavedScreenMatch,
    Tenant,
)
from app.services import screener_service as screener_module
from app.services.screener_service import (
    CustomMetricService,
    Observation,
    SafeFormula,
    ScreenerService,
)


def _company(ticker: str) -> Company:
    return Company(
        ticker=ticker,
        name=f"{ticker} Co",
        exchange="TEST",
        currency="USD",
        sector="Test",
        industry="Test",
        company_type="standard",
        valuation_model="standard_dcf",
        special_sources=[],
        special_risks=[],
        factor_tags=[],
    )


def _db_with_tenant(external_id: str = "bordes2"):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    tenant = Tenant(external_id=external_id, name=external_id)
    db.add(tenant)
    db.flush()
    db.info["tenant_id"] = tenant.id
    return engine, db, tenant


def test_formula_demasiado_larga_rechazada():
    with pytest.raises(ValueError, match="supera los 1000 caracteres"):
        SafeFormula("1+" * 500 + "1")


def test_constante_no_numerica_rechazada():
    with pytest.raises(ValueError, match="Solo se admiten constantes numéricas"):
        SafeFormula("'abc'")


def test_nombre_de_metrica_invalido_rechazado():
    with pytest.raises(ValueError, match="Nombre de métrica no válido: Foo"):
        SafeFormula("Foo")


def test_operador_binario_no_permitido_rechazado():
    with pytest.raises(ValueError, match="Operador de fórmula no permitido"):
        SafeFormula("pe_ratio << 1")


def test_operador_unario_no_permitido_rechazado():
    with pytest.raises(ValueError, match="Operador unario de fórmula no permitido"):
        SafeFormula("~pe_ratio")


def test_kwargs_no_admitidos():
    with pytest.raises(ValueError, match="no admite argumentos con nombre"):
        SafeFormula("min(pe_ratio, otro=1)")


def test_elemento_compare_no_permitido():
    with pytest.raises(ValueError, match="Elemento de fórmula Compare no permitido"):
        SafeFormula("pe_ratio < 5")


def test_literal_infinito_marca_fuera_de_rango_y_evaluacion_no_finita():
    formula = SafeFormula("1e999")
    assert formula.out_of_range is True
    with pytest.raises(ValueError, match="fuera de rango"):
        SafeFormula.reject_out_of_range("1e999")
    with pytest.raises(ValueError, match="resultado de la fórmula no es finito"):
        formula.evaluate({})


def test_literal_cero_por_notacion_cientifica_marca_fuera_de_rango():
    assert SafeFormula("1e-400").out_of_range is True


def test_exponente_sobre_el_limite_rechazado():
    with pytest.raises(ValueError, match="exponente de la fórmula supera el límite seguro"):
        SafeFormula("pe_ratio ** 11").evaluate({"pe_ratio": Decimal("2")})


def test_metric_key_no_snake_case_rechazada():
    _engine, db, _tenant = _db_with_tenant()
    with db:
        with pytest.raises(ValueError, match="lower-case snake_case"):
            CustomMetricService().create(
                db,
                metric_key="ROIC Spread",
                name="x",
                formula="roic - wacc",
                unit="decimal",
                description="",
            )


def test_metrica_autorreferente_rechazada():
    _engine, db, _tenant = _db_with_tenant()
    with db:
        with pytest.raises(ValueError, match="no puede referirse a sí misma"):
            CustomMetricService().create(
                db,
                metric_key="roic_spread",
                name="x",
                formula="roic_spread + 1",
                unit="decimal",
                description="",
            )


def test_nueva_version_desactiva_la_definicion_anterior():
    _engine, db, _tenant = _db_with_tenant()
    with db:
        service = CustomMetricService()
        first = service.create(
            db,
            metric_key="roic_spread",
            name="v1",
            formula="roic - wacc",
            unit="decimal",
            description="",
        )
        second = service.create(
            db,
            metric_key="ROIC_SPREAD",
            name="v2",
            formula="roic + wacc",
            unit="decimal",
            description="",
        )
        assert second.version == 2
        assert first.active is False
        assert second.active is True


def test_filtro_sin_criterios_rechazado():
    _engine, db, _tenant = _db_with_tenant()
    with db:
        with pytest.raises(ValueError, match="al menos un criterio"):
            ScreenerService().create_screen(
                db,
                name="Value",
                description="",
                criteria=[],
                ranking_formula=None,
                ranking_direction="desc",
                alerts_enabled=False,
            )


def test_ranking_direction_invalida_rechazada():
    _engine, db, _tenant = _db_with_tenant()
    with db:
        with pytest.raises(ValueError, match="must be asc or desc"):
            ScreenerService().create_screen(
                db,
                name="Value",
                description="",
                criteria=[{"left": "1", "operator": ">", "right": "0"}],
                ranking_formula=None,
                ranking_direction="sideways",
                alerts_enabled=False,
            )


def test_nombre_vacio_rechazado():
    _engine, db, _tenant = _db_with_tenant()
    with db:
        with pytest.raises(ValueError, match="El nombre no puede estar vacío"):
            ScreenerService().claim_screen_name(db, "   ")


def test_nombre_activo_duplicado_choca():
    _engine, db, _tenant = _db_with_tenant()
    with db:
        service = ScreenerService()
        service.create_screen(
            db,
            name="Value",
            description="",
            criteria=[{"left": "1", "operator": ">", "right": "0"}],
            ranking_formula=None,
            ranking_direction="desc",
            alerts_enabled=False,
        )
        with pytest.raises(ValueError, match="Ya existe un filtro con ese nombre"):
            service.claim_screen_name(db, "Value")


def test_nombre_archivado_se_renombra_y_se_reusa():
    _engine, db, _tenant = _db_with_tenant()
    with db:
        service = ScreenerService()
        screen = service.create_screen(
            db,
            name="Value",
            description="",
            criteria=[{"left": "1", "operator": ">", "right": "0"}],
            ranking_formula=None,
            ranking_direction="desc",
            alerts_enabled=False,
        )
        screen.active = False
        db.commit()
        screen_id = screen.id
        claimed = service.claim_screen_name(db, "Value")
        assert claimed == "Value"
        db.refresh(screen)
        assert screen.name == f"Value [archivado #{screen_id}]"


def test_nombre_propio_excluido_no_choca():
    _engine, db, _tenant = _db_with_tenant()
    with db:
        service = ScreenerService()
        screen = service.create_screen(
            db,
            name="Value",
            description="",
            criteria=[{"left": "1", "operator": ">", "right": "0"}],
            ranking_formula=None,
            ranking_direction="desc",
            alerts_enabled=False,
        )
        claimed = service.claim_screen_name(db, "Value", exclude_id=screen.id)
        assert claimed == "Value"


def test_carrera_de_nombre_duplicado_se_traduce_a_value_error(monkeypatch):
    _engine, db, _tenant = _db_with_tenant()

    def commit_roto(self):
        raise IntegrityError("INSERT INTO saved_screens", {}, Exception("uq_saved_screen_tenant_name"))

    with db:
        monkeypatch.setattr(Session, "commit", commit_roto)
        with pytest.raises(ValueError, match="Ya existe un filtro con ese nombre"):
            ScreenerService().create_screen(
                db,
                name="Value",
                description="",
                criteria=[{"left": "1", "operator": ">", "right": "0"}],
                ranking_formula=None,
                ranking_direction="desc",
                alerts_enabled=False,
            )
        monkeypatch.undo()
        db.rollback()


def test_cache_de_cobertura_se_poda_con_mas_de_128_tenants():
    _engine, db, tenant = _db_with_tenant("tenant-podado")
    snapshot = dict(screener_module._METRIC_COVERAGE_CACHE)
    try:
        screener_module._METRIC_COVERAGE_CACHE.clear()
        for i in range(129):
            screener_module._METRIC_COVERAGE_CACHE[f"tenant-{i}"] = (0.0, [])
        with db:
            ScreenerService().metric_coverage(db)
        assert len(screener_module._METRIC_COVERAGE_CACHE) == 1
        assert tenant.id in screener_module._METRIC_COVERAGE_CACHE
    finally:
        screener_module._METRIC_COVERAGE_CACHE.clear()
        screener_module._METRIC_COVERAGE_CACHE.update(snapshot)


def test_match_obsoleto_se_desactiva_en_el_siguiente_run():
    _engine, db, _tenant = _db_with_tenant()
    with db:
        service = ScreenerService()
        company = _company("CMPD")
        db.add(company)
        db.flush()
        metric = CalculatedMetric(
            company_id=company.id,
            metric="roic",
            value=Decimal("0.18"),
            unit="decimal",
            period="FY2025",
            fiscal_year=2025,
            status="ok",
            definition_version="test-v1",
            formula="roic",
            source_fact_ids=[],
            calculation_trace={},
            confidence=Decimal("0.9"),
        )
        db.add(metric)
        screen = service.create_screen(
            db,
            name="Calidad",
            description="",
            criteria=[{"left": "roic", "operator": ">", "right": "0.05"}],
            ranking_formula=None,
            ranking_direction="desc",
            alerts_enabled=False,
        )
        first = service.run_saved(db, screen)
        assert first["new_match_company_ids"] == [company.id]
        match = db.scalar(select(SavedScreenMatch).where(SavedScreenMatch.saved_screen_id == screen.id))
        assert match.active is True

        metric.value = Decimal("0.01")
        db.commit()
        second = service.run_saved(db, screen)
        assert second["new_match_company_ids"] == []
        db.refresh(match)
        assert match.active is False


def test_run_ignora_definicion_de_metrica_con_formula_rota():
    _engine, db, tenant = _db_with_tenant()
    with db:
        db.add(
            CustomMetricDefinition(
                tenant_id=tenant.id,
                metric_key="rota",
                name="Rota",
                formula="a << b",
                unit="decimal",
                description="",
                version=1,
                active=True,
                metadata_={},
            )
        )
        db.commit()
        response = ScreenerService().run(
            db,
            criteria=[{"left": "1", "operator": ">", "right": "0"}],
        )
        assert response["results"] == []


def test_observations_combina_metricas_calculadas_y_facts():
    _engine, db, _tenant = _db_with_tenant()
    with db:
        company = _company("OBS")
        db.add(company)
        db.flush()
        db.add(
            CalculatedMetric(
                company_id=company.id,
                metric="roic",
                value=Decimal("0.18"),
                unit="decimal",
                period="FY2025",
                fiscal_year=2025,
                status="ok",
                definition_version="test-v1",
                formula="roic",
                source_fact_ids=[],
                calculation_trace={},
                confidence=Decimal("0.9"),
            )
        )
        for year, value in ((2024, "10"), (2025, "20")):
            db.add(
                FinancialFact(
                    company_id=company.id,
                    metric="free_cash_flow",
                    value=Decimal(value),
                    unit="USD",
                    period=f"FY{year}",
                    fiscal_year=year,
                    fiscal_quarter="FY",
                    source_type="sec_filing",
                    confidence=Decimal("0.95"),
                )
            )
        db.commit()
        observations = ScreenerService()._observations(db, company)
        assert observations["roic"].value == Decimal("0.18")
        assert observations["free_cash_flow"].value == Decimal("20")


def test_newest_per_year_salta_filas_sin_fiscal_year():
    rows = [
        FinancialFact(metric="x", value=Decimal("1"), fiscal_year=None),
        FinancialFact(metric="x", value=Decimal("2"), fiscal_year=2020),
    ]
    by_year = ScreenerService._newest_per_year(rows)
    assert list(by_year) == [2020]
    assert by_year[2020].value == Decimal("2")


def test_ratio_cagr_devuelve_none_con_denominador_cero():
    numerators = [
        FinancialFact(
            metric="fcf",
            value=Decimal("10"),
            fiscal_year=2020,
            fiscal_quarter="FY",
            confidence=Decimal("0.9"),
        ),
        FinancialFact(
            metric="fcf",
            value=Decimal("20"),
            fiscal_year=2025,
            fiscal_quarter="FY",
            confidence=Decimal("0.9"),
        ),
    ]
    denominators = [
        FinancialFact(
            metric="shares",
            value=Decimal("0"),
            fiscal_year=2020,
            fiscal_quarter="FY",
            confidence=Decimal("0.9"),
        ),
        FinancialFact(
            metric="shares",
            value=Decimal("10"),
            fiscal_year=2025,
            fiscal_quarter="FY",
            confidence=Decimal("0.9"),
        ),
    ]
    assert ScreenerService()._ratio_cagr(numerators, denominators) is None


def test_custom_metrics_unevaluable_se_omite_con_warning(caplog):
    observations = {
        "roic": Observation(Decimal("0"), Decimal("0.9"), None, "FY2025", "test", []),
    }
    definition = CustomMetricDefinition(
        metric_key="inverse_roic",
        name="Inverse",
        formula="1 / roic",
        unit="decimal",
        description="",
        version=1,
        active=True,
        metadata_={},
    )
    ScreenerService._custom_metrics(observations, [definition])
    assert "inverse_roic" not in observations
    assert "inverse_roic" in caplog.text


def test_criterion_sin_valor_derecho_rechazado():
    with pytest.raises(ValueError, match="Cada criterio necesita valor izquierdo"):
        ScreenerService._criterion({"left": "pe_ratio", "operator": ">", "right": ""})


def test_observations_metrica_duplicada_gana_el_ano_reciente():
    _engine, db, _tenant = _db_with_tenant()
    with db:
        company = _company("DUP")
        db.add(company)
        db.flush()
        for year, value in ((2025, "0.18"), (2024, "0.10")):
            db.add(
                CalculatedMetric(
                    company_id=company.id,
                    metric="roic",
                    value=Decimal(value),
                    unit="decimal",
                    period=f"FY{year}",
                    fiscal_year=year,
                    status="ok",
                    definition_version="test-v1",
                    formula="roic",
                    source_fact_ids=[],
                    calculation_trace={},
                    confidence=Decimal("0.9"),
                )
            )
        db.commit()
        observations = ScreenerService()._observations(db, company)
        assert observations["roic"].value == Decimal("0.18")


def test_ratio_cagr_none_cuando_el_cagr_sintetico_no_es_valido():
    numerators = [
        FinancialFact(
            metric="fcf",
            value=Decimal("-10"),
            fiscal_year=2020,
            fiscal_quarter="FY",
            confidence=Decimal("0.9"),
        ),
        FinancialFact(
            metric="fcf",
            value=Decimal("20"),
            fiscal_year=2025,
            fiscal_quarter="FY",
            confidence=Decimal("0.9"),
        ),
    ]
    denominators = [
        FinancialFact(
            metric="shares",
            value=Decimal("10"),
            fiscal_year=2020,
            fiscal_quarter="FY",
            confidence=Decimal("0.9"),
        ),
        FinancialFact(
            metric="shares",
            value=Decimal("10"),
            fiscal_year=2025,
            fiscal_quarter="FY",
            confidence=Decimal("0.9"),
        ),
    ]
    assert ScreenerService()._ratio_cagr(numerators, denominators) is None
