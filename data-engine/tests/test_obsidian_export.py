"""El ZIP es portable, sin fuentes sintéticas, y no mezcla tesis de tenants."""

import io
from datetime import UTC, datetime
from zipfile import ZipFile

from app.services.obsidian_export import Note, Source, build_obsidian_zip


def test_zip_frontmatter_links_and_source_dates():
    payload = build_obsidian_zip(
        "SAN",
        [
            Note(
                "Tesis SAN v3",
                version=3,
                date="2026-09-23",
                status="draft",
                body="# Análisis",
                sources=[
                    Source(url="https://example.org/report(1)", date="2026-09-20", statement="Margen"),
                    Source(statement="Afirmación sin fuente"),
                ],
            ),
            Note("Tesis SAN v9", version=9, status="insufficient_data"),
        ],
    )
    with ZipFile(io.BytesIO(payload)) as archive:
        assert set(archive.namelist()) == {
            "GerarAI/SAN/SAN - Índice.md",
            "GerarAI/SAN/Tesis SAN v3.md",
            "GerarAI/SAN/Tesis SAN v9.md",
        }
        index = archive.read("GerarAI/SAN/SAN - Índice.md").decode()
        assert "[[Tesis SAN v9]]" in index and "[[Tesis SAN v3]]" in index
        v3 = archive.read("GerarAI/SAN/Tesis SAN v3.md").decode()
        assert 'fecha: "2026-09-23"' in v3
        assert 'fuentes:\n  - "https://example.org/report(1)"' in v3
        assert "[Fuente](<https://example.org/report(1)>) (2026-09-20)" in v3
        assert "Afirmación sin fuente: Sin datos de URL" in v3
        v9 = archive.read("GerarAI/SAN/Tesis SAN v9.md").decode()
        assert 'fecha:' not in v9 and "Sin datos" in v9
        assert "fuentes: []" in v9


def test_invalid_ticker_does_not_escape_archive():
    import pytest

    with pytest.raises(ValueError):
        build_obsidian_zip("../evil", [Note("Unsafe")])


# --------------------------------------------------------------------------
# Vault del tenant (cartera + watchlist): índice global, wikilinks entre
# empresas, índice por ticker y nulos honestos. Mismo estándar que el zip
# por ticker: nada sintético, nada mezclado entre tenants.
# --------------------------------------------------------------------------

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import main
from app.core.database import Base, get_db
from app.models import Claim, ClaimEvidence, Company, Document, Position, Tenant, ThesisVersion, WatchItem
from app.services.obsidian_export import (
    CompanyEntry,
    build_obsidian_vault,
    find_mentions,
)


def _vault_entries():
    return [
        CompanyEntry(
            ticker="ASTS",
            name="AST SpaceMobile",
            sector="Technology",
            industry="Telecom",
            in_portfolio=True,
        ),
        CompanyEntry(
            ticker="RKLB",
            name="Rocket Lab USA",
            sector="Unknown",
            industry="",
            in_portfolio=True,
            in_watchlist=True,
        ),
        CompanyEntry(ticker="SAN", name="Banco Santander", in_watchlist=True),
    ]


def _vault_notes():
    return {
        "ASTS": [
            Note(
                "Tesis ASTS v1",
                version=1,
                date="2026-09-20",
                status="final",
                body="# Tesis\n\nCompite con RKLB en espacio. Rocket Lab USA aparece como comparable.",
                sources=[Source(url="https://example.org/asts", date="2026-09-19", statement="Cobertura")],
            )
        ]
    }


def test_vault_estructura_indice_global_y_por_ticker():
    payload = build_obsidian_vault(_vault_entries(), _vault_notes(), {"ASTS": {"RKLB"}})
    with ZipFile(io.BytesIO(payload)) as archive:
        names = set(archive.namelist())
        assert names == {
            "GerarAI/Índice.md",
            "GerarAI/ASTS/ASTS - Índice.md",
            "GerarAI/ASTS/ASTS.md",
            "GerarAI/ASTS/Tesis ASTS v1.md",
            "GerarAI/RKLB/RKLB - Índice.md",
            "GerarAI/RKLB/RKLB.md",
            "GerarAI/SAN/SAN - Índice.md",
            "GerarAI/SAN/SAN.md",
        }
        index = archive.read("GerarAI/Índice.md").decode()
        assert 'tipo: "indice"' in index and 'fecha: "2026-09-20"' in index
        assert "- [[ASTS - Índice|ASTS]] - AST SpaceMobile" in index
        assert "- [[RKLB - Índice|RKLB]] - Rocket Lab USA" in index
        assert "## Watchlist" in index and "- [[SAN - Índice|SAN]] - Banco Santander" in index
        # ASTS no está en watchlist: no puede aparecer en esa sección.
        watchlist_section = index.split("## Watchlist", 1)[1]
        assert "ASTS" not in watchlist_section


