"""/obsidian/vault.zip: el numero de sentencias no crece con las empresas del vault.

El vault resolvia cada simbolo de watchlist con ``resolve_company`` (una o mas
consultas por simbolo) y cargaba las tesis de cada empresa por separado
(versiones, secciones, claims, evidencias y documentos: hasta cinco consultas
por empresa). Con la cartera de Nico (19 empresas) eran 81 sentencias por
descarga. Ahora los simbolos se resuelven con un IN (``resolve_company`` solo
para los que no casan exacto) y las tesis de todas las empresas salen en una
consulta por tabla. El ZIP resultante es el mismo.
"""

from __future__ import annotations

import io
from datetime import UTC, datetime
from zipfile import ZipFile

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import main
from app.api.routes.obsidian import _load_thesis_notes, _load_thesis_notes_by_company
from app.core.database import get_db
from app.models.entities import (
    Base,
    Claim,
    ClaimEvidence,
    Company,
    Document,
    Position,
    Tenant,
    ThesisSection,
    ThesisVersion,
    WatchItem,
)


def _seed(n: int):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session = Session(engine)
    tenant = Tenant(external_id="obs-perf", name="Test perf")
    session.add(tenant)
    session.flush()
    tenant_id = tenant.id
    session.info["tenant_id"] = tenant_id
    companies = []
    for i in range(n):
        ticker = f"OBS{i:03d}"
        company = Company(
            ticker=ticker, name=f"Empresa {i}", exchange="NYSE", currency="USD",
            sector="Tech", industry="Tech", company_type="standard",
            valuation_model="standard_dcf", special_sources=[], special_risks=[], factor_tags=[],
        )
        session.add(company)
        session.flush()
        companies.append(company)
        # Mitad en cartera, todas en watchlist; la ultima solo en watchlist con sufijo.
        if i % 2 == 0:
            session.add(Position(company_id=company.id, quantity=1, average_cost=10, tenant_id=tenant_id))
        session.add(WatchItem(symbol=ticker, company=company.name, tenant_id=tenant_id))
        for version in (1, 2):
            thesis = ThesisVersion(
                company_id=company.id, version=version, status="final",
                thesis_markdown="" if version == 1 else f"# Tesis {ticker} v2",
                executive_summary=f"Resumen {ticker}. Ver Empresa {(i + 1) % n}.",
                rating="buy", tenant_id=tenant_id,
            )
            session.add(thesis)
            session.flush()
            session.add(ThesisSection(
                thesis_version_id=thesis.id, company_id=company.id, section_key="riesgos", title="Riesgos",
                body=f"Riesgos de {ticker}", order_index=1, tenant_id=tenant_id,
            ))
            claim = Claim(
                company_id=company.id, thesis_version_id=thesis.id,
                statement=f"Afirmación {ticker} v{version}.", status="verified", tenant_id=tenant_id,
            )
            document = Document(
                company_id=company.id, title=f"Doc {ticker}", source_type="filing",
                source_url=f"https://example.org/{ticker}/{version}",
                published_at=datetime(2026, 9, 18, tzinfo=UTC), tenant_id=tenant_id,
            )
            session.add_all([claim, document])
            session.flush()
            session.add(ClaimEvidence(
                claim_id=claim.id, document_id=document.id, summary="Evidencia.", tenant_id=tenant_id,
            ))
    # Simbolo con sufijo de mercado (resuelve al ticker base) y uno sin empresa.
    session.add(WatchItem(symbol="OBS000.L", company="Empresa 0", tenant_id=tenant_id))
    session.add(WatchItem(symbol="NOEXISTE", company=None, tenant_id=tenant_id))
    session.commit()
    session.close()
    scoped = Session(engine)
    scoped.info["tenant_id"] = tenant_id
    return engine, scoped


def _vault(n: int) -> tuple[int, dict[str, bytes]]:
    engine, scoped = _seed(n)

    def _override():
        yield scoped

    main.app.dependency_overrides[get_db] = _override
    statements: list[str] = []
    try:
        listener = lambda *a: statements.append(a[2])  # noqa: E731
        event.listen(engine, "before_cursor_execute", listener)
        response = TestClient(main.app).get("/api/obsidian/vault.zip")
        event.remove(engine, "before_cursor_execute", listener)
    finally:
        main.app.dependency_overrides.clear()
        scoped.close()
        engine.dispose()
    assert response.status_code == 200, response.text
    archive = ZipFile(io.BytesIO(response.content))
    return len(statements), {name: archive.read(name) for name in archive.namelist()}


def test_vault_no_escala_con_las_empresas():
    pocas, _ = _vault(3)
    muchas, ficheros = _vault(15)
    assert muchas == pocas, (pocas, muchas)
    assert pocas <= 16
    # 15 empresas con tesis: cada una tiene sus notas en el ZIP.
    assert sum(1 for name in ficheros if name.endswith(".md") and "Tesis OBS" in name) == 30


def test_vault_simbolos_sin_empresa_y_sufijo_siguen_igual():
    _, ficheros = _vault(3)
    indice = b"\n".join(contenido for nombre, contenido in ficheros.items() if nombre.endswith(".md"))
    assert b"NOEXISTE" in indice
    # OBS000.L resuelve a OBS000: no aparece como simbolo sin empresa.
    assert b"OBS000.L" not in indice


def test_notas_por_lotes_iguales_a_la_carga_por_empresa():
    engine, scoped = _seed(4)
    try:
        companies = list(scoped.query(Company).order_by(Company.id))
        por_lotes = _load_thesis_notes_by_company(scoped, companies)
        for company in companies:
            assert por_lotes[company.id] == _load_thesis_notes(scoped, company)
    finally:
        scoped.close()
        engine.dispose()
