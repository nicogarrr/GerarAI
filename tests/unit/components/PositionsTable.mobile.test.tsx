import {render,screen,within} from '@testing-library/react';
import {describe,it,expect} from 'vitest';
import {writeFileSync} from 'node:fs';
import {PositionsTable} from '@/components/paper-trading/PositionsTable';
import {LocaleProvider} from '@/lib/i18n/client';
const position={instrumentKey:'A:ASTS',name:'AST SpaceMobile',kind:'accion',currency:'USD',quantity:10,avgCost:40,realizedPnl:50,optionExpiry:null,optionBadge:null} as const;
describe('demo mobile positions',()=>{
 it.each(['es','en'] as const)('all four position fields are labelled in %s',locale=>{
  const {container}=render(<LocaleProvider locale={locale}><PositionsTable positions={[position]}/></LocaleProvider>);
  if(process.env.POSITIONS_PREVIEW)writeFileSync('/tmp/fact-preview.html',`<!doctype html><html><head><link rel="stylesheet" href="/style.css"></head><body class="bg-gray-950 text-gray-100"><main style="padding:16px;max-width:900px;margin:auto">${container.innerHTML}</main></body></html>`);
  const row=screen.getAllByRole('row')[1];
  const labels=locale==='en'?['Quantity','Average cost','Realized']:['Cantidad','Coste medio','Realizado'];
  labels.forEach(label=>expect(within(row).getByText(label,{exact:true})).toBeInTheDocument());
 });
});
it.each(['es','en'] as const)('keeps expired/today option warnings, valuation reasons and money in %s',locale=>{
 const positions=[{...position,instrumentKey:'O:EXPIRED',kind:'opcion',optionExpiry:'2026-08-01',optionBadge:'vencida',realizedPnl:-50},{...position,instrumentKey:'O:TODAY',kind:'opcion',optionExpiry:'2026-08-02',optionBadge:'vence-hoy',realizedPnl:0},{...position,instrumentKey:'A:MISSING'}];
 const valuation={rows:[{...positions[0],status:'no_valorada',marketValue:null,note:'No source',quoteLabel:'Source missing'},{...positions[1],status:'valorada',marketValue:500,unrealizedPnl:-100,unrealizedPct:null,quoteLabel:'Official quote'}],totals:[],coverage:{valued:1,total:3}};
 render(<LocaleProvider locale={locale}><PositionsTable positions={positions as never} valuation={valuation as never}/></LocaleProvider>);
 expect(screen.getAllByText(/No source/).length).toBeGreaterThan(0);
 expect(screen.getAllByText('Official quote').length).toBeGreaterThan(0);
 expect(document.body.textContent).toContain(locale==='en'?'08/01/2026':'01/08/2026');
});
it('a valued row with a staleness warning shows the warning (not just in a title attr)',()=>{
 const option={...position,instrumentKey:'O:ASTS:2026-12-18:call:50:100',kind:'opcion' as const,optionExpiry:null,optionBadge:null,realizedPnl:0};
 const staleNote='La última operación del contrato tiene más de 1 día hábil: la prima puede no reflejar el precio actual.';
 const valuation={rows:[{...option,status:'valorada',marketValue:460,unrealizedPnl:160,unrealizedPct:53.3,quoteLabel:'última operación 12 nov, 15:47 (hora de Nueva York) · diferida',note:staleNote}],totals:[],coverage:{valued:1,total:1}};
 render(<PositionsTable positions={[option]} valuation={valuation as never}/>);
 // Desktop (celda de valoración) y móvil (línea bajo el nombre): el aviso
 // tiene que estar visible en ambos, no escondido en un tooltip.
 expect(screen.getAllByText(staleNote).length).toBeGreaterThanOrEqual(2);
});
it('valued mobile row carries money, percentage and quote without changing the underlying position',()=>{
 const valuation={rows:[{...position,status:'valorada',marketValue:500,unrealizedPnl:100,unrealizedPct:25,quoteLabel:'Source at 10:00'}],totals:[],coverage:{valued:1,total:1}};
 render(<PositionsTable positions={[position]} valuation={valuation as never}/>);
 expect(document.body.textContent).toContain('25 %');
 expect(screen.getAllByText('Source at 10:00').length).toBeGreaterThan(0);
});
