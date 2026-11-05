import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

// Header's eager-loading protection stays in header-quote-fallback-guard.
// Only list images opt out of document load and automatic SSR preloads.
describe('nonblocking company logos are limited to list pages', () => {
    for (const path of ['app/(root)/watchlist/page.tsx', 'app/(root)/research/page.tsx']) {
        it(`${path}: every list logo opts in`, () => {
            const source = readFileSync(path, 'utf8');
            const logos = source.match(/<CompanyLogo\b[^>]*\/>/g) ?? [];
            assert.ok(logos.length > 0);
            for (const logo of logos) assert.match(logo, /loading="lazy"/);
        });
    }
    it('single-company detail does not opt in', () => {
        const source = readFileSync('app/(root)/research/[ticker]/page.tsx', 'utf8');
        const logos = source.match(/<CompanyLogo\b[^>]*\/>/g) ?? [];
        assert.ok(logos.length > 0);
        for (const logo of logos) assert.doesNotMatch(logo, /loading="lazy"/);
    });
});
