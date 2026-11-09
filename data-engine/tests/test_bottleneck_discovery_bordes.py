"""Bordes de ``app.services.bottleneck_discovery_service``.

Lo que demuestra:
- ``_name_tokens`` descarta tokens de pura puntuación ("-" entre nombres):
  la rama 204->202 no deja tokens vacíos en el patrón.
- ``build_mention_patterns`` omite empresas sin patrón posible (ticker
  corto sin nombre): rama 246->244.
- ``validate_output`` rechaza con el motivo exacto un candidato que no es
  dict (411), un ticker que no es str (416) y los candidatos por encima de
  MAX_CANDIDATES (464-465).
- ``save_within_quota`` en dialecto postgresql toma el advisory lock por
  tenant y día con la clave derivada por sha256 exacta (513-515) y, si el
  alta falla, hace rollback y propaga (538-540). La sesión se dobla con un
  fake: SQLite no puede ejecutar la rama específica de PostgreSQL.
- ``discover``: un TimeoutError del proveedor sin deadline activo detiene
  el barrido como "deadline" sin tocar ``deadline.truncated`` (rama
  659->661).

SQLite real en memoria salvo donde se indica; sin red.
"""

import asyncio
import hashlib
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models import Company, NewsEvent, Tenant
from app.services import bottleneck_discovery_service as svc
from app.services.bottleneck_service import refresh_signals

NOW = datetime(2026, 10, 9, 10, tzinfo=UTC)


@pytest.fixture()
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Tenant(id=1, external_id="a"))
        session.commit()
        session.info["tenant_id"] = 1
        yield session
    engine.dispose()


@pytest.fixture()
def quota_locks_local(monkeypatch):
    # ``_quota_locks`` es global: se dobla con un dict local para que los
    # tests no dejen claves permanentes en el estado del módulo.
    local: dict = {}
    monkeypatch.setattr(svc, "_quota_locks", local)
    return local


def test_name_tokens_descarta_tokens_de_pura_puntuacion():
    assert svc._name_tokens("CV Sciences - Inc.") == ["cv", "sciences", "inc"]


def test_build_mention_patterns_omite_empresas_sin_patron(db):
    db.add(
        Company(
            id=1,
            ticker="AB",
            name="",
            exchange="NASDAQ",
            company_type="large_cap",
            valuation_model="dcf",
        )
    )
    db.add(
        Company(
            id=2,
            ticker="NVDA",
            name="NVIDIA",
            exchange="NASDAQ",
            company_type="large_cap",
            valuation_model="dcf",
        )
    )
    db.commit()
    patterns = svc.build_mention_patterns(db)
    assert set(patterns) == {"NVDA"}


def test_validate_output_rechaza_item_no_dict():
    accepted, rejected = svc.validate_output(
        {"candidatos": ["no-es-dict"]}, allowed_ids=set(), known_tickers=set()
    )
    assert accepted == []
    assert rejected == ["candidato_invalido"]


def test_validate_output_rechaza_ticker_no_str():
    accepted, rejected = svc.validate_output(
        {"candidatos": [{"ticker": 123, "exposicion": "x", "canal": "y", "evidence_ids": []}]},
        allowed_ids=set(),
        known_tickers=set(),
    )
    assert accepted == []
    assert rejected == ["ticker_invalido"]


def test_validate_output_rechaza_exceso_de_candidatos():
    candidatos = [
        {"ticker": "NVDA", "exposicion": "x", "canal": "y", "evidence_ids": []}
        for _ in range(svc.MAX_CANDIDATES + 1)
    ]
    accepted, rejected = svc.validate_output(
        {"candidatos": candidatos}, allowed_ids=set(), known_tickers={"NVDA"}
    )
    assert rejected.count("exceso_de_candidatos") == 1
    assert len(accepted) <= svc.MAX_CANDIDATES


def _fake_session(dialect):
    fake = MagicMock()
    fake.info = {"tenant_id": 1}
    fake.get_bind.return_value.dialect.name = dialect
    fake.scalars.return_value = iter([])
    return fake


def _candidate(ticker):
    return SimpleNamespace(ticker=ticker, reasoning="razon", evidence_ids=["news_event:1"])


