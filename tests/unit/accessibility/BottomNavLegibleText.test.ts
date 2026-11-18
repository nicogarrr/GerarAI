/**
 * Auditoría 18-nov-2026: etiquetas de BottomNav a 12 px con carve-out
 * responsive. A 320 px «Descubrir»/«Watchlist» colisionan a 12 px (medido
 * con captura real; celdas de ~53 px), así que la etiqueta se queda en
 * text-[11px] por debajo de 360 px y sube a text-xs desde 360 px
 * (min-[360px]:text-xs). El área táctil min-h-14 (56 px) no cambia.
 */
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

const ROOT = join(__dirname, '..', '..', '..');

function src(path: string): string {
    return readFileSync(join(ROOT, path), 'utf8');
}

describe('BottomNav: etiqueta legible desde 360 px sin colisión en 320 px', () => {
    it('las dos variantes de etiqueta llevan text-[11px] min-[360px]:text-xs', () => {
        const s = src('components/layout/BottomNav.tsx');
        expect(s.match(/text-\[11px\] font-medium min-\[360px\]:text-xs/g)?.length ?? 0).toBe(2);
    });

    it('el área táctil min-h-14 (56 px) sigue intacta', () => {
        const s = src('components/layout/BottomNav.tsx');
        expect(s.match(/min-h-14/g)?.length ?? 0).toBeGreaterThanOrEqual(2);
    });
});
