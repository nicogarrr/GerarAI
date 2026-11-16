import { describe, expect, it } from 'vitest';
import { mkdirSync, writeFileSync } from 'node:fs';
import { renderToStaticMarkup } from 'react-dom/server';
import { createElement } from 'react';
import { createTranslator } from '@/lib/i18n/translate';
import { deriveUnifiedViewState, toOpportunityRow, toTrackingRow, type UnifiedPick, type UnifiedResult } from '@/lib/propicks/unified';
import OpportunitiesView from '@/components/proPicks/unified/OpportunitiesView';
import TrackingView from '@/components/proPicks/unified/TrackingView';

// Forma del contrato B1 propicks-unified-v1 (GET /api/propicks/unified).
const datum = (value: number | null, status = 'ok') => ({ status, value, asOf: '2026-11-13' });

const pick = (over: Record<string, unknown> = {}): UnifiedPick => ({
    instrumentId: 'inst-1',
    asOf: '2026-11-13',
    listing: { ticker: 'ACME', name: 'Acme Corp', instrumentStatus: 'active', tradingStatus: 'trading', status: 'listed' },
    quality: { score: datum(82), passed: true, scorePolicyVersion: 'propicks-funnel-v1', reasonCodes: [] },
    valuation: { status: 'ok', price: datum(101.5), marginOfSafety: datum(0.18) },
    dca: { status: 'ok', level: datum(2), periodState: 'confirmed' },
    eligibility: { state: 'investigate' },
    tracking: { held: false, watched: true },
    reviewReasons: [],
    evidenceFlags: [],
    ...over,
} as unknown as UnifiedPick);

const result = (status: UnifiedResult['status'], items: UnifiedPick[], blocks: Record<string, unknown> = {}): UnifiedResult => ({
    schemaVersion: 'propicks-unified-v1',
    status,
    asOf: '2026-11-13',
    coverage: { measured: 1, total: 1 },
    blocks: {
        quality: { status: 'ok' }, valuation: { status: 'ok' }, dca: { status: 'ok' }, tracking: { status: 'ok' },
        ...blocks,
    },
    items,
} as unknown as UnifiedResult);

describe('toTrackingRow: seguimiento desde el contrato', () => {
    it('marca held/watched y conserva reviewReasons sin inventar', () => {
        const row = toTrackingRow(pick({ tracking: { held: true, watched: false }, reviewReasons: ['fundamentals_stale_or_missing'] }));
        expect(row).toMatchObject({ ticker: 'ACME', held: true, watched: false, reviewReasons: ['fundamentals_stale_or_missing'] });
    });
});

describe('OpportunitiesView: estados honestos (wireframes 01-05)', () => {
    const t = createTranslator('es');

    it('ok: filas con calidad, valoración y DCA del contrato; sin aviso', () => {
        const res = result('ok', [pick()]);
        const html = renderToStaticMarkup(createElement(OpportunitiesView, { t, view: deriveUnifiedViewState(res), rows: res.items.map(toOpportunityRow) }));
        expect(html).toContain('ACME');
        expect(html).toContain(t('propicks.unified.qualityPassed'));
        expect(html).toContain(t('propicks.unified.dcaConfirmed'));
        expect(html).not.toContain(t('propicks.unifiedStates.states.partial'));
    });

    it('partial: aviso de Veracidad y ausencia declarada, nunca 50 ni 0 inventado', () => {
        const res = result('partial', [pick({ valuation: { status: 'stale', price: datum(null, 'stale'), marginOfSafety: datum(null, 'stale') } })], { valuation: { status: 'error', error: { kind: 'unavailable' } } });
        const html = renderToStaticMarkup(createElement(OpportunitiesView, { t, view: deriveUnifiedViewState(res), rows: res.items.map(toOpportunityRow) }));
        expect(html).toContain(t('propicks.unifiedStates.states.partial'));
        expect(html).toContain('No disponible');
        expect(html).not.toMatch(/50\/100|0\/100/);
    });

    it('empty: estado vacío de Veracidad, sin filas inventadas', () => {
        const res = result('empty', []);
        const html = renderToStaticMarkup(createElement(OpportunitiesView, { t, view: deriveUnifiedViewState(res), rows: [] }));
        expect(html).toContain(t('propicks.unifiedStates.states.empty'));
        expect(html).not.toContain('ACME');
    });

    it('error timeout: role=alert con el texto del errorKind', () => {
        const res = result('error', [], { quality: { status: 'error', error: { kind: 'timeout' } } });
        const html = renderToStaticMarkup(createElement(OpportunitiesView, { t, view: deriveUnifiedViewState(res), rows: [] }));
        expect(html).toContain('role="alert"');
        expect(html).toContain(t('propicks.unifiedStates.errors.timeout'));
    });

    it('excluded/review_data van fuera de la selección principal', () => {
        const res = result('ok', [pick(), pick({ instrumentId: 'inst-2', listing: { ticker: 'WEAK', name: null, instrumentStatus: 'active', tradingStatus: 'trading', status: 'listed' }, eligibility: { state: 'excluded' } })]);
        const html = renderToStaticMarkup(createElement(OpportunitiesView, { t, view: deriveUnifiedViewState(res), rows: res.items.map(toOpportunityRow) }));
        expect(html).toContain(t('propicks.unified.outOfMainTitle'));
        expect(html.indexOf('WEAK')).toBeGreaterThan(html.indexOf(t('propicks.unified.outOfMainTitle')));
    });
});

