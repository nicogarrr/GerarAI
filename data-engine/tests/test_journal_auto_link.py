"""Enlace automatico decision del diario <-> operacion (IBKR o manual).

Solo cuando la correspondencia es inequivoca; ante varias posibles no se
asigna nada; nunca se reescribe la decision ni se tocan ordenes.
"""

from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine

from app.core.database import Base
from app.models import Company, Transaction
from app.services.fundamental_review_service import DecisionJournalService
from app.services.ibkr_import_service import IBKRImportService
from app.services.journal_trade_link import (
    AUTO_LINK_WINDOW_DAYS,
    auto_link_journal_trades,
)
from tests.test_ibkr_import import _tenant_session


def _db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return _tenant_session(engine)


def _company(db, ticker="UBER"):
    company = Company(
        ticker=ticker, name=ticker, exchange="NYSE", currency="USD", sector="T", industry="T",
        company_type="standard", valuation_model="standard_dcf", special_sources=[],
        special_risks=[], factor_tags=[],
    )
    db.add(company)
    db.commit()
    return company


_seq = iter(range(1, 10_000))


def _trade(db, company, day, action="buy", qty="10"):
    n = next(_seq)
    tx = Transaction(
        company_id=company.id, trade_date=day, action=action, quantity=Decimal(qty),
        price=Decimal("70"), fees=Decimal("1"), currency="USD", external_id=f"ibkr-t{n}",
    )
    db.add(tx)
    db.commit()
    return tx


def _entry(db, company, decision="buy", day=date(2026, 3, 10)):
    entry = DecisionJournalService().create(
        db, company, decision=decision, rationale="motivo de prueba", what_must_be_true=[]
    )
    entry.decision_date = day
    db.commit()
    return entry


def test_unique_match_links_without_touching_the_decision():
    db = _db()
    c = _company(db)
    entry = _entry(db, c)
    price_before = entry.price
    trade = _trade(db, c, date(2026, 3, 11))
    assert auto_link_journal_trades(db) == {"linked": 1, "ambiguous": 0, "unlinked": 0}
    db.commit()
    db.refresh(entry)
    assert entry.transaction_id == trade.id
    assert entry.decision_date == date(2026, 3, 10)  # fecha de decision intacta
    assert entry.price == price_before
    assert entry.metadata_["auto_link"]["status"] == "linked"


def test_decisions_without_operation_are_never_linked():
    db = _db()
    c = _company(db)
    for decision in ("hold", "watch", "avoid"):
        _entry(db, c, decision)
    _trade(db, c, date(2026, 3, 10))
    assert auto_link_journal_trades(db) == {"linked": 0, "ambiguous": 0, "unlinked": 0}


def test_wrong_side_or_outside_window_is_not_linked():
    db = _db()
    c = _company(db)
    entry = _entry(db, c, "buy")
    _trade(db, c, date(2026, 3, 10), action="sell")
    _trade(db, c, date(2026, 3, 10 + AUTO_LINK_WINDOW_DAYS + 1))
    assert auto_link_journal_trades(db) == {"linked": 0, "ambiguous": 0, "unlinked": 0}
    db.refresh(entry)
    assert entry.transaction_id is None


def test_trim_matches_a_sale():
    db = _db()
    c = _company(db)
    entry = _entry(db, c, "trim")
    sale = _trade(db, c, date(2026, 3, 10), action="sell")
    auto_link_journal_trades(db)
    db.commit()
    db.refresh(entry)
    assert entry.transaction_id == sale.id


def test_several_candidate_trades_stay_unlinked_and_are_flagged():
    db = _db()
    c = _company(db)
    entry = _entry(db, c)
    a = _trade(db, c, date(2026, 3, 10), qty="4")
    b = _trade(db, c, date(2026, 3, 10), qty="6")  # ejecucion parcial
    assert auto_link_journal_trades(db) == {"linked": 0, "ambiguous": 1, "unlinked": 0}
    db.commit()
    db.refresh(entry)
    assert entry.transaction_id is None
    assert entry.metadata_["auto_link"] == {
        "status": "ambiguous",
        "candidate_transaction_ids": sorted([a.id, b.id]),
        "at": entry.metadata_["auto_link"]["at"],
    }


def test_two_decisions_one_trade_links_neither():
    db = _db()
    c = _company(db)
    e1 = _entry(db, c, day=date(2026, 3, 9))
    e2 = _entry(db, c, day=date(2026, 3, 10))
    _trade(db, c, date(2026, 3, 10))
    assert auto_link_journal_trades(db) == {"linked": 0, "ambiguous": 2, "unlinked": 0}
    db.commit()
    db.refresh(e1), db.refresh(e2)
    assert e1.transaction_id is None and e2.transaction_id is None


def test_already_linked_trade_is_not_reused():
    db = _db()
    c = _company(db)
    trade = _trade(db, c, date(2026, 3, 10))
    first = DecisionJournalService().create(
        db, c, decision="buy", rationale="ya enlazada", what_must_be_true=[],
        transaction_id=trade.id,
    )
    later = _entry(db, c)
    assert auto_link_journal_trades(db) == {"linked": 0, "ambiguous": 0, "unlinked": 0}
    db.refresh(later)
    assert later.transaction_id is None and first.transaction_id == trade.id


