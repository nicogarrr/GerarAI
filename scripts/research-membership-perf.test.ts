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
    assert.match(action, /paginateAll\(/);
    assert.match(action, /\/api\/portfolio\/positions\?limit=2000&offset=/);
    assert.doesNotMatch(action, /\/summary|\/data-quality/);
});
