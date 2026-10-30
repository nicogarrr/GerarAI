import logging
from collections.abc import Generator

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import create_engine, event, false, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker, with_loader_criteria

from app.core.auth import MSG_IDENTITY_REQUIRED, ResearchPrincipal, get_research_principal
from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

# Forward-compat migration failures recorded by init_db(). Empty means the
# schema is fully migrated. A non-empty list means at least one optional
# ALTER / back-fill did NOT run: the schema is half-migrated and every query
# touching the missing column will 500 with no hint that startup was the
# cause. Surfaced by `schema_migration_issues()` for the health payload.
_SCHEMA_MIGRATION_ERRORS: list[dict[str, str]] = []


def schema_migration_issues() -> list[dict[str, str]]:
    """Forward-compat migration failures recorded by the last `init_db()`.

    Each entry is `{"statement": <sql or label>, "error": "<ExceptionClass>"}`.
    Never raises, never blocks: a failed optional alter is a degraded schema,
    not a dead process.
    """
    return [dict(item) for item in _SCHEMA_MIGRATION_ERRORS]


def _record_schema_migration_error(statement: str, exc: BaseException) -> None:
    """Log an optional migration failure at ERROR and keep it for /api/health.

    Only the exception TYPE is recorded, never its message: an init failure
    can carry SQL fragments and host paths, and this is surfaced by a public
    endpoint.
    """
    _SCHEMA_MIGRATION_ERRORS.append(
        {"statement": statement, "error": type(exc).__name__}
    )
    logger.error(
        "Optional schema migration failed (statement=%r, error=%s). "
        "The schema is degraded: queries touching the missing column will fail.",
        statement,
        type(exc).__name__,
        exc_info=exc,
    )


def _execute_optional(statement: str, sql: str) -> bool:
    """Run ONE optional forward-compat statement, isolated from its siblings.

    The previous shape wrapped all 30+ ALTERs and the tenant_id back-fill in a
    single `except Exception: pass`: one failure (locked DB, read-only volume)
    left a half-migrated schema with no log, no metric and no startup failure.
    Each statement is now attempted on its own so a failure is reported with
    the statement that caused it and the remaining migrations still run.
    """
    try:
        with engine.begin() as conn:
            conn.execute(text(sql))
    except Exception as exc:  # noqa: BLE001 — never block startup on optional alter
        _record_schema_migration_error(statement, exc)
        return False
    return True


class Base(DeclarativeBase):
    pass


def _engine_connect_args(database_url: str, idle_timeout_ms: int) -> dict:
    """connect_args por motor.

    El timeout idle-in-transaction es SOLO Postgres (parametro de sesion
    via `options`, valido en psycopg2 y psycopg3): defensa de red para que
    una transaccion abierta y olvidada (worker colgado entre queries) no
    bloquee UPDATEs durante minutos. sqlite lleva check_same_thread y el
    resto de motores no recibe nada.
    """
    if database_url.startswith("sqlite"):
        return {"check_same_thread": False}
    scheme = database_url.split(":", 1)[0].lower()
    if scheme.startswith("postgresql") and idle_timeout_ms > 0:
        return {
            "options": f"-c idle_in_transaction_session_timeout={int(idle_timeout_ms)}"
        }
    return {}


def _engine_pool_kwargs(database_url: str, settings: Settings) -> dict:
    """Parametros de pool SOLO para Postgres.

    sqlite (tests y desarrollo local) conserva su pool por defecto: pasarle
    pool_size/max_overflow no aporta y cambia su semantica de conexiones.
    Los valores llegan de DB_POOL_SIZE / DB_MAX_OVERFLOW / DB_POOL_TIMEOUT /
    DB_POOL_RECYCLE; el compose fija 20+10 en el backend y 4+2 en los workers.
    """
    scheme = database_url.split(":", 1)[0].lower().split("+", 1)[0]
    if scheme not in {"postgres", "postgresql"}:
        return {}
    return {
        "pool_size": settings.db_pool_size,
        "max_overflow": settings.db_max_overflow,
        "pool_timeout": settings.db_pool_timeout,
        "pool_recycle": settings.db_pool_recycle,
    }