def test_manual_unlink_is_respected_and_idempotent():
    db = _db()
    c = _company(db)
    entry = _entry(db, c)
    trade = _trade(db, c, date(2026, 3, 10))
    auto_link_journal_trades(db)
    db.commit()
    DecisionJournalService().link_transaction(db, c, entry.id, None)
    assert auto_link_journal_trades(db) == {"linked": 0, "ambiguous": 0, "unlinked": 0}
    db.refresh(entry)
    assert entry.transaction_id is None
    # volver a enlazar a mano limpia la marca y deja el enlace
    DecisionJournalService().link_transaction(db, c, entry.id, trade.id)
    db.refresh(entry)
    assert entry.transaction_id == trade.id and "auto_link" not in entry.metadata_
    assert auto_link_journal_trades(db) == {"linked": 0, "ambiguous": 0, "unlinked": 0}


def test_other_company_trade_is_not_linked():
    db = _db()
    c = _company(db, "UBER")
    other = _company(db, "LYFT")
    entry = _entry(db, c)
    _trade(db, other, date(2026, 3, 10))
    assert auto_link_journal_trades(db) == {"linked": 0, "ambiguous": 0, "unlinked": 0}
    db.refresh(entry)
    assert entry.transaction_id is None


def test_creating_a_decision_after_the_import_links_it_when_unambiguous():
    db = _db()
    c = _company(db)
    trade = _trade(db, c, date.today())
    entry = DecisionJournalService().create(
        db, c, decision="buy", rationale="registrada tras importar", what_must_be_true=[]
    )
    assert entry.transaction_id == trade.id


def test_ibkr_csv_import_links_a_pending_decision():
    db = _db()
    c = _company(db, "QAZ1")
    entry = _entry(db, c, "buy", day=date(2026, 1, 5))
    result = IBKRImportService().import_ibkr_csv(
        db, "symbol,action,quantity,price,date,fees,currency\nQAZ1,buy,10,100,2026-01-06,0,USD\n"
    )
    assert result["trades_imported"] == 1
    db.refresh(entry)
    imported = db.query(Transaction).one()
    assert entry.transaction_id == imported.id
    assert entry.decision_date == date(2026, 1, 5)


def test_trade_before_the_decision_is_not_linked():
    """Una compra anterior pudo responder a otro razonamiento: no se asocia por proximidad."""
    db = _db()
    c = _company(db)
    entry = _entry(db, c, day=date(2026, 3, 10))
    _trade(db, c, date(2026, 3, 9))
    assert auto_link_journal_trades(db) == {"linked": 0, "ambiguous": 0, "unlinked": 0}
    db.refresh(entry)
    assert entry.transaction_id is None


def test_same_day_trade_is_a_candidate():
    db = _db()
    c = _company(db)
    entry = _entry(db, c, day=date(2026, 3, 10))
    trade = _trade(db, c, date(2026, 3, 10))
    auto_link_journal_trades(db)
    db.commit()
    db.refresh(entry)
    assert entry.transaction_id == trade.id


def test_incompatible_price_in_same_currency_is_vetoed_but_other_currency_is_not():
    db = _db()
    c = _company(db)  # divisa USD
    entry = _entry(db, c)
    entry.price = Decimal("200")  # la operacion fue a 70: -65 %
    db.commit()
    _trade(db, c, date(2026, 3, 10))
    assert auto_link_journal_trades(db) == {"linked": 0, "ambiguous": 0, "unlinked": 0}
    db.refresh(entry)
    assert entry.transaction_id is None
    # Misma empresa, operacion en otra divisa: no hay precio comparable, no se veta.
    c2 = _company(db, "SAN")
    e2 = _entry(db, c2)
    e2.price = Decimal("200")
    db.commit()
    eur = _trade(db, c2, date(2026, 3, 10))
    eur.currency = "EUR"
    db.commit()
    assert auto_link_journal_trades(db)["linked"] == 1


def test_later_fill_makes_an_auto_link_ambiguous_and_undoes_it():
    """Repro del revisor: 1er fill enlaza solo; un 2o fill el mismo dia ya no es inequivoco."""
    db = _db()
    c = _company(db)
    entry = _entry(db, c)
    first = _trade(db, c, date(2026, 3, 10), qty="4")
    auto_link_journal_trades(db)
    db.commit()
    db.refresh(entry)
    assert entry.transaction_id == first.id
    second = _trade(db, c, date(2026, 3, 10), qty="6")
    assert auto_link_journal_trades(db) == {"linked": 0, "ambiguous": 1, "unlinked": 1}
    db.commit()
    db.refresh(entry)
    assert entry.transaction_id is None
    assert entry.metadata_["auto_link"]["status"] == "ambiguous"
    assert entry.metadata_["auto_link"]["candidate_transaction_ids"] == sorted([first.id, second.id])
    # y es estable: otra pasada no vuelve a enlazar sola
    assert auto_link_journal_trades(db)["linked"] == 0


def test_later_second_decision_undoes_auto_link_of_the_first():
    db = _db()
    c = _company(db)
    e1 = _entry(db, c, day=date(2026, 3, 9))
    trade = _trade(db, c, date(2026, 3, 10))
    auto_link_journal_trades(db)
    db.commit()
    db.refresh(e1)
    assert e1.transaction_id == trade.id
    e2 = _entry(db, c, day=date(2026, 3, 10))
    assert auto_link_journal_trades(db)["unlinked"] == 1
    db.commit()
    db.refresh(e1), db.refresh(e2)
    assert e1.transaction_id is None and e2.transaction_id is None


def test_manual_link_is_never_undone_by_new_fills():
    db = _db()
    c = _company(db)
    entry = _entry(db, c)
    first = _trade(db, c, date(2026, 3, 10), qty="4")
    DecisionJournalService().link_transaction(db, c, entry.id, first.id)
    _trade(db, c, date(2026, 3, 10), qty="6")
    assert auto_link_journal_trades(db) == {"linked": 0, "ambiguous": 0, "unlinked": 0}
    db.refresh(entry)
    assert entry.transaction_id == first.id
