import { readFileSync } from 'node:fs';
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import CompanyTechnicalChart from '@/components/research/CompanyTechnicalChart';
import type { CompanyMarketSnapshot } from '@/lib/actions/market-workspace.actions';
import { LocaleProvider } from '@/lib/i18n/client';
import type { PriceEvent } from '@/lib/market/price-events';
import { storedEventText } from '@/lib/market/price-events-text';

// company_events_service.stored_timeline_events escribe estos títulos y
// detalles en castellano. Si cambian en el .py, este test avisa.
const SERVICE = readFileSync('data-engine/app/services/company_events_service.py', 'utf8');

const EVENTS: PriceEvent[] = [
    { id: 'earnings-1', date: '2026-10-20', kind: 'results', title: 'Resultados Q3 2026', detail: 'Fecha confirmada por la fuente', source: 'Finnhub' },
    { id: 'earnings-2', date: '2026-10-10', kind: 'results', title: 'Resultados', detail: null, source: 'Finnhub' },
    { id: 'dividend-1', date: '2026-10-05', kind: 'ex_dividend', title: 'Ex-dividendo', detail: '0.26 USD por acción', source: 'Yahoo' },
    { id: 'insider-1', date: '2026-10-01', kind: 'insider', title: 'Tim Cook vende acciones', detail: 'Operación de 1.234.567 $ (formulario 4)', source: 'SEC' },
    { id: 'insider-2', date: '2026-09-30', kind: 'insider', title: 'Un directivo compra acciones', detail: 'Operación de 250.000 $ (formulario 4)', source: 'SEC' },
    { id: 'news-1', date: '2026-09-29', kind: 'news', title: 'Apple presenta nuevos productos', detail: 'Resumen de la fuente', source: 'Reuters' },
];
const SPANISH = /Resultados|Fecha confirmada|Ex-dividendo|por acción|compra acciones|vende acciones|Un directivo|Operación de|formulario/;

vi.mock('@/lib/actions/company-chart.actions', () => ({ getCompanyChartHistory: vi.fn() }));
vi.mock('@/lib/actions/price-events.actions', () => ({
    getChartEvents: vi.fn(async () => ({ events: EVENTS, averageCost: null, firstBuyDate: null, target: null, targetCurrency: null })),
}));
vi.mock('lightweight-charts', () => ({ createChart: () => { throw new Error('no canvas in jsdom'); } }));

const history = Array.from({ length: 60 }, (_, i) => ({
    date: new Date(Date.UTC(2026, 7, 29 + i)).toISOString().slice(0, 10),
    open: 100 + i, high: 103 + i, low: 99 + i, close: 102 + i, volume: null,
}));
const snapshot: CompanyMarketSnapshot = {
    ticker: 'AAPL', name: 'Fixture', exchange: 'NASDAQ', currency: 'USD',
    history, historyCurrency: 'USD', historySource: 'Fixture local', status: 'available',
    quote: { price: null, change: null, changePercent: null, open: null, high: null, low: null, previousClose: null, priceAsOf: null, priceKind: null },
};

describe('gráfico «Precio y eventos»: eventos guardados en inglés', () => {
    it('el backend sigue escribiendo estas frases', () => {
        expect(SERVICE).toContain('"title": f"Resultados {row.fiscal_label}" if row.fiscal_label else "Resultados",');
        expect(SERVICE).toContain('"Fecha confirmada por la fuente" if row.confirmed is True');
        expect(SERVICE).toContain('"title": "Ex-dividendo",');
        expect(SERVICE).toContain('"detail": f"{amount:g} {row.currency} por acción" if amount else None,');
        expect(SERVICE).toContain(`"title": f"{row.insider or 'Un directivo'} {'compra' if row.code == 'P' else 'vende'} acciones",`);
        expect(SERVICE).toContain('detail = f"Operación de {value:,.0f} $ (formulario {row.form})".replace(",", ".")');
    });

    it('resultados, ex-dividendo y directivos salen en inglés; las noticias quedan como vienen', () => {
        const en = EVENTS.map((event) => storedEventText(event, 'en'));
        expect(en.map((event) => event.title)).toEqual([
            'Results Q3 2026', 'Results', 'Ex-dividend', 'Tim Cook sells shares', 'An insider buys shares', 'Apple presenta nuevos productos',
        ]);
        expect(en.map((event) => event.detail)).toEqual([
            'Date confirmed by the source', null, '0.26 USD per share', '$1,234,567 trade (form 4)', '$250,000 trade (form 4)', 'Resumen de la fuente',
        ]);
        expect(EVENTS.map((event) => storedEventText(event, 'es'))).toEqual(EVENTS);
    });

    it('el panel del gráfico pinta los eventos guardados en inglés', async () => {
        render(<LocaleProvider locale="en"><CompanyTechnicalChart snapshot={snapshot} /></LocaleProvider>);
        expect(await screen.findByText('Tim Cook sells shares')).toBeInTheDocument();
        expect(screen.getByText('Results Q3 2026')).toBeInTheDocument();
        const titles = EVENTS.slice(0, 5).map((event) => storedEventText(event, 'en').title).join(' ');
        expect(titles).not.toMatch(SPANISH);
        expect(screen.queryByText(/Resultados|Ex-dividendo|vende acciones/)).toBeNull();
    });
});


