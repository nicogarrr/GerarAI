/**
 * CLS de la línea de materiales SEC en /calendar/resultados: cada fila de
 * evento pasado montaba <Suspense fallback={null}> y la promesa compartida
 * inserta todas las líneas a la vez al resolver (CLS medido 0,32 en el rig
 * qa-resultados-cls, 390×844). Regresión: el fallback debe reservar la
 * altura real de la línea (~30px: mt-1.5 + chip h-6) para que el swap no
 * desplace las filas visibles.
 */
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

describe('el slot de materiales reserva altura mientras resuelve', () => {
    const page = readFileSync('app/(root)/calendar/resultados/page.tsx', 'utf8');
    const list = readFileSync('components/calendar/FollowedEarningsList.tsx', 'utf8');

    it('la página no usa fallback={null} en el slot de materiales', () => {
        expect(page).not.toContain('fallback={null}');
        expect(page).toContain('fallback={<MaterialsLineSkeleton />}');
    });

    it('la línea resuelta es de una sola línea (altura fija), nunca envuelve', () => {
        // flex-wrap dejaba la línea en 2 alturas a 390px y el swap seguía
        // desplazando (0,148); flex-nowrap + scroll-x fija la altura real.
        expect(list).toMatch(/MaterialsLine[\s\S]*?flex-nowrap/);
        expect(list).toMatch(/MaterialsLine[\s\S]*?overflow-x-auto/);
    });

    it('los chips no encogen: su texto nunca envuelve dentro del chip', () => {
        // Sin shrink-0 el flex los comprimía y el texto pasaba a 2 líneas,
        // dejando la fila más alta que la reserva del skeleton.
        expect(list).toMatch(/MaterialsLine[\s\S]*?shrink-0/);
    });

    it('MaterialsLineSkeleton existe y reserva la altura real de la línea', () => {
        expect(list).toContain('export function MaterialsLineSkeleton');
        // mt-1.5 + h-6: mismas métricas que la línea resuelta de MaterialsLine.
        expect(list).toMatch(/MaterialsLineSkeleton[\s\S]*?mt-1\.5/);
        expect(list).toMatch(/MaterialsLineSkeleton[\s\S]*?h-6/);
    });
});
