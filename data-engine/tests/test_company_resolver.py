"""Contratos de resolve_company: exacto gana, fallback solo con sufijo conocido.

La píldora de búsqueda navega a /research/SAN.MC mientras el universo usa
tickers base (SAN). El fallback resuelve europeas sin tocar tickers reales
con punto (BRK.B) ni sufijos desconocidos.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.entities import Base, Company
from app.services.company_resolver import resolve_company


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    with factory() as session:
        session.info["tenant_id"] = "tenant-test"
        yield session


def _company(db, ticker: str) -> Company:
    company = Company(
        ticker=ticker, name=ticker, exchange="X", currency="EUR",
        sector="S", industry="I", company_type="holding",
        valuation_model="unassigned", special_sources=[], special_risks=[],
        factor_tags=[],
    )
    db.add(company)
    db.flush()
    return company


def test_exact_match_wins(db):
    base = _company(db, "SAN")
    assert resolve_company(db, "SAN").id == base.id
    assert resolve_company(db, "san").id == base.id  # case-insensitive


def test_known_suffix_falls_back_to_base(db):
    base = _company(db, "SAN")
    assert resolve_company(db, "SAN.MC").id == base.id
    assert resolve_company(db, "san.mc").id == base.id


def test_exact_match_beats_suffix_fallback(db):
    base = _company(db, "SAN")
    dotted = _company(db, "SAN.MC")
    assert resolve_company(db, "SAN.MC").id == dotted.id
    assert resolve_company(db, "SAN").id == base.id


def test_unknown_suffix_never_falls_back(db):
    _company(db, "BRK")
    assert resolve_company(db, "BRK.B") is None  # tickers reales con punto intactos


def test_dotless_miss_returns_none(db):
    assert resolve_company(db, "NOEXISTE") is None


def test_suffix_without_base_company_returns_none(db):
    assert resolve_company(db, "FALTA.MC") is None


def test_us_share_class_dash_resolves_to_master_dot(db):
    """BRK-B (notacion Yahoo/SEC) resuelve a la ficha BRK.B del master."""
    brk = _company(db, "BRK.B")
    assert resolve_company(db, "BRK-B").id == brk.id
    assert resolve_company(db, "brk-b").id == brk.id


def test_us_share_class_dot_resolves_to_master_dash(db):
    """Simetrico: si el master guardara guion, el punto tambien resuelve."""
    brk = _company(db, "BRK-B")
    assert resolve_company(db, "BRK.B").id == brk.id


def test_share_class_exact_match_still_wins(db):
    dashed = _company(db, "BRK-B")
    _company(db, "BRK.B")
    assert resolve_company(db, "BRK-B").id == dashed.id


def test_share_class_variant_never_creates_identity(db):
    _company(db, "BRK.A")
    assert resolve_company(db, "BRK-B") is None  # variante distinta: no es la clase A
    assert resolve_company(db, "BTC-USD") is None  # sufijo >1 letra: no es clase US


def test_resolve_companies_share_class_bulk(db):
    from app.services.company_resolver import resolve_companies

    brk = _company(db, "BRK.B")
    companies, missing = resolve_companies(db, ["BRK-B", "AAPL"])
    assert [c.id for c in companies] == [brk.id]
    assert missing == ["AAPL"]


def _ref(db, ticker, figi=None, composite=None):
    from app.models.entities import InstrumentReference

    row = InstrumentReference(
        ticker_normalized=ticker, figi=figi, composite_figi=composite,
        source="financedatabase",
    )
    db.add(row)
    db.flush()
    return row


def test_reference_candidates_rename_resolves_to_same_company(db):
    """Renombre por corporate action: el ticker viejo (sin Company) resuelve
    al nuevo via FIGI compartido en la referencia (seam aditivo)."""
    nuevo = _company(db, "NEWN")
    _ref(db, "OLDN", figi="BBG000X1", composite="BBG000C1")
    _ref(db, "NEWN", figi="BBG000X2", composite="BBG000C1")
    assert resolve_company(db, "oldn") is not None
    assert resolve_company(db, "oldn").id == nuevo.id


def test_reference_candidates_without_figi_falls_through(db):
    """Fila de referencia sin FIGI ni composite: no aporta candidatos y el
    fallback de sufijos sigue igual (miss -> None)."""
    _ref(db, "NOFIGI")
    assert resolve_company(db, "NOFIGI") is None


def test_reference_candidates_error_degrades_to_empty(db, monkeypatch):
    """Si la expansion FIGI lanza a mitad, el seam degrada a sin candidatos
    (politica todo-o-nada) y el resolver sigue con sufijos."""
    import app.services.company_resolver as cr

    monkeypatch.setattr(
        cr, "figi_sibling_tickers", lambda db, row: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    _ref(db, "FAILFIGI", figi="BBG000F1")
    assert resolve_company(db, "FAILFIGI") is None


def test_resolve_company_uses_pinned_catalog_for_exact_match(db):
    """Con el catalogo pineado (tanda de ingesta) el match exacto sale de la
    lista en memoria; el fallback de sufijos sigue consultando la BD."""
    from app.services.company_catalog import pinned_catalog

    san = _company(db, "SAN")
    with pinned_catalog(db):
        assert resolve_company(db, "SAN").id == san.id
        # No esta en el catalogo: cae a referencia/variantes/sufijo con BD.
        assert resolve_company(db, "SAN.MC").id == san.id


def test_resolve_companies_reference_seam_bulk(db):
    """La via en lote tambien expande por FIGI los pendientes tras el exacto."""
    nuevo = _company(db, "NEWB")
    _ref(db, "OLDB", figi="BBG000Y1", composite="BBG000D1")
    _ref(db, "NEWB", figi="BBG000Y2", composite="BBG000D1")
    _ref(db, "NOFIGIB")
    from app.services.company_resolver import resolve_companies

    companies, missing = resolve_companies(db, ["OLDB", "NOFIGIB", "BRK-B"])
    assert [c.id for c in companies] == [nuevo.id]
    assert missing == ["NOFIGIB", "BRK-B"]


def test_resolve_companies_reference_error_keeps_exact_only(db, monkeypatch):
    """Fallo de la referencia en lote: exactos y sufijos sobreviven, FIGI no."""
    nuevo = _company(db, "NEWC")
    _ref(db, "OLDC", figi="BBG000Z1")
    import app.services.company_resolver as cr

    real_select = cr.select

    def boom_select(*args, **kwargs):
        from app.models.entities import InstrumentReference

        if args and args[0] is InstrumentReference:
            raise RuntimeError("tabla rota")
        return real_select(*args, **kwargs)

    monkeypatch.setattr(cr, "select", boom_select)
    from app.services.company_resolver import resolve_companies

    companies, missing = resolve_companies(db, ["OLDC", "NEWC"])
    assert [c.id for c in companies] == [nuevo.id]
    assert missing == ["OLDC"]


def test_resolve_companies_empty_and_blank(db):
    from app.services.company_resolver import resolve_companies

    assert resolve_companies(db, []) == ([], [])
    assert resolve_companies(db, ["", "  "]) == ([], [])
