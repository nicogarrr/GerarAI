"""Safe custom metrics and persistent, evidence-aware company screens."""

from __future__ import annotations

import ast
import logging
import operator
import re
import threading
import time
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, DecimalException
from typing import Any

import sqlalchemy as sa
from sqlalchemy import desc, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased

_METRIC_COVERAGE_CACHE: dict[int, tuple[float, list[str]]] = {}
_METRIC_COVERAGE_LOCK = threading.Lock()
_METRIC_COVERAGE_TTL_SECONDS = 600.0
from app.core.tenancy import tenant_filters
from app.models import (
    CalculatedMetric,
    Company,
    CustomMetricDefinition,
    FinancialFact,
    SavedScreen,
    SavedScreenMatch,
)
from app.services.review_alert_service import ReviewAlertService
from app.services.screener_context_metrics import context_metrics_with_data, context_observations

logger = logging.getLogger(__name__)

DUPLICATE_SCREEN_NAME = "Ya existe un filtro con ese nombre"
SCREEN_NAME_MAX = 240

KEY_RE = re.compile(r"^[a-z][a-z0-9_]{1,159}$")
COMPARATORS = {
    ">": operator.gt,
    ">=": operator.ge,
    "<": operator.lt,
    "<=": operator.le,
    "==": operator.eq,
    "!=": operator.ne,
}


class MissingVariables(ValueError):
    def __init__(self, names: set[str]) -> None:
        self.names = names
        super().__init__(f"Missing variables: {', '.join(sorted(names))}")


CRITERION_UNEVALUABLE_REASON = "No se puede evaluar la fórmula con estos valores"


class SafeFormula:
    FUNCTIONS = {"min": min, "max": max, "abs": abs}
    BINARY = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.Pow: operator.pow,
        ast.Mod: operator.mod,
    }
    UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}

    def __init__(self, expression: str) -> None:
        if len(expression) > 1000:
            raise ValueError("La fórmula supera los 1000 caracteres")
        self.expression = expression
        self.names: set[str] = set()
        # Un anidamiento profundo dentro de los 1000 caracteres («------1»,
        # «-(-(-(…)))») agota la pila al parsear o validar: RecursionError no es
        # ValueError y los llamadores solo capturan ValueError, asi que crear la
        # metrica o el screen respondia 500 en vez de un error de formula.
        try:
            self.tree = ast.parse(expression, mode="eval")
            self._validate(self.tree)
        except SyntaxError as exc:
            raise ValueError("Sintaxis de fórmula no válida") from exc
        except RecursionError as exc:
            raise ValueError("La fórmula está demasiado anidada") from exc

    def _validate(self, node: ast.AST) -> None:
        if isinstance(node, ast.Expression):
            self._validate(node.body)
        elif isinstance(node, ast.Constant):
            if not isinstance(node.value, (int, float)) or isinstance(node.value, bool):
                raise ValueError("Solo se admiten constantes numéricas")
        elif isinstance(node, ast.Name):
            if not KEY_RE.fullmatch(node.id):
                raise ValueError(f"Nombre de métrica no válido: {node.id}")
            self.names.add(node.id)
        elif isinstance(node, ast.BinOp):
            if type(node.op) not in self.BINARY:
                raise ValueError("Operador de fórmula no permitido")
            self._validate(node.left)
            self._validate(node.right)
        elif isinstance(node, ast.UnaryOp):
            if type(node.op) not in self.UNARY:
                raise ValueError("Operador unario de fórmula no permitido")
            self._validate(node.operand)
        elif isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in self.FUNCTIONS:
                raise ValueError("Solo se admiten las funciones min, max y abs")
            if node.keywords:
                raise ValueError("La fórmula no admite argumentos con nombre")
            # Aridad validada al construir: antes min()/abs(1,2)/min(1) pasaban la
            # validacion y fallaban al evaluar con TypeError, que los llamadores
            # (solo capturan ValueError) no manejaban.
            if node.func.id == "abs" and len(node.args) != 1:
                raise ValueError("abs requiere exactamente 1 argumento")
            if node.func.id in ("min", "max") and len(node.args) < 2:
                raise ValueError(f"{node.func.id} requiere al menos 2 argumentos")
            for argument in node.args:
                self._validate(argument)
        else:
            raise ValueError(f"Elemento de fórmula {type(node).__name__} no permitido")

    def evaluate(self, values: dict[str, Decimal]) -> Decimal:
        missing = self.names - values.keys()
        if missing:
            raise MissingVariables(missing)
        try:
            result = self._evaluate(self.tree.body, values)
            if not result.is_finite():
                raise ValueError("El resultado de la fórmula no es finito")
            return result
        # Cualquier señal decimal se normaliza a ValueError: no solo la
        # division por cero, tambien un Overflow de exponentes anidados (cada
        # `**` bajo el limite) que supera el Emax del contexto. Los llamadores
        # (criterios, ranking, metricas personalizadas) solo capturan
        # ValueError: antes un decimal.Overflow tumbaba la ejecucion entera.
        except (DecimalException, ZeroDivisionError) as exc:
            raise ValueError("No se puede evaluar la fórmula con estos valores") from exc
        except RecursionError as exc:
            raise ValueError("La fórmula está demasiado anidada") from exc

    def _evaluate(self, node: ast.AST, values: dict[str, Decimal]) -> Decimal:
        if isinstance(node, ast.Constant):
            return Decimal(str(node.value))
        if isinstance(node, ast.Name):
            return values[node.id]
        if isinstance(node, ast.BinOp):
            left = self._evaluate(node.left, values)
            right = self._evaluate(node.right, values)
            if isinstance(node.op, ast.Pow) and abs(right) > 10:
                raise ValueError("El exponente de la fórmula supera el límite seguro")
            return self.BINARY[type(node.op)](left, right)
        if isinstance(node, ast.UnaryOp):
            return self.UNARY[type(node.op)](self._evaluate(node.operand, values))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            arguments = [self._evaluate(argument, values) for argument in node.args]
            return self.FUNCTIONS[node.func.id](*arguments)
        raise ValueError("Elemento de fórmula no válido")


