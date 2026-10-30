"""Database metrics endpoint for monitoring pool stats and disk usage."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import engine, get_db

router = APIRouter(tags=["admin"])
logger = logging.getLogger(__name__)


def _get_pool_stats() -> dict[str, Any]:
    """Get connection pool statistics.
    
    Returns metrics about the connection pool state including active connections,
    idle connections, and pool configuration.
    """
    try:
        pool = engine.pool
        return {
            "size": pool.size(),
            "checked_out": pool.checkedout(),
            "overflow": pool.overflow(),
            "checked_in": pool.size() - pool.checkedout(),
            "max_overflow": getattr(pool, "_max_overflow", None),
            "pool_size": getattr(pool, "_pool.maxsize", None) if hasattr(pool, "_pool") else None,
            "timeout": getattr(pool, "_timeout", None),
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to collect pool stats: %s", exc)
        return {"error": type(exc).__name__}


def _get_disk_usage(db: Session) -> dict[str, Any]:
    """Get database disk usage metrics.
    
    For PostgreSQL: returns database size and table sizes.
    For SQLite: returns database file size.
    """
    try:
        dialect = db.bind.dialect.name if db.bind else "unknown"
        
        if dialect == "postgresql":
            # Get database size
            db_size_result = db.execute(
                text("SELECT pg_database_size(current_database()) as size")
            ).first()
            db_size_bytes = db_size_result[0] if db_size_result else 0
            
            # Get table sizes (top 10 largest)
            table_sizes = db.execute(
                text("""
                    SELECT 
                        schemaname || '.' || tablename as table_name,
                        pg_total_relation_size(schemaname||'.'||tablename) as total_bytes,
                        pg_relation_size(schemaname||'.'||tablename) as table_bytes,
                        pg_total_relation_size(schemaname||'.'||tablename) - pg_relation_size(schemaname||'.'||tablename) as index_bytes
                    FROM pg_tables
                    WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
                    ORDER BY total_bytes DESC
                    LIMIT 10
                """)
            ).fetchall()
            
            return {
                "dialect": dialect,
                "database_size_bytes": db_size_bytes,
                "database_size_mb": round(db_size_bytes / (1024 * 1024), 2),
                "top_tables": [
                    {
                        "table": row[0],
                        "total_bytes": row[1],
                        "total_mb": round(row[1] / (1024 * 1024), 2),
                        "table_bytes": row[2],
                        "index_bytes": row[3],
                    }
                    for row in table_sizes
                ],
            }
        elif dialect == "sqlite":
            # Get page count and page size
            page_count = db.execute(text("PRAGMA page_count")).scalar()
            page_size = db.execute(text("PRAGMA page_size")).scalar()
            size_bytes = (page_count or 0) * (page_size or 0)
            
            return {
                "dialect": dialect,
                "database_size_bytes": size_bytes,
                "database_size_mb": round(size_bytes / (1024 * 1024), 2),
                "page_count": page_count,
                "page_size": page_size,
            }
        else:
            return {
                "dialect": dialect,
                "error": "Unsupported dialect for disk usage metrics",
            }
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to collect disk usage: %s", exc)
        return {"error": type(exc).__name__, "message": str(exc)}


def _get_table_bloat(db: Session) -> dict[str, Any]:
    """Detect table bloat in PostgreSQL.
    
    Table bloat occurs when deleted or updated rows leave unused space.
    This is PostgreSQL-specific.
    """
    try:
        dialect = db.bind.dialect.name if db.bind else "unknown"
        
        if dialect != "postgresql":
            return {"dialect": dialect, "note": "Table bloat detection only available for PostgreSQL"}
        
        # Simplified bloat detection query
        bloat_results = db.execute(
            text("""
                SELECT
                    schemaname || '.' || tablename as table_name,
                    pg_total_relation_size(schemaname||'.'||tablename) as total_bytes,
                    n_dead_tup,
                    n_live_tup,
                    CASE WHEN n_live_tup > 0
                        THEN round(100.0 * n_dead_tup / (n_live_tup + n_dead_tup), 2)
                        ELSE 0
                    END as dead_tuple_percent
                FROM pg_stat_user_tables
                WHERE n_dead_tup > 1000
                ORDER BY n_dead_tup DESC
                LIMIT 10
            """)
        ).fetchall()
        
        return {
            "dialect": dialect,
            "bloated_tables": [
                {
                    "table": row[0],
                    "total_bytes": row[1],
                    "total_mb": round(row[1] / (1024 * 1024), 2),
                    "dead_tuples": row[2],
                    "live_tuples": row[3],
                    "dead_tuple_percent": float(row[4]),
                }
                for row in bloat_results
            ],
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to detect table bloat: %s", exc)
        return {"error": type(exc).__name__, "message": str(exc)}


async def _collect_metrics(db: Session) -> dict[str, Any]:
    """Collect all database metrics in parallel."""
    pool_stats, disk_usage, table_bloat = await asyncio.gather(
        asyncio.to_thread(_get_pool_stats),
        asyncio.to_thread(_get_disk_usage, db),
        asyncio.to_thread(_get_table_bloat, db),
        return_exceptions=True,
    )
    
    # Handle exceptions from gather
    if isinstance(pool_stats, Exception):
        pool_stats = {"error": type(pool_stats).__name__}
    if isinstance(disk_usage, Exception):
        disk_usage = {"error": type(disk_usage).__name__}
    if isinstance(table_bloat, Exception):
        table_bloat = {"error": type(table_bloat).__name__}
    
    return {
        "pool": pool_stats,
        "disk_usage": disk_usage,
        "table_bloat": table_bloat,
    }


@router.get("/admin/db-metrics")
async def db_metrics(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Get database performance metrics.
    
    Returns:
        - Connection pool statistics (active, idle, max connections)
        - Disk usage (database size, table sizes)
        - Table bloat detection (PostgreSQL only)
    
    This endpoint requires authentication and is intended for monitoring
    and operational visibility.
    """
    return await _collect_metrics(db)
