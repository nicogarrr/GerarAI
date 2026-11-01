import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { ownerEarningsFormulaLabel } from '@/components/research/FundamentalModelPanels';

// La fórmula llega tal cual del backend (long_term_model_service →
// OWNER_EARNINGS_FORMULA). Se lee del fuente Python para que un cambio de
// redacción allí no vuelva a dejar el panel en inglés sin que falle esto.
function backendOwnerEarningsFormula(): string {
    const source = readFileSync(path.join(process.cwd(), 'data-engine/app/services/owner_earnings.py'), 'utf8');
    const block = /OWNER_EARNINGS_FORMULA = \(([\s\S]*?)\n\)/.exec(source)?.[1] ?? '';
    return [...block.matchAll(/"([^"]*)"/g)].map((m) => m[1]).join('');
}

describe('Modelo a largo plazo · beneficio del propietario', () => {
    it('muestra la fórmula del backend en español, sin restos en inglés', () => {
        const formula = backendOwnerEarningsFormula();
        expect(formula).toContain('Berkshire Hathaway 1986 letter');
        const text = ownerEarningsFormulaLabel(formula);
        expect(text).toContain('negativo = el capital circulante absorbió efectivo');
        expect(text).toContain('carta de Berkshire Hathaway de 1986');
        expect(text).toContain('mínimo(valor absoluto(');
        expect(text).not.toMatch(/\b(?:negative|working capital|absorbed|reported|estimated|when not|separately|letter|cash-flow)\b/);
    });

    it('en inglés muestra la fórmula del backend tal cual', () => {
        const formula = backendOwnerEarningsFormula();
        expect(ownerEarningsFormulaLabel(formula, 'en')).toBe(formula);
    });
});