def test_save_within_quota_pg_advisory_lock(monkeypatch, quota_locks_local):
    fake = _fake_session("postgresql")
    monkeypatch.setattr(svc, "todays_discoveries", lambda db, now: 0)
    context = SimpleNamespace(theme="Semiconductores", n_sources=2)
    saved = svc.save_within_quota(fake, context, [_candidate("NVDA")], "m", NOW)
    assert saved == 1
    expected = (
        int.from_bytes(
            hashlib.sha256(f"bottleneck-discovery-quota:1:{svc._today(NOW)}".encode()).digest()[:8],
            "big",
        )
        >> 1
    )
    llamadas = [c for c in fake.execute.call_args_list if "pg_advisory_xact_lock" in str(c.args[0])]
    assert len(llamadas) == 1
    assert str(llamadas[0].args[0]) == "SELECT pg_advisory_xact_lock(:k)"
    assert llamadas[0].args[1] == {"k": expected}


def test_save_within_quota_rollback_en_error(monkeypatch, quota_locks_local):
    fake = _fake_session("sqlite")
    fake.add.side_effect = RuntimeError("boom")
    monkeypatch.setattr(svc, "todays_discoveries", lambda db, now: 0)
    context = SimpleNamespace(theme="Semiconductores", n_sources=2)
    with pytest.raises(RuntimeError, match="boom"):
        svc.save_within_quota(fake, context, [_candidate("NVDA")], "m", NOW)
    fake.rollback.assert_called_once_with()


def test_save_within_quota_no_contamina_estado_global(monkeypatch):
    # Sentinel en el dict ORIGINAL: dos vueltas de save_within_quota con el
    # dict inyectado deben dejar el original exactamente como estaba.
    sentinel = object()
    original = svc._quota_locks
    monkeypatch.setitem(original, ("sentinela", svc._today(NOW)), sentinel)
    snapshot = dict(original)
    local: dict = {}
    monkeypatch.setattr(svc, "_quota_locks", local)
    monkeypatch.setattr(svc, "todays_discoveries", lambda db, now: 0)
    context = SimpleNamespace(theme="Semiconductores", n_sources=2)
    svc.save_within_quota(_fake_session("sqlite"), context, [_candidate("NVDA")], "m", NOW)
    svc.save_within_quota(_fake_session("sqlite"), context, [_candidate("AMD")], "m", NOW)
    clave = (1, svc._today(NOW))
    assert clave in local
    assert len(local) == 1
    assert original == snapshot


class _Router:
    def resolve(self, request):
        return "space-bunny-free"


class _ProviderTimeout:
    name = "stub"

    def __init__(self):
        self.model_router: Any = _Router()
        self._fallback_model: str | None = None

    async def complete(self, request):
        raise TimeoutError("agotado")


@pytest.fixture()
def db_con_tema():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        session.add(Tenant(id=1, external_id="a"))
        session.commit()
        session.info["tenant_id"] = 1
        session.add(
            Company(
                id=1,
                ticker="NVDA",
                name="NVDA",
                exchange="NASDAQ",
                company_type="large_cap",
                valuation_model="dcf",
            )
        )
        session.add_all(
            [
                NewsEvent(
                    id=1,
                    title="Chip shortages persist",
                    url="https://pub-a.example/n1",
                    date=datetime(2026, 10, 3, tzinfo=UTC),
                ),
                NewsEvent(
                    id=2,
                    title="Escasez de chips durante el trimestre",
                    url="https://pub-b.example/n2",
                    date=datetime(2026, 10, 4, tzinfo=UTC),
                ),
                NewsEvent(
                    id=3,
                    title="Chip shortages worsen further",
                    url=None,
                    date=datetime(2026, 10, 5, tzinfo=UTC),
                ),
            ]
        )
        session.commit()
        refresh_signals(session)
        session.commit()
        yield session
    engine.dispose()


def test_timeout_sin_deadline_no_marca_truncated(db_con_tema):
    result = asyncio.run(svc.discover(db_con_tema, provider=_ProviderTimeout(), now=NOW))
    assert result["status"] == "partial"
    assert result["stop_reason"] == "deadline"
    assert result["saved"] == 0