def test_vault_wikilinks_entre_empresas_en_ambas_direcciones():
    payload = build_obsidian_vault(_vault_entries(), _vault_notes(), {"ASTS": {"RKLB"}})
    with ZipFile(io.BytesIO(payload)) as archive:
        asts_index = archive.read("GerarAI/ASTS/ASTS - Índice.md").decode()
        assert "## Empresas relacionadas\n\n- [[RKLB]]" in asts_index
        rklb_company = archive.read("GerarAI/RKLB/RKLB.md").decode()
        assert "## Mencionada en\n\n- [[ASTS]]" in rklb_company
        # RKLB sin tesis: no puede tener "relacionadas" inventadas.
        rklb_index = archive.read("GerarAI/RKLB/RKLB - Índice.md").decode()
        assert "Sin datos: ninguna tesis de RKLB menciona a otras empresas del vault." in rklb_index


def test_vault_nulos_honestos_sin_datos():
    payload = build_obsidian_vault(_vault_entries(), _vault_notes(), {"ASTS": {"RKLB"}})
    with ZipFile(io.BytesIO(payload)) as archive:
        rklb = archive.read("GerarAI/RKLB/RKLB.md").decode()
        assert "- Sector: Sin datos" in rklb and "- Industria: Sin datos" in rklb
        assert "- Rol: En cartera · En watchlist" in rklb
        assert "Sin datos: no hay tesis persistida para RKLB." in rklb
        san_index = archive.read("GerarAI/SAN/SAN - Índice.md").decode()
        assert 'fecha:' not in san_index and 'fuentes: []' in san_index
        assert 'estado: "sin tesis"' in san_index
        asts = archive.read("GerarAI/ASTS/ASTS.md").decode()
        assert 'tipo: "empresa"' in asts and '- "cartera"' in asts


def test_vault_simbolos_sin_empresa_se_listan_sin_inventar():
    payload = build_obsidian_vault(_vault_entries(), _vault_notes(), {}, unresolved_symbols=["xyz123", "XYZ123"])
    with ZipFile(io.BytesIO(payload)) as archive:
        index = archive.read("GerarAI/Índice.md").decode()
        assert "## Símbolos sin empresa en el universo" in index
        assert index.count("- XYZ123 (sin datos de empresa)") == 1
        assert "[[XYZ123" not in index  # nunca wikilink a una nota que no existe


def test_vault_vacio_solo_indice_honesto():
    payload = build_obsidian_vault([], {})
    with ZipFile(io.BytesIO(payload)) as archive:
        assert archive.namelist() == ["GerarAI/Índice.md"]
        index = archive.read("GerarAI/Índice.md").decode()
        assert "Sin datos: no hay posiciones en cartera." in index
        assert "Sin datos: no hay empresas en watchlist." in index
        assert 'fecha:' not in index


def test_vault_rechaza_datos_incoherentes():
    with pytest.raises(ValueError):
        build_obsidian_vault([CompanyEntry(ticker="../evil")], {})
    with pytest.raises(ValueError):
        build_obsidian_vault(_vault_entries(), {"NIO": [Note("Tesis NIO v1")]})
    with pytest.raises(ValueError):
        build_obsidian_vault(_vault_entries(), _vault_notes(), {"ASTS": {"NIO"}})
    with pytest.raises(ValueError):
        build_obsidian_vault(
            _vault_entries(),
            {"ASTS": [Note("Tesis ASTS v1", version=1), Note("Tesis ASTS v1bis", version=1)]},
        )