settings = get_settings()
engine = create_engine(
    settings.database_url,
    connect_args=_engine_connect_args(
        settings.database_url, settings.idle_in_transaction_session_timeout_ms
    ),
    pool_pre_ping=True,
    **_engine_pool_kwargs(settings.database_url, settings),
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


@event.listens_for(Session, "do_orm_execute")
def _scope_tenant_queries(execute_state) -> None:
    # Entity loads get the criteria below. Column/aggregate selects
    # (`select(Model.columna)`, func.count/max, window functions) must add
    # explicit predicates with app.core.tenancy.tenant_filters: on SQLAlchemy
    # 2.0 the loader criteria does not reach those compiled column queries.
    if execute_state.execution_options.get("include_all_tenants"):
        return
    tenant_id = execute_state.session.info.get("tenant_id")
    from app.models.entities import InferredInput, TenantOwnedMixin

    # Inferences are private even in unscoped background/test sessions. NULL
    # authors are quarantined, never a public fallback. Maintenance reads use
    # the explicit include_all_tenants escape hatch above.
    if tenant_id is None:
        if execute_state.is_select:
            execute_state.statement = execute_state.statement.options(
                with_loader_criteria(InferredInput, lambda model: false(), include_aliases=True)
            )
        elif (execute_state.is_update or execute_state.is_delete) and (
            getattr(getattr(execute_state.statement, "table", None), "name", None)
            == "inferred_inputs"
        ):
            raise RuntimeError("Tenant context is required for inferred input writes")
        return

    if execute_state.is_select:
        execute_state.statement = execute_state.statement.options(
            with_loader_criteria(
                TenantOwnedMixin,
                lambda model: model.tenant_id == tenant_id,
                include_aliases=True,
            )
        )
        return
    if execute_state.is_update or execute_state.is_delete:
        # Bulk UPDATE/DELETE Core: sin este filtro una sentencia sin WHERE de
        # tenant barria todas las filas de todos los tenants.
        _scope_tenant_dml(execute_state, tenant_id)


def _scope_tenant_dml(execute_state, tenant_id) -> None:
    statement = execute_state.statement
    table = getattr(statement, "table", None)
    if table is None or "tenant_id" not in table.c:
        return
    if execute_state.is_update:
        values = getattr(statement, "_values", None) or {}
        ordered_values = getattr(statement, "_ordered_values", None) or ()
        keys = [*values, *(column for column, _ in ordered_values)]
        # Core updates retain string keys, while ORM updates use Columns.
        # ordered_values() and execute(update(table), parameters) are also
        # SET assignments; neither is guaranteed to populate _values.
        parameters = execute_state.parameters
        batches = parameters if isinstance(parameters, (list, tuple)) else [parameters]
        keys.extend(
            key for batch in batches if isinstance(batch, dict) for key in batch
        )
        if any(
            (column if isinstance(column, str) else getattr(column, "key", ""))
            == "tenant_id"
            for column in keys
        ):
            raise RuntimeError(
                "Changing tenant_id through bulk updates is not allowed"
            )
    execute_state.statement = statement.where(table.c.tenant_id == tenant_id)


@event.listens_for(Session, "before_flush")
def _assign_tenant_to_new_rows(session: Session, _flush_context, _instances) -> None:
    tenant_id = session.info.get("tenant_id")
    from sqlalchemy import inspect as sa_inspect

    from app.models.entities import InferredInput, TenantOwnedMixin

    # Also reject attached/privileged-loaded cross-tenant mutations and deletes.
    # Do not rely only on SELECT filters to protect an already-loaded object.
    for instance in [*session.new, *session.dirty, *session.deleted]:
        if not isinstance(instance, InferredInput):
            continue
        if tenant_id is None:
            raise RuntimeError("Tenant context is required for inferred input writes")
        if instance.tenant_id is not None and instance.tenant_id != tenant_id:
            raise RuntimeError("Cross-tenant writes are not allowed")
        if instance not in session.new and instance.tenant_id is None:
            raise RuntimeError("Legacy inferred input ownership requires audited recovery")

    # P1-5: tenant_id es inmutable en filas persistentes. Reasignarlo (o
    # vaciarlo) via session.dirty no debe poder hacer commit.
    for instance in session.dirty:
        if not isinstance(instance, TenantOwnedMixin):
            continue
        history = sa_inspect(instance).attrs.tenant_id.history
        if history.has_changes() and list(history.deleted) != list(history.added):
            raise RuntimeError(
                "Cross-tenant writes are not allowed: tenant_id is immutable"
            )

    tenant_rows = [instance for instance in session.new if isinstance(instance, TenantOwnedMixin)]
    if tenant_id is None:
        if settings.research_auth_required and tenant_rows:
            raise RuntimeError("Tenant context is required for tenant-owned writes")
        return

    for instance in tenant_rows:
        if instance.tenant_id is None:
            instance.tenant_id = tenant_id
        elif instance.tenant_id != tenant_id:
            raise RuntimeError("Cross-tenant writes are not allowed")


def get_db(
    principal: ResearchPrincipal | None = Depends(get_research_principal),
    request: Request = None,
) -> Generator[Session, None, None]:
    # Fail-closed: with research auth required there is never an anonymous
    # session. Writes without a tenant must be impossible, not just unscoped.
    #
    # La condicion incluye is_production a proposito. get_research_principal ya
    # es fail-closed en produccion, pero get_db decide por su cuenta y antes
    # solo miraba research_auth_required: con el flag a false, produccion
    # abria sesiones anonimas -> sin db.info["tenant_id"] -> los guards de
    # _scope_tenant_queries/_scope_tenant_dml/_assign_tenant_to_new_rows no
    # inyectan nada y TODAS las consultas quedan sin scope de tenant.
    if principal is None and (
        settings.research_auth_required or settings.is_production
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=MSG_IDENTITY_REQUIRED,
        )
    db = SessionLocal()
    try:
        if principal:
            from app.models import Tenant

            tenant = db.scalar(
                select(Tenant).where(
                    Tenant.external_id == principal.tenant_external_id
                )
            )
            if tenant is None:
                tenant = Tenant(
                    external_id=principal.tenant_external_id,
                    name=f"Workspace {principal.tenant_external_id[:80]}",
                    metadata_={"created_by": principal.user_id},
                )
                db.add(tenant)
                try:
                    db.commit()
                except IntegrityError:
                    # Race: otra peticion concurrente creo el mismo tenant primero.
                    db.rollback()
                    tenant = db.scalar(
                        select(Tenant).where(
                            Tenant.external_id == principal.tenant_external_id
                        )
                    )
                    if tenant is None:
                        raise
                db.refresh(tenant)
            # Tombstone: un tenant ``deleted`` nunca se materializa de nuevo
            # (la fila sigue existiendo por external_id). La unica excepcion
            # es el propio DELETE de privacidad, que solo devuelve la
            # respuesta idempotente ``already_deleted`` sin leer ni escribir
            # datos del tenant. Cualquier otro endpoint recibe 403.
            deleted_retry = (
                tenant.status == "deleted"
                and request is not None
                and request.method == "DELETE"
                and request.url.path.rstrip("/") == "/api/privacy/account"
            )
            if tenant.status != "active" and not deleted_retry:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Tenant access is not active",
                )
            db.info["tenant_id"] = tenant.id
            db.info["user_id"] = principal.user_id
            # #E5: el middleware de latencia por endpoint tiene que particionar
            # sus filas por tenant, y el id interno del tenant SOLO se resuelve
            # aqui (la identidad firmada lleva el external_id). request.state
            # vive en scope["state"], que el middleware ya tiene del mismo
            # request, asi que no hace falta resolver el tenant dos veces ni
            # leer cabeceras de autenticacion fuera de get_research_principal.
            if request is not None:
                request.state.tenant_id = tenant.id
        # Idioma de generacion de la peticion (i18n): los servicios que
        # puentean hilos propios (chat) copian db.info, no el contextvar.
        from app.core.i18n import DEFAULT_LANGUAGE, current_language, tenant_stored_language

        language = current_language()
        if language == DEFAULT_LANGUAGE:
            language = tenant_stored_language(db) or DEFAULT_LANGUAGE
        db.info["language"] = language
        yield db
    finally:
        db.rollback()
        db.close()


