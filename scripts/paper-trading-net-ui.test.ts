import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFileSync, mkdirSync, writeFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';
import type { PaperTradeView } from '../lib/actions/paper-trading.actions';

const base: PaperTradeView = {
    id: 1, ticker: 'ASTS', direction: 'long', horizon: 'short', thesis: 'Ejemplo sintético QA, no propuesta real.',
    conviction: '0.6', proposed_entry: '20', stop: '18', target: '24', inference_basis: 'Supuesto de prueba.',
    status: 'closed', currency: 'USD', created_at: '2026-10-16T18:00:00Z', entry_price: '20', exit_price: '24',
    mark_price: '24', mark_at: '2026-10-16T18:20:00Z', entry_at: '2026-10-16T18:10:00Z', exit_at: '2026-10-16T18:20:00Z',
    realized_pnl: '200', unrealized_pnl: null, close_reason: 'target',
};
async function render(patch: Partial<PaperTradeView> = {}) {
    const ts = await import('typescript');
    const { createElement } = await import('react');
    const { renderToStaticMarkup } = await import('react-dom/server');
    const dir = 'node_modules/.cache/paper-net-render';
    mkdirSync(dir, { recursive: true });
    writeFileSync(`${dir}/view.mjs`, ts.transpileModule(readFileSync('components/proPicks/PaperProposalCard.tsx', 'utf8'), {
        compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
    }).outputText.replaceAll("from '@/lib/format'", `from '${pathToFileURL(`${process.cwd()}/lib/format.ts`).href}'`));
    const mod = await import(`${process.cwd()}/${dir}/view.mjs?v=${Date.now()}`);
    return renderToStaticMarkup(createElement(mod.PaperProposalCard, { trade: { ...base, ...patch } }));
}

test('closed trade shows net result, fees labelled supuesto and dividends with source', async () => {
    const html = await render({
        realized_pnl_net: '196.5', entry_fee: '2', exit_fee: '1.5', cost_label: 'supuesto',
        cost_assumption_version: 'supuesto-v1|fija=1.00|spread_bps=5',
        dividends_total: '1', dividends_count: 1, dividends_uncertain: 0, dividends_wrong_currency: 0,
        dividends_source: 'Yahoo Finance chart/dividends (fallback FMP), via DividendRecord',
    });
    assert.ok(html.includes('Resultado neto simulado'), 'neto');
    assert.ok(html.includes('196,5'), 'importe neto');
    assert.ok(html.toLowerCase().includes('supuesto'), 'rotulo supuesto');
    assert.ok(html.includes('Dividendos'), 'dividendos');
    assert.ok(html.includes('Yahoo'), 'fuente dividendos');
});

test('legacy trade without costs shows net as unavailable, never fabricated', async () => {
    const html = await render({ realized_pnl_net: null });
    assert.ok(html.includes('Resultado neto simulado'));
    assert.ok(html.includes('Sin datos'));
    assert.ok(!html.includes('Costes simulados'));
});

test('uncertain and foreign-currency dividends are surfaced, not hidden', async () => {
    const html = await render({
        realized_pnl_net: '196.5', entry_fee: '2', exit_fee: '1.5', cost_label: 'supuesto',
        dividends_total: '0', dividends_count: 0, dividends_uncertain: 1, dividends_wrong_currency: 2,
        dividends_source: 'Yahoo Finance chart/dividends, via DividendRecord',
    });
    assert.ok(html.includes('incierto'), 'incierto');
    assert.ok(html.includes('otra divisa'), 'otra divisa');
});

test('closed trade distorted by a split shows the warning and keeps the close intact', async () => {
    const html = await render({ corporate_action_warning: 'split_cerrado_sin_ajustar' });
    assert.ok(html.includes('Split declarado'), 'aviso split');
    assert.ok(html.includes('excluid'), 'excluida de estadisticas');
});

test('pending trade blocked by a split explains why there is no fill', async () => {
    const html = await render({ status: 'pending', entry_price: null, entry_at: null, mark_price: null, mark_at: null, exit_price: null, exit_at: null, realized_pnl: null, corporate_action_warning: 'split_pendiente_sin_ajustar' });
    assert.ok(html.includes('Split declarado'), 'aviso split');
    assert.ok(html.includes('no comparable') || html.includes('sin ejecución') || html.includes('no se ejecuta'), 'sin fill');
});

test('split adjustment on an open trade is visible with its source', async () => {
    const html = await render({ status: 'open', realized_pnl: null, realized_pnl_net: null, unrealized_pnl: '40', split_adjustments: 1, last_corporate_action: 'split 2026-10-15 x4 (fuente: yahoo_finance)' });
    assert.ok(html.includes('Ajustada por split'), 'ajuste');
    assert.ok(html.includes('yahoo_finance'), 'fuente');
});
