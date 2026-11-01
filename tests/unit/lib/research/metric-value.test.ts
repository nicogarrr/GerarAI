import { describe, expect, it } from 'vitest';
import { formatResearchMetric } from '@/lib/research/metric-value';

describe('formatResearchMetric', () => {
    it('sin dato o no finito: N/D, nunca 0 ni NaN', () => {
        for (const v of [null, undefined, '', 'abc', NaN, Infinity]) expect(formatResearchMetric(v as never, 'USD')).toBe('N/D');
    });
    it('respeta la divisa de la unidad, no la del listado', () => {
        expect(formatResearchMetric(12.5, 'EUR')).toBe('12,50\u00a0€');
        expect(formatResearchMetric('12.5', 'GBP')).toBe('12,50\u00a0GBP');
    });
    it('por acción conserva la divisa declarada', () => {
        expect(formatResearchMetric(3.1, 'USD/share')).toBe('3,10\u00a0US$/acción');
        expect(formatResearchMetric(3.1, 'EUR/shares')).toBe('3,10\u00a0€/acción');
    });
    it('importes de 1e6 o más no se tratan como precio con céntimos', () => {
        const out = formatResearchMetric(2_500_000_000, 'USD');
        expect(out).not.toBe('$2,500,000,000.00');
        expect(out).toContain('2');
    });
    it('unidad desconocida no infiere escala ni divisa', () => {
        const unknown = formatResearchMetric(0.25, 'foo_bar');
        const bare = formatResearchMetric(0.25, '');
        expect(unknown).toBe(bare);
        expect(unknown).not.toMatch(/%|\$|€/);
    });
    it('porcentajes y ratios conocidos se muestran con unidad', () => {
        expect(formatResearchMetric(0.144, 'decimal')).toContain('14');
    });
    it('en inglés: «$3.10/share», separadores en inglés y N/A', () => {
        expect(formatResearchMetric(3.1, 'USD/share', 'en')).toBe('$3.10/share');
        expect(formatResearchMetric(3.1, 'EUR/shares', 'en')).toBe('€3.10/share');
        expect(formatResearchMetric(1234.5, 'USD', 'en')).toBe('$1,234.50');
        expect(formatResearchMetric(148_401_000_000, 'USD', 'en')).toBe('$148.40B');
        expect(formatResearchMetric(0.144, 'decimal', 'en')).toBe('14.4%');
        expect(formatResearchMetric(19_240_000_000, 'shares', 'en')).toMatch(/shares$/);
        expect(formatResearchMetric(null, 'USD', 'en')).toBe('N/A');
        expect(formatResearchMetric('abc', 'USD', 'en')).toBe('N/A');
    });
    it('el español no cambia al pasar «es» explícito', () => {
        expect(formatResearchMetric(3.1, 'USD/share', 'es')).toBe(formatResearchMetric(3.1, 'USD/share'));
    });
});
