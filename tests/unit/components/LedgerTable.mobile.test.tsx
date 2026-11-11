import {render,screen,within} from '@testing-library/react';
import {it,expect} from 'vitest';
import {LedgerTable} from '@/components/paper-trading/LedgerTable';
import {LocaleProvider} from '@/lib/i18n/client';
const row={clientOrderId:'fixture',kind:'accion',symbol:'ASTS',name:'AST SpaceMobile',side:'buy',openClose:'open',quantity:10,status:'filled',fillPrice:40,currency:'USD',fee:0,executedAt:1700000000000,rejectReason:null,createdAt:1700000000000,simulated:true} as const;
it.each(['es','en'] as const)('labels each ledger value on mobile in %s',locale=>{
 render(<LocaleProvider locale={locale}><LedgerTable entries={[row]}/></LocaleProvider>);
 const tr=screen.getAllByRole('row')[1];
 const heads=screen.getAllByRole('columnheader');
 heads.forEach(head=>expect(within(tr).getByText(head.textContent??'',{exact:true})).toBeInTheDocument());
});
it.each(['es','en'] as const)('keeps rejected rows explicitly unfilled and sorts by execution or creation date in %s',locale=>{
 const entries=[{...row,clientOrderId:'sell',symbol:'OPT-SELL',kind:'opcion',side:'sell',openClose:'close',fee:1},{...row,clientOrderId:'reject',symbol:'REJECT',status:'rejected',fillPrice:null,rejectReason:'Fondo insuficiente',executedAt:null,createdAt:1800000000000},{...row,clientOrderId:'fx',kind:'fx',name:'EUR/USD',executedAt:1750000000000},{...row,clientOrderId:'open',symbol:'OPT-OPEN',kind:'opcion',side:'buy',openClose:'open',fee:0,executedAt:1700000001000}];
 render(<LocaleProvider locale={locale}><LedgerTable entries={entries as never}/></LocaleProvider>);
 const rows=screen.getAllByRole('row').slice(1);
 expect(rows[0].textContent).toContain('REJECT');
 expect(rows[1].textContent).toContain('EUR/USD');
 expect(within(rows[0]).getByText(locale==='en'?'Rejected':'Rechazada')).toBeInTheDocument();
 expect(within(rows[0]).getByText(locale==='en'?'N/A':'N/D')).toBeInTheDocument();
 expect(rows[0].textContent).not.toContain('$40');
 expect(rows[2].textContent).toContain('OPT-OPEN');
 expect(rows[3].textContent).toContain('OPT-SELL');
});
