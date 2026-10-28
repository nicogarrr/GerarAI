import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
const src = (path: string) => readFileSync(path, 'utf8');
describe('production mobile follow-up touch controls', () => {
    it('enlarges remaining standalone links and disclosures locally', () => {
        for (const path of ['components/research/NewsHeadline.tsx', 'components/historical-stress/HistoricalStressView.tsx', 'components/research/CompanyTechnicalChart.tsx', 'app/(root)/cuellos/page.tsx', 'app/(root)/ownership/page.tsx']) {
            expect(src(path)).toContain('min-h-11');
        }
        expect(src('components/insider/InsiderFeed.tsx')).toContain('inline-flex min-h-11 min-w-11 items-center gap-1');
        expect(src('components/markets/LiveMarketsPanel.tsx')).toContain('<Button className="min-w-11" variant="ghost"');
    });
    it('keeps input sizing scoped instead of changing shared input behavior', () => {
        expect(src('components/ui/input.tsx')).toContain('border-gray-600 h-10');
        expect(src('app/(root)/research/news/page.tsx')).toContain('<Input className="min-h-11"');
        expect(src('app/(root)/research/sources/page.tsx')).toContain('<Input className="min-h-11"');
        expect(src('app/(root)/portfolio/intelligence/page.tsx')).toContain('className="min-h-11 w-24"');
    });
});
