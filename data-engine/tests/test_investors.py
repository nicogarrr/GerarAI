"""Modulo Inversores: tabla fija, CIK revisados y resumen sin inventar datos."""

from datetime import date
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models.entities import Base, FundManager, ManagerHolding
from app.services.investors import (
    INVESTORS,
    NO_13F_NOTE,
    get_investor,
    investor_detail,
    list_investors,
    most_bought,
)
from app.services.manager_holding_ingestion_service import (
    REVIEWED_MANAGERS,
    ManagerHoldingIngestionService,
)


def _db() -> Session:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_slugs_unique_and_every_cik_is_reviewed():
    slugs = [i.slug for i in INVESTORS]
    assert len(slugs) == len(set(slugs))
    ciks = [i.cik for i in INVESTORS if i.cik]
    assert len(ciks) == len(set(ciks))
    for cik in ciks:
        assert cik in REVIEWED_MANAGERS, cik


def test_every_reviewed_manager_has_an_investor_entry():
    assert set(REVIEWED_MANAGERS) == {i.cik for i in INVESTORS if i.cik}


def test_pershing_uses_the_new_cik_not_the_13f_nt_one():
    assert "0002026053" in REVIEWED_MANAGERS
    assert "0001336528" not in REVIEWED_MANAGERS
    ackman = get_investor("ackman")
    assert ackman is not None
    assert ackman.cik == "0002026053"


def test_unlisted_ciks_are_refused():
    # Scion (ultimo 13F nov-2025) y Greenlight (feb-2024) quedan fuera.
    for cik in ("0001649339", "0001079114"):
        assert cik not in REVIEWED_MANAGERS
        result = ManagerHoldingIngestionService().sync_manager(_db(), cik=cik)
        assert result["status"] == "unreviewed_manager"


def test_daily_journal_is_never_labelled_as_munger_portfolio():
    inv = get_investor("daily-journal")
    assert inv is not None and inv.kind == "company"
    assert "munger" not in inv.name.lower()
    assert "munger" not in inv.firm.lower()


def test_investors_without_13f_say_so_and_have_no_numbers():
    db = _db()
    result = list_investors(db)
    by_slug = {i["slug"]: i for i in result["investors"]}
    for slug in ("bezos", "mark-leonard", "quintana", "munger", "nick-sleep", "lynch"):
        item = by_slug[slug]
        assert item["has_13f"] is False
        assert item["cik"] is None
        assert item["note"] == NO_13F_NOTE
        assert item["positions"] is None and item["value_usd_thousands"] is None
        detail = investor_detail(db, slug)
        assert detail is not None and detail["holdings"] == []


def test_unsynced_manager_is_honest_empty_not_zero():
    db = _db()
    item = {i["slug"]: i for i in list_investors(db)["investors"]}["buffett"]
    assert item["has_13f"] is True
    assert item["positions"] is None
    assert item["value_usd_thousands"] is None
    assert item["report_date"] is None


def _holding(manager: FundManager, accession: str, filing: date, cusip: str, value: str, name: str):
    return ManagerHolding(
        manager_id=manager.id,
        accession_number=accession,
        report_date=date(2026, 6, 30),
        filing_date=filing,
        name_of_issuer=name,
        title_of_class="COM",
        cusip=cusip,
        value_usd_thousands=Decimal(value),
        shares=Decimal("100"),
        is_amendment=accession.endswith("2"),
    )


def test_issuer_names_resolve_by_cusip_with_filed_fallback():
    """El nameOfIssuer del 13F viene truncado por la SEC; con referencia por
    CUSIP exacto se muestra el nombre completo y el del filing queda en
    name_of_issuer_filed. Sin referencia, fallback al nombre del filing."""
    from app.models.entities import InstrumentReference

    db = _db()
    manager = FundManager(
        cik="0001067983",
        name=REVIEWED_MANAGERS["0001067983"],
        last_report_date=date(2026, 6, 30),
    )
    db.add(manager)
    db.flush()
    db.add_all(
        [
            _holding(manager, "A-1", date(2026, 8, 14), "037833100", "100", "APPLE INC"),
            _holding(manager, "A-1", date(2026, 8, 14), "060505104", "300", "BANK OF AMERICA"),
        ]
    )
    db.add(
        InstrumentReference(
            ticker_normalized="AAPL",
            name="Apple Inc.",
            cusip="037833100",
            as_of=date(2026, 10, 1),
            source="financedatabase",
        )
    )
    db.commit()
    detail = investor_detail(db, "buffett")
    assert detail is not None
    by_filed = {h["name_of_issuer_filed"]: h for h in detail["holdings"]}
    assert by_filed["APPLE INC"]["name_of_issuer"] == "Apple Inc."
    assert by_filed["BANK OF AMERICA"]["name_of_issuer"] == "BANK OF AMERICA"