def test_find_mentions_solo_literales():
    candidates = {"RKLB": "Rocket Lab USA", "SAN": "Banco Santander", "A": "Agilent Technologies"}
    assert find_mentions("Compite con RKLB y con Rocket Lab USA.", candidates) == {"RKLB"}
    assert find_mentions("Banco Santander sube un 3%.", candidates) == {"SAN"}
    # Minúsculas no son mención de ticker; "san" sola no enlaza SAN.
    assert find_mentions("el banco san roque", {"SAN": ""}) == set()
    # Subcadena de un nombre distinto NO enlaza (límite de palabra completo).
    assert find_mentions("La empresa Banco Santanderino no existe.", {"SAN": "Banco Santander"}) == set()
    # Prefijo de otro identificador NO enlaza: guion y punto son adyacentes.
    assert find_mentions("RKLB-OTHER despega", {"RKLB": "Rocket Lab USA"}) == set()
    assert find_mentions("RKLB.OTHER despega", {"RKLB": "Rocket Lab USA"}) == set()
    # Menciones literales reales siguen enlazando en ambos modos.
    assert find_mentions("RKLB despega tras el filing.", {"RKLB": "Rocket Lab USA"}) == {"RKLB"}
    assert find_mentions("BRK.B cae un 2%.", {"BRK": "Berkshire", "BRK.B": "Berkshire B"}) == {"BRK.B"}
    # Tickers de un carácter y nombres cortos/ambigus no enlazan.
    assert find_mentions("A subió", candidates) == set()
    assert find_mentions("", candidates) == set()
    assert find_mentions("Meta sube", {"META": "Meta"}) == set()


def _obsidian_tenant_seed(session: Session, tenant_id: int, company: Company, marker: str) -> None:
    session.info["tenant_id"] = tenant_id
    position = Position(company_id=company.id, quantity=1, average_cost=10, tenant_id=tenant_id)
    watch = WatchItem(symbol=company.ticker, company=company.name, tenant_id=tenant_id)
    thesis = ThesisVersion(
        company_id=company.id,
        version=1,
        status="final",
        thesis_markdown=f"# Tesis {marker}",
        executive_summary=f"Resumen {marker}.",
        rating="buy",
        tenant_id=tenant_id,
    )
    session.add_all([position, watch, thesis])
    session.flush()
    claim = Claim(
        company_id=company.id,
        thesis_version_id=thesis.id,
        statement=f"Afirmación {marker}.",
        status="verified",
        tenant_id=tenant_id,
    )
    document = Document(
        company_id=company.id,
        title=f"Doc {marker}",
        source_type="filing",
        source_url=f"https://example.org/{marker}",
        published_at=datetime(2026, 9, 18, tzinfo=UTC),
        tenant_id=tenant_id,
    )
    session.add_all([claim, document])
    session.flush()
    session.add(
        ClaimEvidence(
            claim_id=claim.id,
            document_id=document.id,
            summary=f"Evidencia {marker}.",
            tenant_id=tenant_id,
        )
    )


@pytest.fixture
def vault_clients():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session = Session(engine)
    tenants = {}
    companies = {}
    for external_id, ticker, name, marker in [
        ("obs-tenant-a", "ACME", "Acme Co", "tenant-a"),
        ("obs-tenant-b", "ZULU", "Zulu Inc", "tenant-b"),
    ]:
        tenant = Tenant(external_id=external_id, name=f"Test {external_id}")
        session.add(tenant)
        session.flush()
        tenants[external_id] = tenant.id
        company = Company(
            ticker=ticker,
            name=name,
            exchange="NYSE",
            currency="USD",
            sector="Unknown",
            industry="Unknown",
            company_type="standard",
            valuation_model="standard_dcf",
            special_sources=[],
            special_risks=[],
            factor_tags=[],
        )
        session.add(company)
        session.flush()
        companies[external_id] = company
        _obsidian_tenant_seed(session, tenant.id, company, marker)
    session.commit()
    session.close()

    sessions = {}
    for external_id, tenant_id in tenants.items():
        scoped = Session(engine)
        scoped.info["tenant_id"] = tenant_id
        sessions[external_id] = scoped

    def _client_for(external_id: str) -> TestClient:
        scoped = sessions[external_id]

        def _override():
            yield scoped

        main.app.dependency_overrides[get_db] = _override
        return TestClient(main.app)

    try:
        yield _client_for
    finally:
        main.app.dependency_overrides.clear()
        for scoped in sessions.values():
            scoped.close()
        engine.dispose()


