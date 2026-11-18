/**
 * Auditoría 18-nov-2026 (P23): la etiqueta «Ganancia/Pérdida» de
 * PortfolioSummary era la única de las cuatro tarjetas resumen por debajo
 * del suelo de lectura de la casa (text-xs / 12 px) e inconsistente con sus
 * hermanas. v1 la subió a text-xs pero siguió recortada: en 2 columnas a
 * 320px la caja de contenido son ~104px y el token irrompible
 * «GANANCIA/PÉRDIDA» mide 145px (medido en Chrome por el Auditor, captura
 * 18-nov); overflow-hidden lo ocultaba. v2: 1 columna hasta 420px (el
 * breakpoint que ya usan los valores) y las cuatro etiquetas idénticas.
 */
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

const ROOT = join(__dirname, '..', '..', '..');
const SIBLING_LABEL = 'text-gray-400 text-xs uppercase tracking-wider font-semibold mb-1';

function labelClasses(source: string): string[] {
    return [...source.matchAll(/<p className="([^"]+)">\{ti\('portfolio\.summary\.(?:totalValue|costTitle|gainTitle|returnTitle)'\)\}<\/p>/g)]
        .map(match => match[1]);
}

describe('PortfolioSummary: las cuatro etiquetas resumen comparten tipografía legible', () => {
    const source = readFileSync(join(ROOT, 'components/portfolio/PortfolioSummary.tsx'), 'utf8');

    it('las cuatro etiquetas existen y son idénticas', () => {
        const labels = labelClasses(source);
        expect(labels.length, 'totalValue, costTitle, gainTitle y returnTitle').toBe(4);
        for (const classes of labels) {
            expect(classes).toBe(SIBLING_LABEL);
        }
    });

    it('nada por debajo de text-xs en las etiquetas resumen', () => {
        for (const classes of labelClasses(source)) {
            expect(classes).not.toContain('text-[11px]');
            expect(classes).not.toContain('text-[10px]');
        }
        expect(source).not.toContain('text-[11px] sm:text-xs');
    });

    it('1 columna hasta 420px: la etiqueta irrompible no cabe en 2 columnas a 320px', () => {
        expect(source).toContain('grid grid-cols-1 min-[420px]:grid-cols-2 gap-3');
        expect(source).not.toContain('grid grid-cols-2 gap-3');
    });
});