@dataclass
class Observation:
    value: Decimal
    confidence: Decimal
    as_of: date | datetime | None
    period: str
    source: str
    source_ids: list[int]


class CustomMetricService:
    def create(
        self,
        db: Session,
        *,
        metric_key: str,
        name: str,
        formula: str,
        unit: str,
        description: str,
    ) -> CustomMetricDefinition:
        metric_key = metric_key.strip().lower()
        if not KEY_RE.fullmatch(metric_key):
            raise ValueError("metric_key must be lower-case snake_case")
        parsed = SafeFormula(formula)
        if metric_key in parsed.names:
            raise ValueError("Una métrica personalizada no puede referirse a sí misma")
        previous = db.scalar(
            select(CustomMetricDefinition)
            .where(CustomMetricDefinition.metric_key == metric_key)
            .order_by(desc(CustomMetricDefinition.version))
            .limit(1)
        )
        if previous:
            previous.active = False
        definition = CustomMetricDefinition(
            metric_key=metric_key,
            name=name.strip(),
            formula=formula.strip(),
            unit=unit.strip() or "decimal",
            description=description.strip(),
            version=previous.version + 1 if previous else 1,
            active=True,
            metadata_={"dependencies": sorted(parsed.names), "engine": "safe_ast_v1"},
        )
        db.add(definition)
        db.commit()
        db.refresh(definition)
        return definition

    @staticmethod
    def active(db: Session) -> list[CustomMetricDefinition]:
        return list(
            db.scalars(
                select(CustomMetricDefinition)
                .where(CustomMetricDefinition.active.is_(True))
                .order_by(CustomMetricDefinition.metric_key)
            ).all()
        )


def _distinct_facts_metrics(db: Session) -> list[str]:
    """Metricas de facts con datos, sin barrer la porcion del tenant.

    El distinct ORM leia todas las filas de facts del tenant (medido 150 ms
    caliente en el laboratorio con 1M filas/tenant; en prod, parte del coste
    en frio de 15-18 s de metric-coverage). Hay ~decenas de metricas: la CTE
    recursiva salta duplicados con una sonda por metrica sobre
    ix_facts_tenant_metric (0122). Portable (subconsulta escalar, sin
    LATERAL); mismo conjunto exacto que el distinct. Medido: 150 ms -> 4 ms.
    """
    tenant_id = db.info.get("tenant_id")
    if tenant_id is None:
        # Dev/test legado sin contexto: mismo resultado por la via ORM.
        return list(
            db.scalars(
                select(FinancialFact.metric).where(*tenant_filters(db, FinancialFact)).distinct()
            ).all()
        )
    # nosemgrep: gerarai-tenant-raw-sql -- ambas lecturas filtran tenant_id=:tenant; bind desde db.info, aislamiento probado en test_cold_endpoints_skip_scan.
    sql = sa.text("""
        WITH RECURSIVE m(metric) AS (
          SELECT * FROM (SELECT metric FROM financial_facts WHERE tenant_id = :tenant ORDER BY metric LIMIT 1)
          UNION ALL
          SELECT (SELECT t2.metric FROM financial_facts t2
                  WHERE t2.tenant_id = :tenant AND t2.metric > m.metric
                  ORDER BY t2.metric LIMIT 1)
          FROM m WHERE m.metric IS NOT NULL
        )
        SELECT metric FROM m WHERE metric IS NOT NULL
    """)
    return [row[0] for row in db.execute(sql, {"tenant": tenant_id}).all()]


