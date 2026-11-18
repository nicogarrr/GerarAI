import { readFileSync } from 'node:fs';

import { describe, expect, it } from 'vitest';

// Zona táctil del botón «Actualizar estado» del aviso de disponibilidad de
// IA (medido en prod 18-nov-2026 a 390px: 104x20 px, bajo el suelo de 44px
// de la casa). Es un botón inline bajo un párrafo, patrón de la casa:
// pseudo-elemento before:-inset-3 que amplía el área a ~44px sin cambiar el
// ritmo visual (mismo patrón que NewsSection/InlineLinkHitArea).

const src = readFileSync('components/ai/AiAvailabilityNotice.tsx', 'utf8');

describe('botón «Actualizar estado»: zona táctil ampliada', () => {
    it('lleva pseudo-elemento before:-inset-3 (44px) conservando su estilo inline', () => {
        expect(src).toContain("relative mt-1 underline underline-offset-2 before:absolute before:-inset-3 before:content-[''] disabled:opacity-50");
    });

    it('sigue siendo un botón type=button deshabilitable mientras comprueba', () => {
        expect(src).toContain('<button type="button" disabled={checking}');
    });
});