def test_most_bought_resolves_issuer_name_by_cusip():
    from app.models.entities import InstrumentReference

    db = _db()
    _two_quarters(db, "0001067983", {"037833100": ("10", "20")})
    db.add(
        InstrumentReference(
            ticker_normalized="AAPL",
            name="Apple Inc.",
            cusip="037833100",
            as_of=date(2026, 10, 1),
            source="financedatabase",
        )
    )
    db.commit()
    result = most_bought(db)
    assert result["items"][0]["name_of_issuer"] == "Apple Inc."
    assert result["items"][0]["name_of_issuer_filed"] == "EMISOR 037833100"


def test_summary_uses_latest_accession_so_amendments_do_not_double_count():
    db = _db()
    manager = FundManager(
        cik="0001067983",
        name=REVIEWED_MANAGERS["0001067983"],
        last_report_date=date(2026, 6, 30),
    )
    db.add(manager)
    db.flush()
    db.add_all(
        [
            _holding(manager, "A-1", date(2026, 8, 14), "037833100", "100", "APPLE INC"),
            _holding(manager, "A-1", date(2026, 8, 14), "060505104", "300", "BANK OF AMERICA"),
            _holding(manager, "A-2", date(2026, 8, 20), "037833100", "150", "APPLE INC"),
            _holding(manager, "A-2", date(2026, 8, 20), "060505104", "250", "BANK OF AMERICA"),
        ]
    )
    db.commit()
    item = {i["slug"]: i for i in list_investors(db)["investors"]}["buffett"]
    assert item["positions"] == 2
    assert item["value_usd_thousands"] == 400.0
    assert item["report_date"] == "2026-06-30"
    detail = investor_detail(db, "buffett")
    assert detail is not None
    assert [h["name_of_issuer"] for h in detail["holdings"]] == ["BANK OF AMERICA", "APPLE INC"]
    assert [h["weight_pct"] for h in detail["holdings"]] == [62.5, 37.5]
    assert "ticker" not in detail["holdings"][0]


def test_unknown_slug_has_no_detail():
    assert investor_detail(_db(), "no-existe") is None


def _two_quarters(db: Session, cik: str, rows: dict[str, tuple[str, str]]):
    """rows: cusip -> (shares Q1, shares Q2); '0' = no existe ese trimestre."""
    manager = FundManager(cik=cik, name=REVIEWED_MANAGERS[cik], last_report_date=date(2026, 6, 30))
    db.add(manager)
    db.flush()
    for cusip, (before, now) in rows.items():
        for period, shares, acc in (
            (date(2026, 3, 31), before, f"{cik}-Q1"),
            (date(2026, 6, 30), now, f"{cik}-Q2"),
        ):
            if shares == "0":
                continue
            db.add(
                ManagerHolding(
                    manager_id=manager.id,
                    accession_number=acc,
                    report_date=period,
                    filing_date=period,
                    name_of_issuer=f"EMISOR {cusip}",
                    title_of_class="COM",
                    cusip=cusip,
                    value_usd_thousands=Decimal("1000000") if period.month == 6 else Decimal("500000"),
                    shares=Decimal(shares),
                    is_amendment=False,
                )
            )


def test_most_bought_counts_buyers_without_inferring_tickers_or_options():
    db = _db()
    _two_quarters(db, "0001067983", {"AAA": ("10", "20"), "BBB": ("0", "5"), "CCC": ("9", "3")})
    _two_quarters(db, "0001061768", {"AAA": ("0", "7"), "CCC": ("1", "1")})
    db.add(
        ManagerHolding(
            manager_id=db.scalar(select(FundManager.id).limit(1)),
            accession_number="0001067983-Q2",
            report_date=date(2026, 6, 30),
            filing_date=date(2026, 6, 30),
            name_of_issuer="EMISOR OPC",
            title_of_class="COM",
            cusip="OPC",
            put_call="Put",
            value_usd_thousands=Decimal("1"),
            shares=Decimal("1"),
            is_amendment=False,
        )
    )
    db.commit()
    result = most_bought(db)
    assert result["status"] == "ok"
    assert result["managers_compared"] == 2
    top = result["items"][0]
    assert top["cusip"] == "AAA" and top["buyers_count"] == 2
    assert top["new_count"] == 1
    assert [i["cusip"] for i in result["items"]] == ["AAA", "BBB"]  # CCC solo vende, OPC es opcion
    assert "ticker" not in top
    # 2026: <value> ya en dolares (1.000.000 por posicion y comprador)
    assert top["value_usd"] == 2_000_000.0


def test_most_bought_without_history_says_sin_datos():
    db = _db()
    result = most_bought(db)
    assert result["status"] == "sin_datos"
    assert result["items"] == []
    assert result["managers_compared"] == 0


def test_most_bought_counts_partial_managers_among_compared():
    db = _db()
    _two_quarters(db, "0001067983", {"AAA": ("10", "20")})
    _two_quarters(db, "0001061768", {"AAA": ("5", "7")})
    baupost = db.scalar(select(FundManager).where(FundManager.cik == "0001061768"))
    baupost.coverage = "partial"
    db.commit()
    result = most_bought(db)
    assert result["managers_compared"] == 2
    assert result["managers_partial"] == 1