class ScreenerService:
    def create_screen(
        self,
        db: Session,
        *,
        name: str,
        description: str,
        criteria: list[dict[str, Any]],
        ranking_formula: str | None,
        ranking_direction: str,
        alerts_enabled: bool,
    ) -> SavedScreen:
        if not criteria:
            raise ValueError("El filtro necesita al menos un criterio")
        normalized = [self._criterion(item) for item in criteria]
        clean_name = self.claim_screen_name(db, name)
        if ranking_formula:
            SafeFormula(ranking_formula)
        if ranking_direction not in {"asc", "desc"}:
            raise ValueError("ranking_direction must be asc or desc")
        screen = SavedScreen(
            name=clean_name,
            description=description.strip(),
            criteria=normalized,
            ranking_formula=ranking_formula.strip() if ranking_formula else None,
            ranking_direction=ranking_direction,
            alerts_enabled=alerts_enabled,
            active=True,
            metadata_={"criteria_version": 1, "formula_engine": "safe_ast_v1"},
        )
        db.add(screen)
        try:
            db.commit()
        except IntegrityError as exc:
            # Carrera con otra petición que guardó el mismo nombre a la vez.
            db.rollback()
            raise ValueError(DUPLICATE_SCREEN_NAME) from exc
        db.refresh(screen)
        return screen

    def claim_screen_name(self, db: Session, name: str, *, exclude_id: int | None = None) -> str:
        """Valida y reserva ``name`` para un filtro activo del tenant.

        ``uq_saved_screen_tenant_name`` cubre también los filtros archivados
        (el borrado es lógico para conservar historial y alertas). Un filtro
        archivado libera su nombre: se renombra con un sufijo «[archivado #id]».
        Un filtro activo con el mismo nombre es un conflicto (ValueError).
        """
        clean = name.strip()
        if not clean:
            raise ValueError("El nombre no puede estar vacío")
        holders = db.scalars(
            select(SavedScreen).where(SavedScreen.name == clean, *tenant_filters(db, SavedScreen))
        ).all()
        for holder in holders:
            if holder.id == exclude_id:
                continue
            if holder.active:
                raise ValueError(DUPLICATE_SCREEN_NAME)
            suffix = f" [archivado #{holder.id}]"
            holder.name = clean[: SCREEN_NAME_MAX - len(suffix)] + suffix
        db.flush()
        return clean

    def metric_coverage(self, db: Session) -> list[str]:
        """Metric names at least one company has data for.

        Drives the screener UI suggestions: a name nobody has data for
        (typo, metric never ingested) can only produce the "every company is
        missing it" outcome, so offering it in the datalist sets the user up
        to fail. Mirrors what run() tracks as names_with_data: calculated
        metrics with a value plus raw financial facts.

        Tres agregaciones (calculated metrics, facts, contexto) sobre tablas
        grandes: en frio tarda >15 s en prod (medido 15,8 s). Se cachea por
        tenant unos minutos: las sugerencias del datalist no necesitan
        frescura en tiempo real.
        """
        tenant = db.info.get("tenant_id")
        with _METRIC_COVERAGE_LOCK:
            cached = _METRIC_COVERAGE_CACHE.get(tenant)
            if cached and time.monotonic() - cached[0] < _METRIC_COVERAGE_TTL_SECONDS:
                return list(cached[1])
        result = self._metric_coverage_uncached(db)
        with _METRIC_COVERAGE_LOCK:
            if len(_METRIC_COVERAGE_CACHE) > 128:
                _METRIC_COVERAGE_CACHE.clear()
            _METRIC_COVERAGE_CACHE[tenant] = (time.monotonic(), result)
        return list(result)

    def _metric_coverage_uncached(self, db: Session) -> list[str]:
        calculated = set(
            db.scalars(
                select(CalculatedMetric.metric)
                .where(
                    CalculatedMetric.value.is_not(None),
                    CalculatedMetric.status == "ok",
                    *tenant_filters(db, CalculatedMetric),
                )
                .distinct()
            ).all()
        )
        facts = set(_distinct_facts_metrics(db))
        return sorted(calculated | facts | set(context_metrics_with_data(db)))

    def run_saved(self, db: Session, screen: SavedScreen) -> dict[str, Any]:
        response = self.run(
            db,
            criteria=screen.criteria,
            ranking_formula=screen.ranking_formula,
            ranking_direction=screen.ranking_direction,
        )
        now = datetime.now(UTC)
        matched_ids = {row["company_id"] for row in response["results"] if row["matched"]}
        existing = {
            row.company_id: row
            for row in db.scalars(
                select(SavedScreenMatch).where(SavedScreenMatch.saved_screen_id == screen.id)
            ).all()
        }
        new_company_ids: list[int] = []
        by_company = {row["company_id"]: row for row in response["results"]}
        for company_id in matched_ids:
            match = existing.get(company_id)
            is_new = match is None or not match.active
            if match is None:
                match = SavedScreenMatch(
                    saved_screen_id=screen.id,
                    company_id=company_id,
                    first_matched_at=now,
                    last_matched_at=now,
                )
                db.add(match)
            match.active = True
            match.last_matched_at = now
            match.result = by_company[company_id]
            if is_new:
                new_company_ids.append(company_id)
                if screen.alerts_enabled:
                    company = db.get(Company, company_id)
                    ReviewAlertService().emit_alert(
                        db,
                        company_id=company_id,
                        alert_type="new_screen_match",
                        severity="medium",
                        title=f"Nueva coincidencia: {screen.name}",
                        message=f"{company.ticker if company else company_id} ahora cumple {screen.name}",
                        fingerprint_parts=["saved_screen", str(screen.id), str(company_id)],
                        metadata={
                            "saved_screen_id": screen.id,
                            "result": by_company[company_id],
                        },
                    )
        for company_id, match in existing.items():
            if match.active and company_id not in matched_ids:
                match.active = False
        screen.last_run_at = now
        db.commit()
        response["saved_screen_id"] = screen.id
        response["new_match_company_ids"] = new_company_ids
        return response

    def run(
        self,
        db: Session,
        *,
        criteria: list[dict[str, Any]],
        ranking_formula: str | None = None,
        ranking_direction: str = "desc",
    ) -> dict[str, Any]:
        normalized = [self._criterion(item) for item in criteria]
        ranking = SafeFormula(ranking_formula) if ranking_formula else None
        definitions = CustomMetricService.active(db)
        # Parse every formula ONCE, outside the company loop: the set of names a
        # screen references is what decides which financial_facts rows are read.
        parsed_criteria = [
            (criterion, SafeFormula(criterion["left"]), SafeFormula(criterion["right"]))
            for criterion in normalized
        ]
        used_names: set[str] = set(ranking.names) if ranking else set()
        for _criterion_item, left, right in parsed_criteria:
            used_names.update(left.names | right.names)
        # Nombres que la corrida realmente consulta: los del screener mas los
        # de las formulas de metricas personalizadas (sus dependencias se
        # expanden en _expand_missing/_custom_metrics, mismas formulas).
        # Acotan tanto el read de calculated_metrics como el de contexto.
        referenced_names = set(used_names)
        for definition in definitions:
            try:
                referenced_names |= SafeFormula(definition.formula).names
            except ValueError:
                continue
        results = []
        # Names of the screen that at least ONE company has data for. A name
        # nobody has (typo, metric never ingested) used to look like "every
        # company is missing it" with no hint that the metric itself is the
        # problem.
        names_with_data: set[str] = set()
        companies = list(db.scalars(select(Company).order_by(Company.ticker)).all())
        # Batch-fetch observations once: two queries per table instead of two
        # queries per company (2N -> 2 on every screener run).
        # Solo la ultima fila por (empresa, metrica) se usa (la primera en el
        # orden fiscal_year DESC NULLS LAST, id DESC): row_number con ese mismo
        # orden y rn = 1 la acota en SQL. Antes se leian TODOS los años y
        # periodos de TODAS las metricas calculadas en cada corrida del
        # screener (y de cada saved screen en cada market refresh).
        ranked_calculated = (
            select(
                CalculatedMetric.id.label("id"),
                func.row_number()
                .over(
                    partition_by=(CalculatedMetric.company_id, CalculatedMetric.metric),
                    order_by=(
                        CalculatedMetric.fiscal_year.desc().nullslast(),
                        desc(CalculatedMetric.id),
                    ),
                )
                .label("rn"),
            )
            .where(
                CalculatedMetric.value.is_not(None),
                CalculatedMetric.status == "ok",
                # Acotado a los nombres referenciados: la ventana particiona
                # por (company_id, metric), asi que excluir metricas enteras
                # no cambia rn de las que quedan (mismas filas, mismo orden).
                # Antes rankeaba TODAS las metricas calculadas del tenant
                # (todos los anos y periodos) en cada corrida; el resultado
                # por empresa solo usa los nombres referenciados. Con el
                # filtro, PG puede usar ix_calc_metrics_tenant_metric_ok
                # (tenant_id, metric) en vez de barrer el indice de la
                # ventana entero.
                CalculatedMetric.metric.in_(sorted(referenced_names)),
                *tenant_filters(db, CalculatedMetric),
            )
            .subquery("bounded_calculated_metrics")
        )
        calculated_by_company: dict[int, list[CalculatedMetric]] = {}
        for row in db.scalars(
            select(CalculatedMetric)
            .join(ranked_calculated, ranked_calculated.c.id == CalculatedMetric.id)
            .where(ranked_calculated.c.rn == 1)
            .order_by(
                CalculatedMetric.company_id,
                CalculatedMetric.metric,
                CalculatedMetric.fiscal_year.desc().nullslast(),
                desc(CalculatedMetric.id),
            )
        ).all():
            calculated_by_company.setdefault(row.company_id, []).append(row)
        facts_by_company = self._facts_by_company(db, self._required_fact_metrics(used_names, definitions))
        # Valoracion, tesis y nivel DCA como nombres del screener (tambien
        # dentro de metricas personalizadas). Solo se leen si se usan.
        context_by_company = context_observations(db, referenced_names, companies)
        for company in companies:
            observations = self._observations_from_rows(
                calculated_by_company.get(company.id, []),
                facts_by_company.get(company.id, []),
            )
            observations.update(context_by_company.get(company.id, {}))
            self._custom_metrics(observations, definitions)
            values = {key: item.value for key, item in observations.items()}
            names_with_data.update(name for name in used_names if name in observations)
            criterion_results: list[dict[str, Any]] = []
            # Criteria and ranking are tracked separately ON PURPOSE. A ranking
            # formula is a tiebreaker: it orders the result set, it never decides
            # membership. Sharing one `missing` set let a company that satisfies
            # every criterion but lacks the ranking metric be reported
            # `matched: false`, be dropped from `match_count`, never become a
            # SavedScreenMatch and DEACTIVATE an existing match - silently
            # stopping its alerts.
            criteria_missing: set[str] = set()
            ranking_missing: set[str] = set()
            unevaluable_criteria: set[str] = set()
            for criterion, left, right in parsed_criteria:
                try:
                    left_value = left.evaluate(values)
                    right_value = right.evaluate(values)
                    passed = COMPARATORS[criterion["operator"]](left_value, right_value)
                    criterion_results.append(
                        {
                            **criterion,
                            "left_value": str(left_value),
                            "right_value": str(right_value),
                            "passed": passed,
                        }
                    )
                except MissingVariables as exc:
                    expanded = self._expand_missing(exc.names, definitions, values)
                    criteria_missing.update(expanded)
                    criterion_results.append(
                        {**criterion, "passed": False, "missing_fields": sorted(expanded)}
                    )
                except ValueError as exc:
                    # SafeFormula re-raises division-by-zero / non-finite results
                    # as ValueError. This company's data is unusable for THIS
                    # criterion; the rest of the universe is fine. Without this
                    # branch a single revenue == 0 under `fcf_margin > 0.1` took
                    # down the whole run (and, in the refresh path, the whole
                    # POST /api/portfolio/refresh-market after prices, FX,
                    # revaluation and the snapshot had already been committed).
                    unevaluable_criteria.add(criterion["left"])
                    # py/stack-trace-exposure (alerta 216): la razon publica es
                    # constante y el detalle de la excepcion va al log del
                    # servidor, nunca a la respuesta.
                    logger.warning(
                        "screener criterion %s unevaluable for company_id=%s: %s",
                        criterion["left"],
                        company.id,
                        exc,
                    )
                    criterion_results.append(
                        {
                            **criterion,
                            "passed": False,
                            "status": "unevaluable",
                            "error": CRITERION_UNEVALUABLE_REASON,
                        }
                    )
            rank_value = None
            ranking_unevaluable: str | None = None
            if ranking:
                try:
                    rank_value = ranking.evaluate(values)
                except MissingVariables as exc:
                    ranking_missing.update(self._expand_missing(exc.names, definitions, values))
                except ValueError as exc:
                    # Same isolation as the criteria: an unrankable company keeps
                    # its result row and simply sorts on the `rank_value is None`
                    # key. Its ranking fields are present but unusable, so they
                    # are NOT reported as missing data - that would be a false
                    # claim about the coverage of the screen.
                    ranking_unevaluable = str(exc)
                    logger.warning(
                        "screener ranking formula unevaluable for company_id=%s: %s",
                        company.id,
                        exc,
                    )
            # The union is only for RESULT QUALITY (which fields are missing,
            # coverage and confidence). Membership reads `criteria_missing` alone.
            missing = criteria_missing | ranking_missing
            available = {name for name in used_names - missing if name in observations}
            confidence_values = [observations[name].confidence for name in available]
            dates = [observations[name].as_of for name in available if observations[name].as_of]
            # `entry`, not `row`: an annotated `row` here re-types the whole
            # function-scope name that the ORM batch loops above already bound
            # to CalculatedMetric / FinancialFact.
            entry: dict[str, Any] = {
                "company_id": company.id,
                "ticker": company.ticker,
                "name": company.name,
                "matched": not criteria_missing and all(item["passed"] for item in criterion_results),
                "rank_value": str(rank_value) if rank_value is not None else None,
                "coverage_percent": round(100 * len(available) / len(used_names), 1) if used_names else 100.0,
                "confidence": str(sum(confidence_values, Decimal("0")) / len(confidence_values))
                if confidence_values
                else "0",
                "latest_data_at": max(dates).isoformat() if dates else None,
                "missing_fields": sorted(missing),
                "criteria": criterion_results,
            }
            if unevaluable_criteria:
                entry["unevaluable_criteria"] = sorted(unevaluable_criteria)
            if ranking_unevaluable is not None:
                entry["ranking_status"] = "unevaluable"
            results.append(entry)

        def result_order(row: dict[str, Any]) -> tuple[Any, ...]:
            missing_rank = row["rank_value"] is None
            rank_value = Decimal(row["rank_value"]) if row["rank_value"] is not None else Decimal("0")
            ordered_rank = rank_value if ranking_direction == "asc" else -rank_value
            return (not row["matched"], missing_rank, ordered_rank, row["ticker"])

        results.sort(key=result_order)
        return {
            "criteria": normalized,
            "ranking_formula": ranking_formula,
            "ranking_direction": ranking_direction,
            "company_count": len(results),
            "match_count": sum(1 for row in results if row["matched"]),
            # Metrics the screen uses that NO company has data for. Empty when
            # the universe is empty (nothing to conclude).
            "metrics_without_data": sorted(used_names - names_with_data) if results else [],
            "results": results,
        }

    # Per-company cap on the financial_facts rows read for ONE metric. A screen
    # only reads the latest value and the CAGR endpoints, so a few dozen periods
    # per metric is plenty of history while still bounding the read.
    MAX_FACTS_PER_METRIC = 60

    def _facts_by_company(self, db: Session, metrics: set[str]) -> dict[int, list[FinancialFact]]:
        """Financial facts for the metrics this screen references, bounded.

        Unfiltered, this read the WHOLE `financial_facts` table (every metric of
        every company, full history) once per saved screen on every market
        refresh. It is now filtered to the referenced metric names and capped at
        `MAX_FACTS_PER_METRIC` rows per (company, metric) with a
        `row_number()` window, which both SQLite and Postgres support.

        Ordering is `(fiscal_year DESC NULLS LAST, id DESC)`: the newest
        fiscal year first, and within a year the newest ingested row first.
        `NULLS LAST` is explicit because SQLite sorts NULLs first on ASC while
        Postgres sorts them last, and a NULL-year fact must never outrank a real
        annual one.
        """
        if not metrics:
            return {}
        # Single-pass: la ventana se calcula sobre las filas que ya cumplen
        # metric/tenant y se filtra por rn en la MISMA consulta. La forma
        # anterior (subconsulta de ids + join de vuelta por id) leia la tabla
        # entera del tenant para reencontrar ~7k filas por id (MEDIDO en el
        # laboratorio 0120: 43,5 ms -> 5,9 ms con conjunto de filas identico).
        ranked = (
            select(
                FinancialFact,
                func.row_number()
                .over(
                    partition_by=(FinancialFact.company_id, FinancialFact.metric),
                    order_by=(
                        FinancialFact.fiscal_year.desc().nullslast(),
                        desc(FinancialFact.id),
                    ),
                )
                .label("rn"),
            )
            .where(
                FinancialFact.metric.in_(sorted(metrics)),
                *tenant_filters(db, FinancialFact),
            )
            .subquery("bounded_financial_facts")
        )
        bounded_fact = aliased(FinancialFact, ranked)
        facts_by_company: dict[int, list[FinancialFact]] = {}
        for fact in db.scalars(
            select(bounded_fact)
            .where(ranked.c.rn <= self.MAX_FACTS_PER_METRIC)
            .order_by(
                bounded_fact.company_id,
                bounded_fact.metric,
                bounded_fact.fiscal_year.desc().nullslast(),
                desc(bounded_fact.id),
            )
        ).all():
            facts_by_company.setdefault(fact.company_id, []).append(fact)
        return facts_by_company

    def _required_fact_metrics(self, names: set[str], definitions: list[CustomMetricDefinition]) -> set[str]:
        """Fact metrics behind the names a screen references.

        Walks the same graph the observations do: a `*_cagr` name needs its base
        fact metric, `shares_cagr` needs `shares_diluted`, `fcf_per_share_cagr`
        needs `free_cash_flow` and `shares_diluted`, and a custom metric key
        needs every dependency of its formula (transitively).
        """
        by_key = {definition.metric_key: definition for definition in definitions}
        required: set[str] = set()
        pending = list(names)
        seen: set[str] = set()
        while pending:
            name = pending.pop()
            if name in seen:
                continue
            seen.add(name)
            required.add(name)
            for base in self._derived_fact_metrics(name):
                pending.append(base)
            definition = by_key.get(name)
            if definition is not None:
                pending.extend(SafeFormula(definition.formula).names)
        return required

    @staticmethod
    def _derived_fact_metrics(name: str) -> list[str]:
        """Fact metrics that back a derived screener observation."""
        if name == "shares_cagr":
            return ["shares_diluted"]
        if name == "fcf_per_share_cagr":
            return ["free_cash_flow", "shares_diluted"]
        if name.endswith("_cagr"):
            return [name[: -len("_cagr")]]
        return []

    @staticmethod
    def _expand_missing(
        names: set[str],
        definitions: list[CustomMetricDefinition],
        values: dict[str, Decimal],
    ) -> set[str]:
        by_key = {definition.metric_key: definition for definition in definitions}
        expanded = set(names)
        pending = list(names)
        while pending:
            name = pending.pop()
            definition = by_key.get(name)
            if definition is None:
                continue
            for dependency in SafeFormula(definition.formula).names:
                if dependency not in values and dependency not in expanded:
                    expanded.add(dependency)
                    pending.append(dependency)
        return expanded

    @staticmethod
    def _criterion(item: dict[str, Any]) -> dict[str, str]:
        left = str(item.get("left") or item.get("metric") or "").strip()
        operator_key = str(item.get("operator") or "").strip()
        raw_right = item.get("right", item.get("value"))
        right = str(raw_right).strip()
        if not left or not right or operator_key not in COMPARATORS:
            raise ValueError("Cada criterio necesita valor izquierdo, operador y valor derecho")
        SafeFormula(left)
        SafeFormula(right)
        return {"left": left, "operator": operator_key, "right": right}

    def _observations(self, db: Session, company: Company) -> dict[str, Observation]:
        calculated = db.scalars(
            select(CalculatedMetric)
            .where(
                CalculatedMetric.company_id == company.id,
                CalculatedMetric.value.is_not(None),
                CalculatedMetric.status == "ok",
            )
            .order_by(
                CalculatedMetric.metric,
                CalculatedMetric.fiscal_year.desc().nullslast(),
                desc(CalculatedMetric.id),
            )
        ).all()
        facts = list(
            db.scalars(
                select(FinancialFact)
                .where(FinancialFact.company_id == company.id)
                .order_by(
                    FinancialFact.metric,
                    FinancialFact.fiscal_year.desc().nullslast(),
                    desc(FinancialFact.id),
                )
            ).all()
        )
        return self._observations_from_rows(calculated, facts)

    def _observations_from_rows(
        self,
        calculated: list[CalculatedMetric],
        facts: list[FinancialFact],
    ) -> dict[str, Observation]:
        result: dict[str, Observation] = {}
        for metric in calculated:
            if metric.metric not in result and metric.value is not None:
                result[metric.metric] = Observation(
                    metric.value,
                    metric.confidence,
                    metric.updated_at,
                    metric.period,
                    "calculated_metric",
                    [metric.id],
                )
        by_metric: dict[str, list[FinancialFact]] = {}
        for fact in facts:
            by_metric.setdefault(fact.metric, []).append(fact)
        for metric_name, series in by_metric.items():
            # DEDUP RULE: facts arrive ordered (fiscal_year DESC NULLS LAST,
            # id DESC): the newest fiscal year and, within a year, the newest
            # ingested row. Like `_cagr` (see `_newest_per_year`) an ANNUAL row
            # wins: a Q3 ingested after the FY is not the year's value, and a
            # criterion such as ``free_cash_flow > X`` or a custom formula mixing
            # metrics must not compare a quarter against annual figures. Only a
            # metric with no annual row at all falls back to the newest row.
            annual = ScreenerService._newest_per_year(series, annual_only=True)
            fact = annual[max(annual)] if annual else series[0]
            result.setdefault(
                metric_name,
                Observation(
                    fact.value,
                    fact.confidence,
                    fact.updated_at,
                    fact.period,
                    fact.source_type,
                    [fact.id],
                ),
            )
        for key, series in by_metric.items():
            cagr = self._cagr(series)
            if cagr:
                result[f"{key}_cagr"] = cagr
        if "shares_diluted_cagr" in result:
            result["shares_cagr"] = result["shares_diluted_cagr"]
        fcf_per_share = self._ratio_cagr(
            by_metric.get("free_cash_flow", []),
            by_metric.get("shares_diluted", []),
        )
        if fcf_per_share:
            result["fcf_per_share_cagr"] = fcf_per_share
        return result

    @staticmethod
    def _cagr(series: list[FinancialFact]) -> Observation | None:
        # DEDUP RULE, identical to the point observation in
        # `_observations_from_rows`: within one fiscal_year the NEWEST ingested
        # row wins, i.e. the FIRST one seen, because the series arrives ordered
        # (fiscal_year DESC NULLS LAST, id DESC) and a higher id is a later
        # insert. `financial_facts` has no unique constraint on
        # (tenant_id, company_id, metric, fiscal_year) and several documents
        # legitimately author the same year, so a restated issuer has two rows
        # per year. Building this dict by comprehension kept the LAST write and
        # therefore the LOWEST id: the CAGR base was the OLD restatement while
        # the point value was the NEW one, and growth was systematically wrong.
        annual = ScreenerService._newest_per_year(series, annual_only=True)
        years = sorted(annual)
        if len(years) < 2:
            return None
        first, last = annual[years[0]], annual[years[-1]]
        if first.value <= 0 or last.value < 0:
            return None
        value = (last.value / first.value) ** (Decimal("1") / (years[-1] - years[0])) - 1
        return Observation(
            value,
            min(first.confidence, last.confidence),
            last.updated_at,
            f"FY{years[0]}-FY{years[-1]}",
            "calculated_cagr",
            [first.id, last.id],
        )

    @staticmethod
    def _newest_per_year(
        rows: Iterable[FinancialFact], *, annual_only: bool = False
    ) -> dict[int, FinancialFact]:
        """Newest-ingested row per fiscal_year; first row wins (see `_cagr`)."""
        by_year: dict[int, FinancialFact] = {}
        for row in rows:
            if row.fiscal_year is None:
                continue
            if annual_only and (row.fiscal_quarter or "").upper().startswith("Q"):
                continue
            by_year.setdefault(row.fiscal_year, row)
        return by_year

    def _ratio_cagr(
        self, numerators: list[FinancialFact], denominators: list[FinancialFact]
    ) -> Observation | None:
        # Same dedup rule as `_cagr`: newest row per fiscal_year, not the last
        # write of a comprehension over an unsorted series.
        # Solo filas anuales, igual que `_cagr`: un trimestre ingerido despues
        # del anual no puede ocupar el lugar del ano.
        numerator_by_year = self._newest_per_year(numerators, annual_only=True)
        denominator_by_year = self._newest_per_year(denominators, annual_only=True)
        years = sorted(numerator_by_year.keys() & denominator_by_year.keys())
        if len(years) < 2:
            return None
        first_year, last_year = years[0], years[-1]
        first_n, last_n = numerator_by_year[first_year], numerator_by_year[last_year]
        first_d, last_d = denominator_by_year[first_year], denominator_by_year[last_year]
        if first_d.value == 0 or last_d.value == 0:
            return None
        synthetic = [
            FinancialFact(
                id=first_n.id,
                company_id=first_n.company_id,
                metric="fcf_per_share",
                value=first_n.value / first_d.value,
                period=f"FY{first_year}",
                fiscal_year=first_year,
                confidence=min(first_n.confidence, first_d.confidence),
            ),
            FinancialFact(
                id=last_n.id,
                company_id=last_n.company_id,
                metric="fcf_per_share",
                value=last_n.value / last_d.value,
                period=f"FY{last_year}",
                fiscal_year=last_year,
                confidence=min(last_n.confidence, last_d.confidence),
            ),
        ]
        observation = self._cagr(synthetic)
        if observation:
            observation.source_ids = [first_n.id, first_d.id, last_n.id, last_d.id]
            observation.as_of = last_n.updated_at
        return observation

    @staticmethod
    def _custom_metrics(
        observations: dict[str, Observation],
        definitions: list[CustomMetricDefinition],
    ) -> None:
        pending = list(definitions)
        for _ in range(len(pending) + 1):
            changed = False
            values = {key: item.value for key, item in observations.items()}
            for definition in list(pending):
                formula = SafeFormula(definition.formula)
                try:
                    value = formula.evaluate(values)
                except MissingVariables:
                    continue
                except ValueError as exc:
                    # A custom metric that cannot be computed on THIS company's
                    # data (division by zero, non-finite) is left unobserved, so
                    # the screen reports it as missing instead of the whole run
                    # raising out of here.
                    logger.warning("custom metric %s unevaluable: %s", definition.metric_key, exc)
                    continue
                dependencies = [observations[name] for name in formula.names]
                observations[definition.metric_key] = Observation(
                    value=value,
                    confidence=min(
                        (item.confidence for item in dependencies),
                        default=Decimal("0"),
                    ),
                    as_of=max(
                        (item.as_of for item in dependencies if item.as_of),
                        default=None,
                    ),
                    period=max((item.period for item in dependencies), default="unknown"),
                    source=f"custom_metric_v{definition.version}",
                    source_ids=[source_id for item in dependencies for source_id in item.source_ids],
                )
                pending.remove(definition)
                changed = True
            if not changed:
                break
