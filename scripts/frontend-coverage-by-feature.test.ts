import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

const { classify, summarize, render, OTHER } = await import('./frontend-coverage-by-feature.mjs');

describe('frontend-coverage-by-feature', () => {
  it('clasifica cada fichero en su funcionalidad (prioridad por orden)', () => {
    assert.equal(classify('lib/taxes/holding-money.ts'), 'impuestos (IRPF/720)');
    assert.equal(classify('components/watchlist/DcaHitRatesCard.tsx'), 'DCA');
    assert.equal(classify('components/watchlist/WatchlistAddButton.tsx'), 'watchlist');
    assert.equal(classify('lib/portfolio-allocation.ts'), 'cartera/tearsheet');
    assert.equal(classify('lib/format.ts'), 'divisa/formato');
    assert.equal(classify('components/research/ThesisApproveButton.tsx'), 'tesis');
    assert.equal(classify('components/research/CompanyHeaderQuote.tsx'), 'ficha/research');
    assert.equal(classify('middleware.ts'), 'auth');
    assert.equal(classify('components/paper-trading/OrderTicket.tsx'), OTHER);
  });

  it('agrega líneas y ramas con el denominador real y ordena por hueco', () => {
    const file = (covered: number, total: number) => ({
      lines: { covered, total, pct: total ? (100 * covered) / total : 100 },
      branches: { covered: 0, total: 0, pct: 100 },
    });
    const byFeature = summarize({
      total: file(0, 0),
      'lib/taxes/a.ts': file(9, 10),
      'components/taxes/B.tsx': file(1, 10),
    }, '/repo');
    const taxes = byFeature.get('impuestos (IRPF/720)');
    assert.deepEqual(taxes.lines, [10, 20]);
    assert.equal(taxes.percentLines, 50);
    assert.equal(taxes.percentBranches, 100);
    assert.equal(taxes.files[0].file, 'components/taxes/B.tsx');
    const md = render(byFeature, { markdown: true, top: 1 });
    assert.match(md, /\| impuestos \(IRPF\/720\) \| 50% \| 100% \| `B\.tsx` \(10%\) \|/);
  });
});
