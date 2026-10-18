import { test } from 'node:test';
import assert from 'node:assert/strict';
// @ts-expect-error Node strip-types requires explicit extension.
import { citationKindLabelFor, toPortfolioChatCitations } from '../lib/chat/citations.ts';
test('preserves backend URL, page and locator; internal source has no invented URL', () => {
    const result = toPortfolioChatCitations([
        { type: 'document_chunk', id: 8, title: 'Informe anual de prueba', page_number: 12, url: 'https://example.org/report.pdf' },
        { type: 'financial_fact', id: 9, title: 'Ingresos 2025' },
    ]);
    assert.equal(result[0]?.url, 'https://example.org/report.pdf');
    assert.equal(result[0]?.page, 12);
    assert.equal(result[0]?.locator, 'document_chunk:8');
    assert.equal(result[1]?.url, null);
    assert.equal(result[1]?.locator, 'financial_fact:9');
});
test('no sources stays empty; unsafe URLs never become links', () => {
    assert.deepEqual(toPortfolioChatCitations([]), []);
    for (const url of ['javascript:alert(1)', 'data:text/html,bad', 'file:///etc/passwd', 'https://user:pass@example.org', 'nvidia.com/fake']) {
        assert.equal(toPortfolioChatCitations([{type: 'document_chunk', id: 1, title: 'Fixture', url}])[0]?.url, null);
    }
});

test('brain action and UI pass citations through', async () => {
    const { readFileSync } = await import('node:fs');
    const action = readFileSync(new URL('../lib/actions/brain.actions.ts', import.meta.url), 'utf8');
    const ui = readFileSync(new URL('../components/brain/GlobalBrain.tsx', import.meta.url), 'utf8');
    assert.match(action, /citations: toPortfolioChatCitations\(response.sources\)/);
    assert.match(ui, /citations: result.citations/);
    assert.match(ui, /<BrainSources citations=\{m.citations\}/);
});

test('chatWithCompany dead code stays removed', async () => {
    const { existsSync } = await import('node:fs');
    assert.equal(existsSync(new URL('../lib/actions/chat.actions.ts', import.meta.url)), false);
});

test('Cerebro enlaza datos propios solo a rutas internas conocidas', () => {
    for (const url of ['/portfolio', '/research/AAPL?view=financials', '/research/MSFT?view=thesis', '/research/AAPL?view=news']) {
        assert.equal(toPortfolioChatCitations([{ type: 'market_price', id: 1, title: 'Dato', url }])[0]?.url, url);
    }
    for (const url of ['//evil.example', '/api/admin', '/research/AAPL?view=financials&redirect=https://evil.example']) {
        assert.equal(toPortfolioChatCitations([{ type: 'market_price', id: 1, title: 'Dato', url }])[0]?.url, null);
    }
});

test('panel Cerebro bloquea y restaura el scroll de fondo', async () => {
    const { readFileSync } = await import('node:fs');
    const ui = readFileSync('components/brain/GlobalBrain.tsx', 'utf8');
    assert.ok(ui.includes("document.body.style.overflow = 'hidden'"));
    assert.ok(ui.includes('document.body.style.overflow = previousOverflow'));
});

test('Cerebro no repite la misma fuente ni la etiqueta de tipo si el título ya la dice', () => {
    const result = toPortfolioChatCitations([
        { type: 'position', id: 7, title: 'Posición GOOGL', url: '/portfolio' },
        { type: 'position', id: 7, title: 'Posición GOOGL', url: '/portfolio' },
    ] as never);
    assert.equal(result.length, 1);
    assert.equal(citationKindLabelFor(result[0]), null);
    assert.equal(citationKindLabelFor({ locator: 'position:9', document: 'GOOGL' }), 'Posición');
});

test('B5: el mismo documento citado por varios fragmentos no se repite en Fuentes', () => {
    const result = toPortfolioChatCitations([
        { type: 'knowledge_chunk', id: 31, title: 'Numantia Patrimonio - Carta 2021', page_number: 4 },
        { type: 'knowledge_chunk', id: 32, title: 'Numantia Patrimonio - Carta 2021', page_number: 4 },
        { type: 'knowledge_chunk', id: 33, title: 'Numantia Patrimonio - Carta 2021', page_number: 9 },
    ]);
    assert.equal(result.length, 2);
    assert.deepEqual(result.map((c) => c.page), [4, 9]);
});
