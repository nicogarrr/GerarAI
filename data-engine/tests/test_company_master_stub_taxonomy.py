"""Un stub del buscador (research_candidate/unassigned) recibe la taxonomia del
maestro; una ficha ya decidida no se sobrescribe. Evita que ASTS caiga en
standard_dcf en produccion, donde el seed completo no corre."""

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models import Company
from app.seed import apply_master_taxonomy_to_stubs
from app.valuation.engines.registry import resolve_engine_key


def _db() -> Session:
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine, tables=[Company.__table__])
    return Session(engine)


def _stub(ticker: str, **over) -> Company:
    data = dict(
        ticker=ticker, name=ticker, exchange="UNKNOWN", currency="USD", sector="Unknown",
        industry="Unknown", company_type="research_candidate", valuation_model="unassigned",
        special_sources=[], special_risks=[], factor_tags=[],
    )
    data.update(over)
    return Company(**data)


def test_stub_in_master_gets_pre_revenue_engine():
    db = _db()
    db.add(_stub("ASTS"))
    db.commit()
    company = db.query(Company).filter_by(ticker="ASTS").one()
    assert resolve_engine_key(company) == "standard_dcf"
    assert apply_master_taxonomy_to_stubs(db) == ["ASTS"]
    db.commit()
    db.refresh(company)
    assert company.company_type == "space_telecom_pre_fcf"
    assert resolve_engine_key(company) == "pre_revenue"


def test_decided_company_is_not_overwritten_and_unknown_ticker_untouched():
    db = _db()
    db.add(_stub("ASTS", valuation_model="sotp"))
    db.add(_stub("ZZZZ"))
    db.commit()
    assert apply_master_taxonomy_to_stubs(db) == []
    assert db.query(Company).filter_by(ticker="ASTS").one().valuation_model == "sotp"
    assert db.query(Company).filter_by(ticker="ZZZZ").one().valuation_model == "unassigned"


def test_imported_holding_stub_gets_master_taxonomy_and_identity():
    """KRKNF en prod: importada de IBKR como imported_holding/unassigned con
    sector "Unknown"; el maestro (Kraken Robotics, Industrials/Marine
    robotics) la repara. La divisa nunca se toca."""
    db = _db()
    db.add(_stub("KRKNF", name="KRKNF", company_type="imported_holding"))
    db.commit()
    assert apply_master_taxonomy_to_stubs(db) == ["KRKNF"]
    db.commit()
    company = db.query(Company).filter_by(ticker="KRKNF").one()
    assert company.company_type == "defense_contract_backlog"
    assert company.sector == "Industrials"
    assert company.industry == "Marine robotics"
    assert company.exchange == "OTC"
    assert company.name == "Kraken Robotics"
    assert company.currency == "USD"


def test_master_payload_missing_optional_keys_skips_them(monkeypatch):
    """Un payload del maestro sin una clave de taxonomía o identidad no debe
    reventar ni borrar lo existente. Cubre las ramas `key not in payload` y el
    nombre ya verificado (no placeholder)."""
    from app import seed as seed_module

    monkeypatch.setattr(
        seed_module,
        "COMPANY_MASTER",
        [
            {
                "ticker": "ASTS",
                "company_type": seed_module.STUB_TYPE,
                "valuation_model": seed_module.STUB_MODEL,
                "name": "Astera Labs",
                # Sin special_sources/special_risks/factor_tags ni exchange:
                # esas claves se saltan.
            }
        ],
    )
    db = _db()
    db.add(_stub("ASTS"))
    db.commit()

    assert apply_master_taxonomy_to_stubs(db) == ["ASTS"]
    db.commit()
    company = db.query(Company).filter_by(ticker="ASTS").one()
    assert company.name == "Astera Labs"
    assert company.exchange == "UNKNOWN"
    assert company.factor_tags == []


def test_seed_installs_only_global_taxonomy(monkeypatch):
    """`seed()` no crea usuario, cartera ni evidencia: solo init + maestro."""
    from app import seed as seed_module

    calls: list[str] = []
    monkeypatch.setattr(seed_module, "init_db", lambda: calls.append("init"))
    monkeypatch.setattr(
        seed_module, "ensure_company_master", lambda: calls.append("master")
    )

    seed_module.seed()

    assert calls == ["init", "master"]


def test_real_identity_fields_are_not_overwritten():
    """Un campo de identidad con dato real (no placeholder) no se pisa aunque
    la fila sea un stub reparable."""
    db = _db()
    db.add(_stub("KRKNF", name="KRKNF", sector="Industrials", industry="Marine robotics"))
    db.commit()
    assert apply_master_taxonomy_to_stubs(db) == ["KRKNF"]
    db.commit()
    company = db.query(Company).filter_by(ticker="KRKNF").one()
    # Taxonomia siempre se aplica al stub; identidad real se respeta.
    assert company.company_type == "defense_contract_backlog"
    assert company.sector == "Industrials"
    assert company.exchange == "OTC"  # placeholder "UNKNOWN" -> maestro
