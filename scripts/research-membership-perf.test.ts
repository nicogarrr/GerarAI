import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
// @ts-expect-error TS5097
import { portfolioMembership } from '../lib/research/portfolio-membership.ts';

test('membership preserves shorts, excludes closed positions and normalizes symbols', () => {
    assert.deepEqual([...portfolioMembership([
        {ticker: ' cost ', quantity: 2}, {ticker: 'SHORT', quantity: -1},
        {ticker: 'CLOSED', quantity: 0}, {ticker: '', quantity: 5},
    ])], ['COST', 'SHORT']);
});

test('research index does not await unused valuation/FX/data-quality summary', () => {
    const page = readFileSync('app/(root)/research/page.tsx', 'utf8');
    assert.doesNotMatch(page, /getPortfolioSummary|portfolioSummary/);
    assert.match(page, /portfolioMembership\(portfolioPositions\)/);
    const action = readFileSync('lib/actions/research.actions.ts', 'utf8').split('export async function getResearchPortfolioPositions')[1];
    assert.match(action, /requireAuthenticatedUser\(\)/);
    // Paginacion completa por page_info.has_next (fetchAllBackendPages, #3413):
    // la firma anterior (paginateAll + limit=2000&offset=) ignoraba la paginacion
    // real del backend (page/page_size, max 200) y repetia la pagina 1.
    assert.match(action, /fetchAllBackendPages\(/);
    assert.match(action, /\/api\/portfolio\/positions\?page=\$\{page\}&page_size=/);
    assert.doesNotMatch(action, /\/summary|\/data-quality/);
});
