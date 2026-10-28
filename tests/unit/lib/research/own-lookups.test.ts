import { describe, expect, it } from 'vitest';
import { analystRatingEs } from '@/lib/research/analyst-rating-es';
import { frameworkTerm, frameworkLabel } from '@/lib/research/framework-terms';
import { thesisCodeLabel } from '@/lib/research/thesis-code-label';
import { sourceDisplay } from '@/lib/research/source-display';
import { reviewStatusLabel, expectationMetricLabel } from '@/lib/research/expectation-labels';
import { metricLabel } from '@/lib/research/metric-labels';
import { nodeColor } from '@/lib/knowledge-graph/graph-model';

describe('catálogos solo aceptan propiedades propias', () => {
  it.each(['constructor', 'toString', '__proto__', 'hasOwnProperty', 'valueOf'])('%s conserva fallback sin filtrar prototipo', (key) => {
    expect(analystRatingEs(key)).toBe(key);
    expect(frameworkTerm(key)).toBeNull();
    expect(frameworkLabel(key)).toBe(key);
    expect(thesisCodeLabel(key)).toBe(key);
    expect(sourceDisplay(key)).toBe(key.replaceAll('_', ' '));
    expect(reviewStatusLabel(key)).toBe(key);
    expect(expectationMetricLabel(key)).toBe(key.replaceAll('_', ' '));
    expect(metricLabel(key)).toBe(key.replaceAll('_', ' '));
    expect(nodeColor(key)).toBe(nodeColor('unknown_type'));
  });
  it('conserva las traducciones conocidas', () => {
    expect(analystRatingEs('buy')).toBe('Compra');
    expect(thesisCodeLabel('draft')).toBe('borrador');
    expect(sourceDisplay('sec')).toBe('SEC EDGAR');
    expect(reviewStatusLabel('met')).toBe('cumplido');
  });
});
