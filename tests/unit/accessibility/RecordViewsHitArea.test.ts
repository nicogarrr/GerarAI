import { readFileSync } from 'node:fs';

import { describe, expect, it } from 'vitest';

// Zona táctil de los enlaces de ticker en RecordViews (medido en prod
// 18-nov-2026 a 390px en /plan: 16 px de alto, paso de 24 px). Mismo
// patrón de la casa que InsiderOperationsView y RiskDashboardView:
// pseudo-elemento before:-inset-y-2 (32 px efectivos, rellena el hueco del
// paso sin tapar al vecino) + -inset-x-1.5. Hay DOS instancias: tabla de
// escritorio y tarjetas móviles (md:hidden) — las dos llevan la expansión.

const src = readFileSync('components/data/RecordViews.tsx', 'utf8');

describe('RecordViews: enlaces de celda con zona táctil ampliada', () => {
    it('las dos instancias (tabla y tarjetas móviles) llevan before:-inset', () => {
        const hits = src.match(/relative font-mono font-semibold text-teal-300 before:absolute before:-inset-x-1\.5 before:-inset-y-2 before:content-\[''\] hover:text-teal-200 hover:underline/g) ?? [];
        expect(hits, 'instancias del enlace de celda con expansión').toHaveLength(2);
    });

    it('no queda la clase inline sin expansión', () => {
        expect(src).not.toContain('className="font-mono font-semibold text-teal-300 hover:text-teal-200 hover:underline"');
    });
});
