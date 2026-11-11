import { readFileSync } from 'node:fs';

import { describe, expect, it } from 'vitest';

import { checkLegible, explicitSizePx } from './legible-text-guard';

// Badge «detectado» de /cuellos: quedó fuera de la PR hermana (solo N/D) y
// seguía a 10px. Su color ya cumple de sobra (teal-300 sobre teal-400/15,
// medido 11.0:1 con tokens reales); el fallo era el tamaño. Pin: el badge no
// puede bajar de 12px y su tinta teal-300 mide >=4.5:1 sobre el fondo teal
// al 15% mezclado sobre surface-0.

import { blendOver, contrastRatio } from './contrast-helpers';

function classTokens(className: string): string[] {
    return className.split(/\s+/).filter(Boolean);
}

describe('cuellos: badge «detectado»', () => {
    it('va a >=12px', () => {
        const src = readFileSync('app/(root)/cuellos/page.tsx', 'utf8');
        const badge = [...src.matchAll(/<span className="([^"]*bg-teal-400\/15[^"]*)"[^>]*>\s*\{t\('bottlenecks\.page\.detected'\)/g)]
            .map((m) => classTokens(m[1]));
        expect(badge.length, 'no se encuentra el badge «detectado»').toBe(1);
        expect(explicitSizePx(badge[0]), 'el badge «detectado» no puede bajar de 12px').toBeGreaterThanOrEqual(12);
    });

    it('su contraste mide >=4.5:1 con tokens reales (documentado)', () => {
        // teal-300 (no redefinido, #5eead4) sobre teal-400 (--color-teal-400
        // del tema, #14b8a6) al 15% sobre surface-0 (#0a0a0b).
        const bg = blendOver('#14b8a6', '#0a0a0b', 0.15);
        expect(contrastRatio('#5eead4', bg)).toBeGreaterThanOrEqual(4.5);
        // Y el guard real confirma que la tinta base de la tarjeta sigue AA:
        expect(checkLegible(['text-xs', 'text-gray-500'], 'surface-0').ok).toBe(true);
    });
});