def test_vault_endpoint_no_mezcla_tenants(vault_clients):
    response_a = vault_clients("obs-tenant-a").get("/api/obsidian/vault.zip")
    assert response_a.status_code == 200, response_a.text[:300]
    assert response_a.headers["content-type"] == "application/zip"
    assert "gerarai-obsidian-vault.zip" in response_a.headers["content-disposition"]
    assert response_a.headers["cache-control"] == "private, no-store"
    with ZipFile(io.BytesIO(response_a.content)) as archive:
        names = set(archive.namelist())
        assert "GerarAI/ACME/ACME.md" in names
        assert "GerarAI/ACME/Tesis ACME v1.md" in names
        # Nada del tenant B: ni carpetas, ni menciones en el índice.
        assert not any("ZULU" in name for name in names)
        index = archive.read("GerarAI/Índice.md").decode()
        assert "ACME" in index and "ZULU" not in index and "Zulu Inc" not in index
        tesis = archive.read("GerarAI/ACME/Tesis ACME v1.md").decode()
        assert "tenant-a" in tesis and "tenant-b" not in tesis
        # Cita real con fuente y fecha del documento del tenant A.
        assert "https://example.org/tenant-a" in tesis
        assert "(2026-09-18)" in tesis

    response_b = vault_clients("obs-tenant-b").get("/api/obsidian/vault.zip")
    assert response_b.status_code == 200
    with ZipFile(io.BytesIO(response_b.content)) as archive:
        names = set(archive.namelist())
        assert "GerarAI/ZULU/ZULU.md" in names
        assert not any("ACME" in name for name in names)
        index = archive.read("GerarAI/Índice.md").decode()
        assert "ZULU" in index and "ACME" not in index


@pytest.fixture
def vault_client_positions():
    """Un tenant con posición viva, posición cerrada en watchlist y cerrada sin watchlist."""
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session = Session(engine)
    tenant = Tenant(external_id="obs-tenant-pos", name="Test posiciones")
    session.add(tenant)
    session.flush()
    companies = {}
    for ticker, name in [("VIVA", "Viva Co"), ("CERRADA", "Cerrada Co"), ("HIST", "Historia Co")]:
        company = Company(
            ticker=ticker,
            name=name,
            exchange="NYSE",
            currency="USD",
            sector="Unknown",
            industry="Unknown",
            company_type="standard",
            valuation_model="standard_dcf",
            special_sources=[],
            special_risks=[],
            factor_tags=[],
        )
        session.add(company)
        session.flush()
        companies[ticker] = company
    session.add(Position(company_id=companies["VIVA"].id, quantity=3, average_cost=10, tenant_id=tenant.id))
    session.add(Position(company_id=companies["CERRADA"].id, quantity=0, average_cost=10, tenant_id=tenant.id))
    session.add(Position(company_id=companies["HIST"].id, quantity=0, average_cost=10, tenant_id=tenant.id))
    session.add(WatchItem(symbol="CERRADA", company="Cerrada Co", tenant_id=tenant.id))
    session.commit()
    tenant_id = tenant.id
    session.close()

    scoped = Session(engine)
    scoped.info["tenant_id"] = tenant_id

    def _override():
        yield scoped

    main.app.dependency_overrides[get_db] = _override
    try:
        yield TestClient(main.app)
    finally:
        main.app.dependency_overrides.clear()
        scoped.close()
        engine.dispose()


def test_vault_posicion_cerrada_no_es_cartera(vault_client_positions):
    response = vault_client_positions.get("/api/obsidian/vault.zip")
    assert response.status_code == 200, response.text[:300]
    with ZipFile(io.BytesIO(response.content)) as archive:
        names = set(archive.namelist())
        assert "GerarAI/VIVA/VIVA.md" in names
        assert "GerarAI/CERRADA/CERRADA.md" in names  # sigue por watchlist
        assert not any("HIST" in name for name in names)  # cerrada sin watchlist: fuera
        index = archive.read("GerarAI/Índice.md").decode()
        cartera = index.split("## Cartera", 1)[1].split("## Watchlist", 1)[0]
        assert "VIVA" in cartera and "CERRADA" not in cartera
        watchlist = index.split("## Watchlist", 1)[1]
        assert "CERRADA" in watchlist
        cerrada = archive.read("GerarAI/CERRADA/CERRADA.md").decode()
        assert '"cartera"' not in cerrada
        assert '- "watchlist"' in cerrada
        assert "- Rol: En watchlist" in cerrada
