import { describe, expect, it } from 'vitest';

import { readingSections } from '@/lib/research/thesis-reading-sections';

const OLD_MEMO = `# Tesis ACME

## 1. Resumen ejecutivo

Texto del resumen.

## Catalizadores

- Resultados del 3T (12 nov)
- **Investor day** en enero

## Riesgos

La deuda vence en 2027
y el refinanciado es caro.

| Métrica | Valor |
|---|---|
| ND/EBITDA | 3,1 |
`;

describe('readingSections (A10: tesis antigua solo con markdown)', () => {
    it('con narrative_sections las usa tal cual', () => {
        const sections = [{ titulo: 'Negocio', parrafos: ['Uno.'] }];
        expect(readingSections({ narrative_sections: sections, thesis_markdown: OLD_MEMO })).toBe(sections);
    });

    it('sin secciones, deriva catalizadores y riesgos del memo markdown', () => {
        const sections = readingSections({ narrative_sections: [], thesis_markdown: OLD_MEMO, executive_summary: 'Resumen.' });
        expect(sections.map((s) => s.titulo)).toEqual(['Catalizadores', 'Riesgos']);
        expect(sections[0].parrafos).toEqual(['Resultados del 3T (12 nov)', 'Investor day en enero']);
        // Prosa en varias líneas = un párrafo; la tabla no se convierte en prosa ilegible.
        expect(sections[1].parrafos).toEqual(['La deuda vence en 2027 y el refinanciado es caro.']);
    });

    it('sin resumen aparte, la sección de resumen del memo se conserva', () => {
        const sections = readingSections({ narrative_sections: null, thesis_markdown: OLD_MEMO });
        expect(sections[0]).toEqual({ titulo: 'Resumen ejecutivo', parrafos: ['Texto del resumen.'] });
    });

    it('sin secciones ni markdown no inventa nada', () => {
        expect(readingSections({ narrative_sections: [], thesis_markdown: '  ' })).toEqual([]);
        expect(readingSections({})).toEqual([]);
    });
});
