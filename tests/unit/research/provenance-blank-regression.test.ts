import { expect, it } from 'vitest';
import { formatProvenanceValue } from '@/lib/research/provenance-format';

// REPRO (rojo): un valor en blanco debe ser N/D, no "0".
it("'   ' -> N/D", () => {
    expect(formatProvenanceValue('   ', 'USD')).toBe('N/D');
});
