from __future__ import annotations

from sqlalchemy import desc, func, select
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import Session, aliased

from app.core.tenancy import tenant_filters
from app.models import (
    CalculatedMetric,
    Claim,
    Company,
    Document,
    FinancialFact,
    FundamentalModelVersion,
    NewsEvent,
    Position,
    ResearchAlert,
    ResearchReview,
    ThesisChange,
    ThesisVersion,
    ValuationModel,
)
from app.schemas import CompanySnapshotOut
from app.services.document_visibility import without_archive_duplicates
from app.services.news_headline_translation import display_translation, original_headline
from app.services.thesis_change_identity import ChangeItem, group_change_items
from app.services.thesis_publication_gate import model_withheld_reason, withhold_thesis_payload
from app.valuation.margin_convention import margin_convention_known


class CompanySnapshotService:
    @staticmethod
    def _held_company_ids(db: Session, company_ids: list[int]) -> set[int]:
        """company_ids con posicion viva (cantidad > 0) del tenant actual.

        La tenencia es por tenant y vive en ``positions``;
        ``companies.company_type`` es una etiqueta estatica fijada en el
        alta de la ficha (F143). Sin tenant en la sesion no se afirma
        tenencia. El filtro de tenant es explicito: los criterios de carga
        no alcanzan consultas de agregacion.
        """
        tenant_id = db.info.get("tenant_id")
        if tenant_id is None or not company_ids:
            return set()
        return set(
            db.scalars(
                select(Position.company_id)
                .where(
                    Position.tenant_id == tenant_id,
                    Position.company_id.in_(company_ids),
                    Position.quantity > 0,
                )
                .distinct()
            ).all()
        )

    """Build the small workspace bootstrap exclusively from persisted rows.

    This service deliberately contains no calculator, model builder, graph
    builder, document chunk loader or commit. Refreshes belong to explicit POST
    endpoints so a GET can be cached, retried and observed without side effects.
    """

    def build(self, db: Session, company: Company) -> CompanySnapshotOut:
        thesis = db.scalar(
            select(ThesisVersion)
            .where(ThesisVersion.company_id == company.id)
            .order_by(desc(ThesisVersion.version))
            .limit(1)
        )
        model = db.scalar(
            select(FundamentalModelVersion)
            .where(FundamentalModelVersion.company_id == company.id)
            .order_by(desc(FundamentalModelVersion.version))
            .limit(1)
        )
        valuation_model = db.scalar(
            select(ValuationModel)
            .where(ValuationModel.company_id == company.id)
            .order_by(desc(ValuationModel.version), desc(ValuationModel.created_at))
            .limit(1)
        )
        recent_changes = self._enrich_changes_many(
            db,
            {
                company.id: list(
                    db.scalars(
                        select(ThesisChange)
                        .where(ThesisChange.company_id == company.id)
                        .order_by(desc(ThesisChange.created_at), desc(ThesisChange.id))
                        .limit(10)
                    ).all()
                )
            },
        )[company.id]
        counts = self._counts(db, company.id)
        held = self._held_company_ids(db, [company.id])
        return self._assemble(
            company,
            thesis,
            model,
            valuation_model,
            recent_changes,
            counts,
            in_portfolio=company.id in held,
        )

    def build_many(
        self, db: Session, companies: list[Company]
    ) -> dict[int, CompanySnapshotOut]:
        """Snapshots de N empresas con queries agregadas (anti fan-out del indice).

        El indice de research pedia un snapshot por empresa: 5 round trips x
        40 empresas = ~200 queries contra Postgres y 40 llamadas HTTP por
        visita. Aqui el ultimo thesis/modelo/valoracion por empresa sale con
        row_number() particionado por company_id, los ultimos 10 cambios por
        empresa con la misma ventana, y los 8 conteos agrupados con GROUP BY:
        ~13 queries para TODO el lote, independientemente de N. El caller
        acota el lote (MAX_SNAPSHOT_BATCH_TICKERS en la ruta); no hay
        proyeccion parcial de columnas, se leen las filas completas igual
        que en build().
        """
        if not companies:
            return {}
        # inspect().identity da la PK SIN consulta aunque la instancia venga
        # expirada (leer .id re-SELECTaria una por una); las filas se
        # refrescan en UNA query por IN.
        company_ids = [
            int(identity[0])
            for company in companies
            if (identity := sa_inspect(company).identity) is not None
        ]
        if not company_ids:
            return {}
        companies = list(
            db.scalars(select(Company).where(Company.id.in_(company_ids))).all()
        )
        theses = self._latest_by_company(
            db, ThesisVersion, company_ids, desc(ThesisVersion.version)
        )
        models = self._latest_by_company(
            db, FundamentalModelVersion, company_ids, desc(FundamentalModelVersion.version)
        )
        valuations = self._latest_by_company(
            db,
            ValuationModel,
            company_ids,
            desc(ValuationModel.version),
            desc(ValuationModel.created_at),
        )
        changes = self._enrich_changes_many(db, self._recent_changes_many(db, company_ids))
        counts = self._counts_many(db, company_ids)
        held = self._held_company_ids(db, company_ids)
        return {
            company.id: self._assemble(
                company,
                theses.get(company.id),
                models.get(company.id),
                valuations.get(company.id),
                changes.get(company.id, []),
                counts[company.id],
                in_portfolio=company.id in held,
            )
            for company in companies
        }

    @staticmethod
    def _latest_by_company(
        db: Session, entity: type, company_ids: list[int], *order_by
    ) -> dict[int, object]:
        """La fila mas reciente por company_id en UNA query (window function)."""
        ranked = (
            select(
                entity,
                func.row_number()
                .over(partition_by=entity.company_id, order_by=[*order_by])
                .label("rank_"),
            )
            .where(entity.company_id.in_(company_ids))
            .subquery()
        )
        aliased_entity = aliased(entity, ranked)
        rows = db.scalars(select(aliased_entity).where(ranked.c.rank_ == 1)).all()
        return {row.company_id: row for row in rows}

    @staticmethod
    def _recent_changes_many(
        db: Session, company_ids: list[int], per_company: int = 10
    ) -> dict[int, list[ThesisChange]]:
        """Los ultimos ``per_company`` cambios de cada empresa en UNA query."""
        ranked = (
            select(
                ThesisChange,
                func.row_number()
                .over(
                    partition_by=ThesisChange.company_id,
                    order_by=[desc(ThesisChange.created_at), desc(ThesisChange.id)],
                )
                .label("rank_"),
            )
            .where(ThesisChange.company_id.in_(company_ids))
            .subquery()
        )
        aliased_change = aliased(ThesisChange, ranked)
        # ORDER BY externo: la window numera cada particion, pero sin orden
        # de la consulta exterior las filas salen en orden arbitrario.
        rows = db.scalars(
            select(aliased_change)
            .where(ranked.c.rank_ <= per_company)
            .order_by(ranked.c.company_id, desc(ranked.c.created_at), desc(ranked.c.id))
        ).all()
        grouped: dict[int, list[ThesisChange]] = {}
        for row in rows:
            grouped.setdefault(row.company_id, []).append(row)
        return grouped

    @staticmethod
    def _enrich_changes_many(
        db: Session, changes_by_company: dict[int, list[ThesisChange]]
    ) -> dict[int, list[dict]]:
        """Cambios recientes con identidad atribuida de su evento, en lote.

        La misma noticia en dos idiomas genera un ThesisChange por idioma
        (QA ASTS 21-oct-2026: el par ES/EN salía duplicado en «Últimos
        cambios»). ThesisChange no enlaza con NewsEvent; la ResearchReview
        creada con él sí. Dos queries para TODO el lote (reviews + eventos),
        no una por empresa ni por cambio; la agrupación es la misma regla de
        identidad atribuida que «Desde tu última visita» (nunca similitud) y
        conserva las fuentes absorbidas en ``tambien_en`` con su URL.
        """
        all_changes = [change for rows in changes_by_company.values() for change in rows]
        if not all_changes:
            return {cid: [] for cid in changes_by_company}
        review_rows = db.execute(
            select(ResearchReview.thesis_change_id, ResearchReview.news_event_id).where(
                ResearchReview.thesis_change_id.in_([c.id for c in all_changes]),
                ResearchReview.news_event_id.is_not(None),
                *tenant_filters(db, ResearchReview),
            )
        ).all()
        event_id_by_change: dict[int, int] = {}
        for change_id, event_id in review_rows:
            event_id_by_change.setdefault(change_id, event_id)
        event_ids = set(event_id_by_change.values())
        events = (
            {e.id: e for e in db.scalars(select(NewsEvent).where(NewsEvent.id.in_(event_ids))).all()}
            if event_ids
            else {}
        )
        out: dict[int, list[dict]] = {}
        for company_id, rows in changes_by_company.items():
            items: list[ChangeItem] = []
            for orden, change in enumerate(rows):
                event = events.get(event_id_by_change.get(change.id))
                translation = display_translation(event) if event is not None else None
                items.append(
                    ChangeItem(
                        resumen=change.summary,
                        direccion=change.impact_direction,
                        requiere_revision=bool(change.requires_review),
                        fecha=None,
                        orden=orden,
                        news_event_id=event.id if event is not None else None,
                        fuente_url=event.url if event is not None else None,
                        fuente_nombre=event.source if event is not None else None,
                        titular_original=original_headline(event) if event is not None else None,
                        traduccion_titular=(
                            translation["text"]
                            if isinstance(translation, dict) and isinstance(translation.get("text"), str)
                            else None
                        ),
                        extra={"change": change},
                    )
                )
            out[company_id] = []
            for item in group_change_items(items):
                change = item.extra["change"]
                out[company_id].append(
                    {
                        "id": change.id,
                        "company_id": change.company_id,
                        "change_type": change.change_type,
                        "impact_direction": change.impact_direction,
                        "materiality_score": change.materiality_score,
                        "summary": change.summary,
                        "affected_metrics": change.affected_metrics or [],
                        "requires_review": item.requiere_revision,
                        "created_at": change.created_at,
                        "fuente_url": item.fuente_url,
                        "fuente_nombre": item.fuente_nombre,
                        "tambien_en": item.tambien_en or None,
                    }
                )
        return out

    @staticmethod
    def _counts_many(db: Session, company_ids: list[int]) -> dict[int, dict[str, int]]:
        """Los 8 conteos por empresa: una query GROUP BY por tabla, no por empresa."""

        # F315: medido en SQLAlchemy 2.1.6, with_loader_criteria SI alcanza
        # a los agregados (func.count() select_from); aun asi TODAS las
        # entidades tenant-owned se filtran explicitamente, no solo
        # documents, como segunda capa y fail-closed. Company es global y
        # compartida entre tenants; sin ninguna de las dos capas un snapshot
        # sumaba los facts/metrics/claims/versions/reviews/alerts de otros
        # tenants.
        tenant_id = db.info.get("tenant_id")

        def grouped(entity: type, *extra_where) -> dict[int, int]:
            stmt = (
                select(entity.company_id, func.count())
                .where(entity.company_id.in_(company_ids), *extra_where)
                .group_by(entity.company_id)
            )
            if tenant_id is not None:
                stmt = stmt.where(entity.tenant_id == tenant_id)
            return {int(cid): int(n) for cid, n in db.execute(stmt).all()}

        facts = grouped(FinancialFact)
        calculated_metrics = grouped(CalculatedMetric)
        # F304: el contador debe contar lo que la ficha deja VER. La lista de
        # documentos colapsa las re-ingestas del mismo filing de archivo
        # (without_archive_duplicates); contar filas crudas declaraba el
        # doble de documentos de los accesibles (KO: «DOCUMENTOS 40» con 20
        # enlaces). Misma regla de visibilidad que la lista y que
        # /documents/count.
        documents_stmt = without_archive_duplicates(
            select(Document.company_id, func.count())
            .where(Document.company_id.in_(company_ids))
            .group_by(Document.company_id)
        )
        # El filtro explícito es segunda capa sobre with_loader_criteria
        # (que medido en SQLAlchemy 2.1.6 SI alcanza a los agregados):
        # sin ninguna de las dos capas una empresa compartida entre
        # tenants sumaría los documentos de todos. Mismo patrón que
        # /documents/count.
        if tenant_id is not None:
            documents_stmt = documents_stmt.where(Document.tenant_id == tenant_id)
        documents = {int(cid): int(n) for cid, n in db.execute(documents_stmt).all()}
        claims = grouped(Claim)
        thesis_versions = grouped(ThesisVersion)
        model_versions = grouped(FundamentalModelVersion)
        open_reviews = grouped(
            ResearchReview, ResearchReview.status.in_(["open", "in_progress"])
        )
        open_alerts = grouped(
            ResearchAlert, ResearchAlert.status.in_(["open", "snoozed"])
        )
        return {
            company_id: {
                "facts": facts.get(company_id, 0),
                "calculated_metrics": calculated_metrics.get(company_id, 0),
                "documents": documents.get(company_id, 0),
                "claims": claims.get(company_id, 0),
                "thesis_versions": thesis_versions.get(company_id, 0),
                "model_versions": model_versions.get(company_id, 0),
                "open_reviews": open_reviews.get(company_id, 0),
                "open_alerts": open_alerts.get(company_id, 0),
            }
            for company_id in company_ids
        }

    def _assemble(
        self,
        company: Company,
        thesis: ThesisVersion | None,
        model: FundamentalModelVersion | None,
        valuation_model: ValuationModel | None,
        recent_changes: list[dict],
        counts: dict[str, int],
        in_portfolio: bool = False,
    ) -> CompanySnapshotOut:
        missing: list[str] = []
        if counts["documents"] == 0:
            missing.append("documents")
        if counts["facts"] == 0:
            missing.append("financial_facts")
        if thesis is None:
            missing.append("thesis")
        if model is None:
            missing.append("long_term_model")

        review_required = counts["open_reviews"] > 0 or counts["open_alerts"] > 0
        completed = 4 - len(missing)
        score = completed * 20
        if counts["calculated_metrics"] > 0:
            score += 10
        if counts["claims"] > 0:
            score += 10
        # Anti-falsa-seguridad: sin tesis no hay nota alta aunque haya
        # hechos+documentos+modelo (era 70/100 con 0 afirmaciones y sin
        # tesis). Sin afirmaciones tampoco se supera el notable.
        # Ponderación: 20 por capa (docs, facts, tesis, modelo) +10 métricas +10 claims.
        if thesis is None:
            score = min(score, 59)
        elif counts["claims"] == 0:
            score = min(score, 69)
        if counts["documents"] == counts["facts"] == counts["claims"] == 0:
            health_status = "empty"
        elif review_required:
            health_status = "review_required"
        elif missing or counts["claims"] == 0:
            # Sin afirmaciones el score queda topado (<=69): la etiqueta debe
            # acompañar al numero; "healthy" con nota topada era contradictorio.
            health_status = "incomplete"
        else:
            health_status = "healthy"

        margin_fields = {
            "margin_of_safety": None,
            "archived_margin_of_safety": thesis.margin_of_safety if thesis else None,
            "margin_of_safety_convention": (thesis.valuation_basis or {}).get("margin_of_safety_convention") if thesis else None,
            "margin_of_safety_status": "missing" if thesis is None or thesis.margin_of_safety is None else "unknown_convention",
        }
        if thesis and thesis.margin_of_safety is not None and margin_convention_known(thesis.valuation_basis):
            margin_fields["margin_of_safety"] = thesis.margin_of_safety
            margin_fields["margin_of_safety_status"] = "verified"
        thesis_summary = None
        if thesis is not None:
            thesis_summary = {
                "id": thesis.id,
                "version": thesis.version,
                "status": thesis.status,
                "executive_summary": thesis.executive_summary,
                "rating": thesis.rating,
                "current_price": thesis.current_price,
                "bear_value": thesis.bear_value,
                "base_value": thesis.base_value,
                "bull_value": thesis.bull_value,
                "expected_value": thesis.expected_value,
                **margin_fields,
                "data_confidence_score": thesis.data_confidence_score,
                "source_coverage_score": thesis.source_coverage_score,
                "hypothesis": getattr(thesis, "hypothesis", None),
                "catalysts": getattr(thesis, "catalysts", None),
                "invalidation_criteria": getattr(thesis, "invalidation_criteria", None),
                "scenario_probabilities": getattr(thesis, "scenario_probabilities", None),
                "created_at": thesis.created_at,
            }

            thesis_summary = withhold_thesis_payload(thesis_summary, thesis, model_withheld_reason(thesis, model))

        if thesis_summary and thesis_summary["margin_of_safety_status"] == "withheld":
            margin_fields = {key: thesis_summary[key] for key in margin_fields}

        model_summary = None
        if model is not None:
            model_summary = {
                "id": model.id,
                "version": model.version,
                "engine_version": model.engine_version,
                "algorithm_version": model.algorithm_version,
                "framework_key": model.framework_key,
                "horizon_years": model.horizon_years,
                "status": model.status,
                "publishable": model.publishable,
                "input_fingerprint": model.input_fingerprint,
                "forecast_fingerprint": model.forecast_fingerprint,
                "market_snapshot_fingerprint": model.market_snapshot_fingerprint,
                "valuation_snapshot_fingerprint": model.valuation_snapshot_fingerprint,
                "code_commit_sha": model.code_commit_sha,
                "scenario_probabilities": {
                    str(key): float(value) if value is not None else None
                    for key, value in (model.scenario_probabilities or {}).items()
                },
                "created_at": model.created_at,
            }

        return CompanySnapshotOut.model_validate(
            {
                "company": company,
                "in_portfolio": in_portfolio,
                "latest_thesis": thesis_summary,
                "valuation_summary": {
                    "model_id": valuation_model.id if valuation_model else None,
                    "model_type": (
                        valuation_model.model_type
                        if valuation_model
                        else company.valuation_model
                    ),
                    "version": valuation_model.version if valuation_model else None,
                    "status": (
                        valuation_model.status if valuation_model else "not_generated"
                    ),
                    "current_price": thesis.current_price if thesis else None,
                    "bear_value": thesis_summary["bear_value"] if thesis_summary else None,
                    "base_value": thesis_summary["base_value"] if thesis_summary else None,
                    "bull_value": thesis_summary["bull_value"] if thesis_summary else None,
                    "expected_value": thesis_summary["expected_value"] if thesis_summary else None,
                    **margin_fields,
                    "updated_at": (
                        valuation_model.updated_at if valuation_model else None
                    ),
                },
                "model_summary": model_summary,
                "research_health": {
                    "score": min(100, score),
                    "status": health_status,
                    "missing": missing,
                    "review_required": review_required,
                },
                "counts": counts,
                "recent_changes": recent_changes,
            },
            from_attributes=True,
        )

    @staticmethod
    def _counts(db: Session, company_id: int) -> dict[str, int]:
        """Los 8 conteos en UNA sola query (anti 8 round-trips por snapshot)."""
        # Filtro de tenant explicito: segunda capa y fail-closed; medido
        # en SQLAlchemy 2.1.6, with_loader_criteria SI alcanza a los
        # agregados func.count().select_from(...) — ver _counts_many.
        tenant_id = db.info.get("tenant_id")
        documents_subquery = without_archive_duplicates(
            select(func.count()).select_from(Document).where(Document.company_id == company_id)
        )
        if tenant_id is not None:
            documents_subquery = documents_subquery.where(Document.tenant_id == tenant_id)

        # F315: las 7 entidades tenant-owned se cuentan con filtro de
        # tenant explícito como segunda capa (medido en SQLAlchemy 2.1.6,
        # los agregados SI heredan with_loader_criteria); Company es global
        # y compartida entre tenants.
        def scoped_count(entity: type, *extra_where):
            stmt = (
                select(func.count())
                .select_from(entity)
                .where(entity.company_id == company_id, *extra_where)
            )
            if tenant_id is not None:
                stmt = stmt.where(entity.tenant_id == tenant_id)
            return stmt.scalar_subquery()

        row = db.execute(
            select(
                scoped_count(FinancialFact).label("facts"),
                scoped_count(CalculatedMetric).label("calculated_metrics"),
                documents_subquery.scalar_subquery().label("documents"),
                scoped_count(Claim).label("claims"),
                scoped_count(ThesisVersion).label("thesis_versions"),
                scoped_count(FundamentalModelVersion).label("model_versions"),
                scoped_count(
                    ResearchReview,
                    ResearchReview.status.in_(["open", "in_progress"]),
                ).label("open_reviews"),
                scoped_count(
                    ResearchAlert,
                    ResearchAlert.status.in_(["open", "snoozed"]),
                ).label("open_alerts"),
            )
        ).one()
        return {
            "facts": int(row.facts or 0),
            "calculated_metrics": int(row.calculated_metrics or 0),
            "documents": int(row.documents or 0),
            "claims": int(row.claims or 0),
            "thesis_versions": int(row.thesis_versions or 0),
            "model_versions": int(row.model_versions or 0),
            "open_reviews": int(row.open_reviews or 0),
            "open_alerts": int(row.open_alerts or 0),
        }