it('traduce moneda declarada y avisa cuando el importe no es comparable', () => {
    const base: PriceEvent = { id: 'pdmr', date: '2026-11-13', kind: 'insider', title: 'Ana compra acciones', source: 'tracefour' };
    const known = { ...base, detail: 'Operación de 250.000 GBP (formulario PDMR)' };
    const unknown = { ...base, detail: 'Importe no comparable: divisa o importe no informado (formulario PDMR)' };
    expect(storedEventText(known, 'en').detail).toBe('250,000 GBP trade (form PDMR)');
    expect(storedEventText(unknown, 'en').detail).toBe('Amount not comparable: currency or amount not reported (form PDMR)');
    expect(storedEventText(known, 'es')).toEqual(known);
    expect(storedEventText(unknown, 'es')).toEqual(unknown);
});


it('keeps estimated and unknown dates explicit in both languages', () => {
    const base: PriceEvent = { id: 'estimated', date: '2026-11-20', kind: 'results', title: 'Resultados', source: 'Yahoo Finance' };
    for (const [es, en] of [
        ['Fecha estimada por la fuente; puede cambiar', 'Date estimated by the source; it may change'],
        ['La fuente no indica si la fecha está confirmada', 'The source does not say whether the date is confirmed'],
    ]) {
        expect(storedEventText({ ...base, detail: es }, 'en').detail).toBe(en);
        expect(storedEventText({ ...base, detail: es }, 'es').detail).toBe(es);
    }
});

it('translates uncertain dividend notices from the Spanish catalogue', () => {
    const event: PriceEvent = { id: 'uncertain', date: '2026-11-20', kind: 'ex_dividend', title: 'Ex-dividendo', detail: 'Importe incierto: la fuente guarda varios importes para esta fecha', source: 'yahoo_finance' };
    expect(storedEventText(event, 'en').detail).toBe('Uncertain amount: the source stores several amounts for this date');
    expect(storedEventText(event, 'es')).toEqual(event);
});

it('preserves unrecognized stored source text', () => {
    const base: PriceEvent = {id:'fallback', date:'2026-11-20', kind:'results', title:'Source title', detail:'Source detail', source:'Source'};
    for (const kind of ['results', 'ex_dividend', 'insider'] as const) {
        expect(storedEventText({...base, kind}, 'en')).toEqual({...base, kind});
        expect(storedEventText({...base, kind, detail:null}, 'en')).toEqual({...base, kind, detail:null});
    }
});

it('keeps confirmation and freshness separate in both languages', () => {
    const base: PriceEvent = {id:'stale',date:'2026-11-20',kind:'results',title:'Resultados',source:'Yahoo Finance'};
    for (const [es,en] of [
        ['Fecha confirmada por la fuente\nDato desactualizado: última consulta 2026-10-15; la fecha puede haber cambiado','Date confirmed by the source\nOutdated data: last checked 2026-10-15; the date may have changed'],
        ['La fuente no indica si la fecha está confirmada\nFecha de consulta no disponible; no se puede verificar la vigencia','The source does not say whether the date is confirmed\nLast checked date unavailable; freshness cannot be verified'],
    ]) {
        expect(storedEventText({...base,detail:es},'en').detail).toBe(en);
        expect(storedEventText({...base,detail:es},'es').detail).toBe(es);
    }
    const malformed = 'Dato desactualizado: última consulta UNKNOWN; la fecha puede haber cambiado';
    expect(storedEventText({...base,detail:malformed},'en').detail).toBe(malformed);
});
