import type { ManagerHoldings, ManagerChanges } from '@/lib/actions/ownership.actions';
export const mobileHoldings: ManagerHoldings = {cik:'1',manager:'Fixture Fund',status:'unverified',report_date:'2026-06-30',coverage:'fixture',holdings:[{
 accession_number:'0001-fixture',is_amendment:true,name_of_issuer:'LONG ISSUER HOLDING CORPORATION WITH MULTIPLE CLASSES',title_of_class:'CLASS A COMMON STOCK',cusip:'123456789',value_usd_thousands:1250000,shares:123456,share_type:'SH',put_call:null,investment_discretion:'SOLE',filing_url:'https://example.com/fixture-13f.xml',
}]};
export const mobileChanges: ManagerChanges = {cik:'1',status:'ok',previous_report:'2022-12-31',latest_report:'2026-06-30',changes:[{
 change:'increased',name_of_issuer:'LONG ISSUER HOLDING CORPORATION WITH MULTIPLE CLASSES',title_of_class:'CLASS A COMMON STOCK',cusip:'123456789',put_call:null,shares_latest:123456,shares_previous:100000,value_usd_thousands_latest:1250000,value_usd_thousands_previous:1000,
}]};
