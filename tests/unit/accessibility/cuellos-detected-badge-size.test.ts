import { readFileSync } from 'node:fs';

import { describe, expect, it } from 'vitest';

import { explicitSizePx } from './legible-text-guard';

// Badge «detectado» de /cuellos: pin de TAMAÑO (no puede bajar de 12px).
// Ojo: no se afirma aquí ningún ratio de contraste — el color computado del
// badge es oklch (Chrome) y un hex hardcodeado no es una medida.
// Captura manual (11 nov 2026, fixture harness local con los className
// exactos, Chrome + CSS compilado del tema, computed style oklch -> sRGB):
// la tinta teal del badge sobre su fondo efectivo quedo en torno a 11:1.
// Es una captura puntual, no una garantía de contraste; este pin es solo
// de tamaño.

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
});