def init_db() -> None:
    import re

    from sqlalchemy import inspect

    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)

    # The record describes THIS run: a previous degraded startup must not keep
    # a stale entry forever, and a healthy re-run must clear it.
    _SCHEMA_MIGRATION_ERRORS.clear()

    # Lightweight forward-compat for SQLite/dev DBs created before new columns.
    # Every statement is attempted independently through `_execute_optional`
    # (or `_record_schema_migration_error` for the structural rebuild), so one
    # failure is logged at ERROR with the offending statement and the rest of
    # the forward-compat still runs. Nothing here ever blocks startup.
    try:
        inspector = inspect(engine)
        if settings.database_url.startswith("sqlite") and "investment_principles" in (
            inspector.get_table_names()
        ):
            principle_columns = {
                column["name"]
                for column in inspector.get_columns("investment_principles")
            }
            principle_additions = {
                "principle_fingerprint": "VARCHAR(64)",
                "semantic_duplicate_of_id": "INTEGER",
                "canonical_principle_id": "INTEGER",
                "version": "INTEGER NOT NULL DEFAULT 1",
                "superseded_by_id": "INTEGER",
            }
            for column, definition in principle_additions.items():
                if column in principle_columns:
                    continue
                _execute_optional(
                    f"ALTER TABLE investment_principles ADD COLUMN {column}",
                    "ALTER TABLE investment_principles "
                    f"ADD COLUMN {column} {definition}",
                )
            _execute_optional(
                "UPDATE investment_principles SET principle_fingerprint",
                "UPDATE investment_principles "
                "SET principle_fingerprint = lower(hex(randomblob(32))) "
                "WHERE principle_fingerprint IS NULL",
            )
        if "thesis_versions" in inspector.get_table_names():
            columns = {col["name"] for col in inspector.get_columns("thesis_versions")}
            if "input_fingerprint" not in columns:
                _execute_optional(
                    "ALTER TABLE thesis_versions ADD COLUMN input_fingerprint",
                    "ALTER TABLE thesis_versions ADD COLUMN input_fingerprint VARCHAR(64)",
                )
        if "news_events" in inspector.get_table_names():
            columns = {col["name"] for col in inspector.get_columns("news_events")}
            if "metadata" not in columns:
                _execute_optional(
                    "ALTER TABLE news_events ADD COLUMN metadata",
                    "ALTER TABLE news_events ADD COLUMN metadata JSON",
                )
        if settings.database_url.startswith("sqlite"):
            thesis_columns = {
                column["name"]: column
                for column in inspector.get_columns("thesis_versions")
            }
            nullable_thesis_values = (
                "current_price",
                "bear_value",
                "base_value",
                "bull_value",
                "expected_value",
                "margin_of_safety",
            )
            if any(
                not thesis_columns[column]["nullable"]
                for column in nullable_thesis_values
                if column in thesis_columns
            ):
                # SQLite cannot drop NOT NULL in place. Rebuild only this table,
                # preserving its constraints, data and explicit indexes.
                try:
                    with engine.connect() as conn:
                        create_sql = conn.execute(
                            text(
                                "SELECT sql FROM sqlite_master "
                                "WHERE type='table' AND name='thesis_versions'"
                            )
                        ).scalar_one()
                        index_sql = [
                            row[0]
                            for row in conn.execute(
                                text(
                                    "SELECT sql FROM sqlite_master WHERE type='index' "
                                    "AND tbl_name='thesis_versions' AND sql IS NOT NULL"
                                )
                            ).all()
                        ]
                        conn.commit()
                        conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
                        conn.commit()
                        try:
                            with conn.begin():
                                rebuilt = create_sql.replace(
                                    "CREATE TABLE thesis_versions",
                                    "CREATE TABLE thesis_versions__nullable",
                                    1,
                                )
                                for column in nullable_thesis_values:
                                    rebuilt = re.sub(
                                        rf"(\b{column}\b\s+NUMERIC\([^)]+\))\s+NOT NULL",
                                        r"\1",
                                        rebuilt,
                                        count=1,
                                        flags=re.IGNORECASE,
                                    )
                                conn.exec_driver_sql(rebuilt)
                                names = [
                                    row[1]
                                    for row in conn.exec_driver_sql(
                                        "PRAGMA table_info(thesis_versions)"
                                    ).all()
                                ]
                                quoted = ", ".join(f'"{name}"' for name in names)
                                conn.exec_driver_sql(
                                    f"INSERT INTO thesis_versions__nullable ({quoted}) "
                                    f"SELECT {quoted} FROM thesis_versions"
                                )
                                conn.exec_driver_sql("DROP TABLE thesis_versions")
                                conn.exec_driver_sql(
                                    "ALTER TABLE thesis_versions__nullable "
                                    "RENAME TO thesis_versions"
                                )
                                for statement in index_sql:
                                    conn.exec_driver_sql(statement)
                        finally:
                            conn.exec_driver_sql("PRAGMA foreign_keys=ON")
                            conn.commit()
                except Exception as exc:  # noqa: BLE001 — one table, keep migrating
                    _record_schema_migration_error(
                        "REBUILD thesis_versions (drop NOT NULL on "
                        + ", ".join(nullable_thesis_values)
                        + ")",
                        exc,
                    )
                else:
                    inspector = inspect(engine)
            sqlite_forward_columns = {
                "positions": {
                    "portfolio_id": "INTEGER",
                    "base_currency": "VARCHAR(10) NOT NULL DEFAULT 'EUR'",
                    "market_value_native": "NUMERIC(24, 6)",
                    "market_value_base": "NUMERIC(24, 6)",
                    "cost_basis_native": "NUMERIC(24, 6)",
                    "cost_basis_base": "NUMERIC(24, 6)",
                    "unrealized_pnl_base": "NUMERIC(24, 6)",
                    "realized_pnl_base": "NUMERIC(24, 6)",
                    "fx_rate": "NUMERIC(20, 10)",
                },
                "transactions": {"portfolio_id": "INTEGER"},
                "fundamental_model_versions": {
                    "algorithm_version": "VARCHAR(160) NOT NULL DEFAULT 'unknown'",
                    "forecast_fingerprint": "VARCHAR(64) NOT NULL DEFAULT 'unknown'",
                    "market_snapshot_fingerprint": "VARCHAR(64) NOT NULL DEFAULT 'unknown'",
                    "valuation_snapshot_fingerprint": "VARCHAR(64) NOT NULL DEFAULT 'unknown'",
                    "code_commit_sha": "VARCHAR(80) NOT NULL DEFAULT 'unknown'",
                },
                "expectation_reviews": {
                    "actual_metric_id": "INTEGER",
                    "actual_source_type": "VARCHAR(40)",
                    "semantics": "VARCHAR(40) NOT NULL DEFAULT 'higher_is_better'",
                },
                "fundamental_drivers": {
                    "currency": "VARCHAR(10) NOT NULL DEFAULT 'N/A'",
                    "time_basis": "VARCHAR(40) NOT NULL DEFAULT 'point_in_time'",
                    "geography": "VARCHAR(120) NOT NULL DEFAULT 'global'",
                    "segment": "VARCHAR(160) NOT NULL DEFAULT 'consolidated'",
                    "period": "VARCHAR(40) NOT NULL DEFAULT 'unknown'",
                    "source": "VARCHAR(240) NOT NULL DEFAULT 'financial_fact'",
                },
            }
            table_names = set(inspector.get_table_names())
            for table_name, definitions in sqlite_forward_columns.items():
                if table_name not in table_names:
                    continue
                existing = {
                    column["name"] for column in inspector.get_columns(table_name)
                }
                for column_name, definition in definitions.items():
                    if column_name in existing:
                        continue
                    _execute_optional(
                        f'ALTER TABLE "{table_name}" ADD COLUMN "{column_name}"',
                        f'ALTER TABLE "{table_name}" ADD COLUMN '
                        f'"{column_name}" {definition}',
                    )
                inspector = inspect(engine)
            tenant_tables = [
                table.name
                for table in Base.metadata.sorted_tables
                if "tenant_id" in table.columns
                and table.name in inspector.get_table_names()
            ]
            for table_name in tenant_tables:
                columns = {
                    col["name"]
                    for col in inspector.get_columns(table_name)
                }
                if "tenant_id" not in columns:
                    _execute_optional(
                        f'ALTER TABLE "{table_name}" ADD COLUMN tenant_id',
                        f'ALTER TABLE "{table_name}" ADD COLUMN tenant_id INTEGER',
                    )
                    inspector = inspect(engine)
    except Exception as exc:  # noqa: BLE001 — never block startup on optional alter
        # A structural failure (inspection itself, driver refusal) is still not
        # a reason to kill the process, but it is NEVER silent: an unlogged
        # half-migrated schema is how a missing column turns into an unexplained
        # 500 in every query that touches it.
        _record_schema_migration_error("init_db forward-compat block", exc)


def batch_refresh(db: Session, objects: list) -> None:
    """Reload many persistent instances of one model with a single SELECT.

    Equivalent to calling db.refresh on each object, but issues one query
    instead of one per object. All objects must share the same mapped class
    and already be persistent in the session.
    """
    if not objects:
        return
    model = type(objects[0])
    ids = [obj.id for obj in objects]
    db.scalars(
        select(model)
        .where(model.id.in_(ids))
        .execution_options(populate_existing=True)
    ).all()
