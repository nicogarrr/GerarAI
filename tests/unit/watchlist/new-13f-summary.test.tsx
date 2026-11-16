import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { createElement } from 'react';
import { LocaleProvider } from '@/lib/i18n/client';
import New13fSummary from '@/components/watchlist/New13fSummary';
import { mapNewPositions, type WatchlistNew13f, type WatchlistNew13fItem } from '@/lib/watchlist/new-13f';

// Forma real del contrato de Bottlenecks (0026d2108): GET /api/ownership/institutions/{ticker}
// -> new_positions={status,count,value_known_count,top_by_shares,top_by_value,value_basis}
const holderPayload = (over: Record<string, unknown> = {}): Omit<WatchlistNew13fItem, 'ticker'> => ({
    status: 'ok',
    period: '2026-09-30',
    new_positions: {
        status: 'ok',
        count: 70,
        value_known_count: 2,
        top_by_shares: [
            { cik: '1', name: 'Quadrature Capital', shares: 393_100, value_usd: 23_100_000, filing_url: 'https://www.sec.gov/x' },
            { cik: '2', name: 'Mizuho Markets Americas', shares: 213_400, value_usd: 12_600_000, filing_url: null },
            { cik: '3', name: 'Entropy Technologies', shares: 121_700, value_usd: null, filing_url: null },
        ],
        top_by_value: [],
        value_basis: 'declarado al cierre del trimestre',
    },
    ...over,
});

const render = (data: WatchlistNew13f) => renderToStaticMarkup(createElement(New13fSummary, { data }));

describe('mapNewPositions: del contrato 13F al view-model de watchlist', () => {
    it('mapea conteo real, top por acciones y valor declarado; valor ausente -> null', () => {
        const vm = mapNewPositions('ASTS', holderPayload());
        expect(vm.status).toBe('ok');
        expect(vm.period).toBe('2026-09-30');
        expect(vm.countNew).toBe(70);
        expect(vm.topNew.map((r) => r.fund)).toEqual(['Quadrature Capital', 'Mizuho Markets Americas', 'Entropy Technologies']);
        expect(vm.topNew[0]).toMatchObject({ shares: 393_100, valueApprox: 23_100_000, valueBasis: 'declared' });
        expect(vm.topNew[2].valueApprox).toBeNull(); // ausente: N/D, nunca estimado mezclado
        expect(vm.topTotalShares).toBe(606_500 + 121_700);
        expect(vm.partial).toBe(false);
    });

    it('valor_parcial -> partial declarado (count real, valores no todos conocidos)', () => {
        const payload = holderPayload();
        payload.new_positions!.status = 'valor_parcial';
        payload.new_positions!.value_known_count = 1;
        expect(mapNewPositions('ASTS', payload).partial).toBe(true);
    });

    it('sin_detalle (snapshot legado): count conservado, sin lista inventada', () => {
        const payload = holderPayload();
        payload.new_positions = { status: 'sin_detalle', count: 70, value_known_count: null, top_by_shares: [], top_by_value: [] };
        const vm = mapNewPositions('ASTS', payload);
        expect(vm.status).toBe('count_only');
        expect(vm.countNew).toBe(70);
        expect(vm.topNew).toEqual([]);
    });

    it('sin snapshot o sin dato de conteo -> no_data («Sin datos»), count null nunca 0', () => {
        const vm = mapNewPositions('ASTS', { status: 'sin_datos', reason: 'sin_cusip' });
        expect(vm.status).toBe('no_data');
        const payload = holderPayload();
        payload.new_positions = { status: 'sin_datos', count: null, value_known_count: null, top_by_shares: [], top_by_value: [] };
        expect(mapNewPositions('ASTS', payload).status).toBe('no_data');
    });

    it('0 nuevas de verdad -> 0 mostrado, no ausencia', () => {
        const payload = holderPayload();
        payload.new_positions!.count = 0;
        payload.new_positions!.top_by_shares = [];
        const vm = mapNewPositions('ASTS', payload);
        expect(vm.status).toBe('ok');
        expect(vm.countNew).toBe(0);
    });
});

describe('New13fSummary: render honesto', () => {
    const okVm = mapNewPositions('ASTS', holderPayload());

    it('muestra nº de nuevas con trimestre, las mayores y el total de acciones', () => {
        const html = render(okVm);
        expect(html).toContain('70');
        expect(html).toContain('Quadrature Capital');
        expect(html).toContain('393');
        expect(html.toLowerCase()).toContain('total');
    });

    it('sin snapshot -> «Sin datos», sin cifras inventadas', () => {
        const vm = mapNewPositions('ASTS', { status: 'sin_datos', reason: 'sin_cusip' });
        const html = render(vm);
        expect(html).toContain('Sin datos');
        expect(html).not.toContain('Quadrature');
    });

    it('count_only declara que la lista no está disponible', () => {
        const payload = holderPayload();
        payload.new_positions = { status: 'sin_detalle', count: 70, value_known_count: null, top_by_shares: [], top_by_value: [] };
        const html = render(mapNewPositions('ASTS', payload));
        expect(html).toContain('70');
        expect(html).not.toContain('Quadrature');
    });
});

it('uses only the five largest rows and sums those five, not all holders',()=>{
 const payload=holderPayload();payload.new_positions!.top_by_shares=Array.from({length:10},(_,i)=>({cik:String(i),name:null,shares:10-i,value_usd:0}));
 const vm=mapNewPositions('AAPL',payload);expect(vm.topNew).toHaveLength(5);expect(vm.topTotalShares).toBe(40);expect(vm.topNew[0].fund).toBe('0');expect(vm.topNew[0].valueApprox).toBe(0);
});
it('handles missing count and missing lists without inventing numbers',()=>{
 const payload=holderPayload();payload.new_positions!.count=undefined as unknown as number;expect(mapNewPositions('AAPL',payload).status).toBe('no_data');
 const valid=holderPayload();valid.new_positions!.top_by_shares=undefined as unknown as [];expect(mapNewPositions('AAPL',valid).topNew).toEqual([]);
});
it('renders real zero as zero and partial/unknown values honestly',()=>{
 const p=holderPayload();p.new_positions!.count=0;p.new_positions!.top_by_shares=[];expect(render(mapNewPositions('AAPL',p))).toContain('0 nuevas');
 const v=mapNewPositions('AAPL',holderPayload());v.partial=true;v.topNew[0].valueApprox=0;expect(render(v)).toContain('parciales');
 v.countNew=null;expect(render(v)).toContain('Sin datos');
});

it.each(['es','en'] as const)('%s pluralizes zero, one, and many positions',locale=>{
 for(const count of [0,1,2]){
  const vm=mapNewPositions('AAPL',holderPayload());vm.countNew=count;
  const html=renderToStaticMarkup(<LocaleProvider locale={locale}><New13fSummary data={vm}/></LocaleProvider>);
  const noun=locale==='es'?(count===1?'nueva posición':'nuevas posiciones'):(count===1?'new position':'new positions');
  expect(html).toContain(`${count} ${noun}`);
 }
});
