import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFileSync, mkdirSync, writeFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';
import type { PaperTradeView } from '../lib/actions/paper-trading.actions';

const trade: PaperTradeView = {
    id: 1, ticker: 'ASTS', direction: 'long', horizon: 'short', thesis: 'Ejemplo sintético QA, no propuesta real.',
    conviction: '0.6', proposed_entry: '20', stop: '18', target: '24', inference_basis: 'Supuesto de prueba.',
    status: 'pending', currency: 'USD', created_at: '2026-10-16T18:00:00Z', entry_price: null, exit_price: null,
    mark_price: null, mark_at: null, entry_at: null, exit_at: null, realized_pnl: null, unrealized_pnl: null, close_reason: null,
};
async function render(patch: Partial<PaperTradeView> = {}) {
    const ts = await import('typescript');
    const { createElement } = await import('react');
    const { renderToStaticMarkup } = await import('react-dom/server');
    const dir = 'node_modules/.cache/paper-proposal-render';
    mkdirSync(dir, { recursive: true });
    writeFileSync(`${dir}/view.mjs`, ts.transpileModule(readFileSync('components/proPicks/PaperProposalCard.tsx', 'utf8'), {
        compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
    }).outputText.replaceAll("from '@/lib/format'", `from '${pathToFileURL(`${process.cwd()}/lib/format.ts`).href}'`));
    const mod = await import(`${process.cwd()}/${dir}/view.mjs`);
    return renderToStaticMarkup(createElement(mod.PaperProposalCard, { trade: { ...trade, ...patch } }));
}
test('separates proposed levels from observed fills without manufacturing execution', async () => {
    const html = await render();
    for (const text of ['Propuesta del modelo', 'Precios observados', 'Pendiente de entrada', 'Entrada propuesta', 'Entrada simulada', 'No es una orden al broker', 'no es una probabilidad de acierto validada', 'Sin datos']) assert.ok(html.includes(text), text);
    assert.doesNotMatch(html, /NaN|Invalid Date/);
});
test('uses actual currency, source, quantity and dated fills for closed trades', async () => {
    const html = await render({ status: 'closed', currency: 'EUR', quantity: '50', price_source: 'yahoo_finance_spot', entry_price: '20', entry_at: '2026-10-16T18:10:00Z', exit_price: '24', exit_at: '2026-10-16T18:20:00Z', close_reason: 'target', realized_pnl: '200' });
    for (const text of ['EUR', 'yahoo_finance_spot', 'Cantidad simulada (supuesto)', '50', '200', 'Motivo de cierre: Objetivo', '20:10', '20:20']) assert.ok(html.includes(text), text);
});
test('non-finite and missing numbers, invalid dates and conviction outside range are unavailable', async () => {
    const html = await render({ proposed_entry: 'bad', conviction: '8', mark_at: 'bad', quantity: '', mark_price: 'Infinity' });
    assert.doesNotMatch(html, /NaN|Infinity|Invalid Date|800 %/);
    assert.ok((html.match(/Sin datos/g) ?? []).length >= 5);
});
test('real zero values stay zero, short versus five-year and short direction are explicit', async () => {
    const html = await render({ direction: 'short', horizon: 'five_years', status: 'closed', conviction: '0', realized_pnl: '0', close_reason: 'manual' });
    for (const text of ['Corto', 'Tesis 5 años', '0 %', 'Cierre anticipado']) assert.ok(html.includes(text), text);
});
test('model text is escaped, never treated as HTML or an instruction', async () => {
    const html = await render({ thesis: '<script>alert(1)</script>', inference_basis: '<img src=x onerror=alert(1)>' });
    assert.ok(html.includes('&lt;script&gt;alert(1)&lt;/script&gt;'));
    assert.ok(html.includes('&lt;img src=x onerror=alert(1)&gt;'));
    const upper = await render({ thesis: '<SCRIPT>alert(1)</SCRIPT>' });
    assert.ok(upper.includes('&lt;SCRIPT&gt;alert(1)&lt;/SCRIPT&gt;'));
});
test('wiring is read-only, no generation batch, scheduler, manual close or mock production data', () => {
    const view = readFileSync('components/proPicks/PaperTradingView.tsx', 'utf8');
    assert.match(view, /<PaperProposalCard key=\{trade.id\} trade=\{trade\}/);
    assert.doesNotMatch(view, /fetch\(|method:\s*['"]POST|llm-proposals|\/feed|\/close/);
});

test('preserves valid six-decimal levels and fractional quantities instead of rounding to fake zeros', async () => {
    const html = await render({ proposed_entry: '0.004', stop: '0.003', target: '0.008', quantity: '0.0001' });
    for (const text of ['0,004', '0,003', '0,008', '0,0001']) assert.ok(html.includes(text), text);
    const smallest = await render({ proposed_entry: '0.000002', stop: '0.000001', target: '0.000003', quantity: '0.000001' });
    for (const text of ['0,000001', '0,000002', '0,000003']) assert.ok(smallest.includes(text), text);
});