describe('TrackingView: qué cambió desde tu revisión (wireframe 08)', () => {
    const t = createTranslator('es');

    it('tarjetas held/watched con motivos de revisión veraces', () => {
        const rows = [pick({ tracking: { held: true, watched: false }, reviewReasons: ['fundamentals_stale_or_missing'] })].map(toTrackingRow);
        const html = renderToStaticMarkup(createElement(TrackingView, { t, rows }));
        expect(html).toContain('ACME');
        expect(html).toContain(t('propicks.unified.trackingSubtitle'));
        expect(html).toContain(t('propicks.unifiedStates.reasons.fundamentals_stale_or_missing'));
        expect(html).not.toMatch(/50\/100/);
    });

    it('sin seguimiento -> lista vacía declarada, sin tarjetas inventadas', () => {
        const html = renderToStaticMarkup(createElement(TrackingView, { t, rows: [] }));
        expect(html).toContain(t('propicks.unifiedStates.states.empty'));
    });
});


describe('branch cases and inherited API codes', () => {
 const t=createTranslator('es');
 it('renders missing/failed quality, forming or absent DCA, and safe unknown eligibility',()=>{
  const rows=[
   toOpportunityRow(pick({listing:{ticker:'ZERO',name:'ZERO',status:'delisted',instrumentStatus:'unknown',tradingStatus:'unknown'},quality:{...pick().quality,score:datum(null,'missing'),passed:null},dca:{...pick().dca,level:datum(null,'missing'),periodState:null},eligibility:{state:'excluded'}})),
   toOpportunityRow(pick({instrumentId:'two',quality:{...pick().quality,passed:false},dca:{...pick().dca,periodState:'forming'},eligibility:{state:'constructor'}})),
  ];
  const html=renderToStaticMarkup(createElement(OpportunitiesView,{t,view:{state:'ok',affectedBlocks:[],asOf:'2026-11-13'},rows}));
  expect(html).toContain(t('propicks.unified.qualityNotPassed'));
  expect(html).toContain(t('propicks.unified.dcaForming'));
  expect(html).toContain(t('propicks.unified.openFile'));
  expect(html).toContain('No disponible');
 });
 it('tracking handles watched-only, null name/flags, empty and inherited reasons',()=>{
  const rows=[toTrackingRow(pick({listing:{...pick().listing,name:null},tracking:{held:false,watched:null},reviewReasons:[]})),toTrackingRow(pick({instrumentId:'two',reviewReasons:['constructor']}))];
  const html=renderToStaticMarkup(createElement(TrackingView,{t,rows}));
  expect(html).toContain(t('propicks.unifiedStates.unknownReason'));
  expect(html).not.toContain('[object');
 });
 it('numeric datum refuses strings and infinity without replacing real zero',()=>{
  expect(toOpportunityRow(pick({quality:{...pick().quality,score:{status:'ok',value:'text'}}})).qualityScore).toBeNull();
  expect(toOpportunityRow(pick({quality:{...pick().quality,score:datum(Infinity)}})).qualityScore).toBeNull();
  expect(toOpportunityRow(pick({quality:{...pick().quality,score:datum(0)}})).qualityScore).toBe(0);
 });
 it.each(['es','en'] as const)('exports %s real views for pixel inspection',locale=>{
  const tr=createTranslator(locale);
  const r=result('partial',[pick(),pick({instrumentId:'two',listing:{...pick().listing,ticker:'REVIEW'},eligibility:{state:'review_data'}})],{valuation:{status:'partial'}});
  const html=renderToStaticMarkup(createElement('main',{className:'space-y-8 p-4'},createElement(OpportunitiesView,{t:tr,view:deriveUnifiedViewState(r),rows:r.items.map(toOpportunityRow)}),createElement(TrackingView,{t:tr,rows:r.items.map(toTrackingRow)})));
  mkdirSync('/tmp/propicks-screens-visual',{recursive:true});writeFileSync(`/tmp/propicks-screens-visual/${locale}.html`,html);
 });
});


it.each(['quality', 'dca'] as const)('does not infer %s from a crossed null field',field=>{
 const t=createTranslator('es');
 const p=pick(field === 'quality' ? {quality:{...pick().quality,passed:null}} : {dca:{...pick().dca,periodState:null}});
 const html=renderToStaticMarkup(createElement(OpportunitiesView,{t,view:deriveUnifiedViewState(result('ok',[p])),rows:[toOpportunityRow(p)]}));
 expect(html).not.toContain(t('propicks.unified.qualityNotPassed'));
 expect(html).not.toContain(t('propicks.unified.dcaForming'));
 expect(html.match(/No disponible/g)).toHaveLength(1);
});
it('encodes slash-containing ticker as one route segment in both views',()=>{
 const t=createTranslator('es');const p=pick({listing:{...pick().listing,ticker:'BRK/B'}});
 const opportunity=renderToStaticMarkup(createElement(OpportunitiesView,{t,view:deriveUnifiedViewState(result('ok',[p])),rows:[toOpportunityRow(p)]}));
 const tracking=renderToStaticMarkup(createElement(TrackingView,{t,rows:[toTrackingRow(p)]}));
 for(const html of [opportunity,tracking]){expect(html).toContain('href="/research/BRK%2FB"');expect(html).not.toContain('href="/research/BRK/B"');}
});
