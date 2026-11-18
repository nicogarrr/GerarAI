/**
 * Auditoría 18-nov-2026: texto de lectura a 10 px en /portfolio, por debajo
 * del suelo de la casa (text-xs / 12 px, auditoría de contraste del 11-nov y
 * guard en tests/unit/accessibility/legible-text-guard.ts).
 *
 * - HoldingSignals: etiqueta del valor justo bajo el importe.
 * - PortfolioDividends: notas ámbar de bruto no verificado / solo bruto (x2).
 * - PortfolioScores: etiqueta «sin datos» bajo la puntuación.
 * - PortfolioTransactions: etiqueta «bruto» junto al importe.
 *
 * Ninguno es marcador tipográfico (sup «*»): todos transmiten información.
 */
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

const ROOT = join(__dirname, '..', '..', '..');

function src(path: string): string {
    return readFileSync(join(ROOT, path), 'utf8');
}

describe('texto legible en /portfolio: nada de lectura por debajo de 12 px', () => {
    it('HoldingSignals: etiqueta del valor justo a text-xs', () => {
        const s = src('components/portfolio/HoldingSignals.tsx');
        expect(s).not.toContain('text-[10px]');
        expect(s).toContain('block text-xs text-gray-500');
    });

    it('PortfolioDividends: notas de bruto a text-xs', () => {
        const s = src('components/portfolio/PortfolioDividends.tsx');
        expect(s).not.toContain('text-[10px]');
        expect(s.match(/block text-xs text-amber-400\/90/g)?.length).toBeGreaterThanOrEqual(2);
    });

    it('PortfolioScores: etiqueta sin datos a text-xs', () => {
        const s = src('components/portfolio/PortfolioScores.tsx');
        expect(s).not.toContain('text-[10px]');
        expect(s).toContain('text-xs uppercase tracking-wide text-gray-500');
    });

    it('PortfolioTransactions: etiqueta bruto a text-xs', () => {
        const s = src('components/portfolio/PortfolioTransactions.tsx');
        expect(s).not.toContain('text-[10px]');
        expect(s).toContain('ml-1.5 text-xs uppercase tracking-wide text-gray-500');
    });
});
