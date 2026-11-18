import { readFileSync } from 'node:fs';

import { describe, expect, it } from 'vitest';

// Desbordamiento horizontal de /plan a 320px (medido en prod 18-nov-2026,
// viewport 320px: scrollWidth 343; la pista única del grid `grid gap-6` se iba
// a 327px sobre los 288 disponibles). Dos causas medidas en vivo por bisección
// (ocultando hijos del grid y luego del interior de cada tarjeta), no supuestas:
//  1. Cabecera de RecordDetail («Objetivo y asignación»): la fila de botones
//     «Refrescar» + «Editar plan» (109+8+135 ≈ 253px de min-content en nowrap)
//     forzaba la pista a 301px. Fix: flex-wrap → el min-content pasa a ser el
//     botón más ancho (~140px); en escritorio (sm:flex-row) sigue en una fila.
//  2. Estado vacío de RecordList («Aportaciones»): el CTA «Registrar
//     aportación» (whitespace-nowrap del Button base, ≈213px de min-content)
//     dentro del EmptyState p-8 forzaba la pista a 327px. Fix: el disparador
//     del diálogo permite romper el texto conservando min-h 44px.

const recordViews = readFileSync('components/data/RecordViews.tsx', 'utf8');
const contributionDialog = readFileSync('components/plan/PlanContributionDialog.tsx', 'utf8');

describe('/plan a 320px: sin desbordamiento horizontal', () => {
    it('la fila de botones de la cabecera de RecordDetail envuelve (flex-wrap)', () => {
        expect(recordViews).toContain('<div className="flex flex-wrap items-center gap-2">');
    });

    it('no queda la fila de botones de cabecera sin envolver', () => {
        expect(recordViews).not.toContain('<div className="flex items-center gap-2">\n                    {fetchRecord && (');
    });

    it('el CTA «Registrar aportación» permite romper el texto y mantiene 44px', () => {
        expect(contributionDialog).toContain('h-auto min-h-[44px] gap-2 whitespace-normal py-2 text-center');
    });
});
