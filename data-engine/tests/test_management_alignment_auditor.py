"""Auditor regression probes for PR5354; run from data-engine with pytest."""
from datetime import date
from decimal import Decimal
from types import SimpleNamespace as NS

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models.entities import Base, InsiderTransaction
from app.services.connectors.form4 import parse_form4_xml
from app.services.insider_persistence import persist_filing
from app.services.management_alignment import dilution_years


def test_ticker_change_is_not_a_stock_split():
    company = NS(cik='0000320193', currency='USD', ticker='AAPL')
    facts = [NS(id=year, metric='shares_outstanding', value=Decimal(value), unit='shares',
                period=f'{year}-12-31:FY', fiscal_year=year, fiscal_quarter='FY',
                filed=date(year+1,2,1), source_type='SEC', is_reported=True,
                accession_number=f'0000320193-{str(year+1)[2:]}-000001', source=None)
             for year,value in [(2024,'100'),(2025,'108.2')]]
    rows = dilution_years(facts,company,[NS(action_type='ticker_change',effective_date=date(2025,5,1))],date(2026,11,11))
    assert rows[-1]['shares_change_pct']['value'] == 8.2


def test_normal_reingestion_upgrades_nullable_flag_with_explicit_evidence():
    engine=create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    def xml(flag):
        mark='' if flag is None else f'<aff10b5One>{flag}</aff10b5One>'
        return f'<ownershipDocument><issuer><issuerTradingSymbol>AAPL</issuerTradingSymbol></issuer><nonDerivativeTable><nonDerivativeTransaction><transactionDate><value>2026-10-01</value></transactionDate><transactionCoding><transactionCode>S</transactionCode>{mark}</transactionCoding><transactionAmounts><transactionShares><value>10</value></transactionShares><transactionPricePerShare><value>10</value></transactionPricePerShare></transactionAmounts></nonDerivativeTransaction></nonDerivativeTable></ownershipDocument>'
    with Session(engine) as db:
        db.info['tenant_id']=1
        filing={'accession_number':'0000320193-26-999999','form':'4','filing_date':'2026-10-02','document_url':'https://example.com/form4.xml'}
        persist_filing(db,filing,parse_form4_xml(xml(None)))
        row=db.scalar(select(InsiderTransaction))
        assert row.data_quality['alignment_10b5_1'] is None
        persist_filing(db,filing,parse_form4_xml(xml('1')))
        assert row.data_quality['alignment_10b5_1'] is True
