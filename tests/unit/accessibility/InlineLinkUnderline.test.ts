import { readFileSync } from 'node:fs';

import { describe, expect, it } from 'vitest';

// Enlaces dentro de bloques de texto: distinguibles sin depender del color
// (WCAG 2.2 SC 1.4.1, uso del color). Regresión vista con axe-core 4.10.2 en
// producción a 390 px (regla link-in-text-block, seria): el enlace «ver la
// lista completa» de /inicio, dentro de un <p> text-gray-500, solo se
// distinguía por el amarillo y subrayaba solo al hover.
describe('enlaces inline en texto', () => {
    it('el enlace a /watchlist dentro del contador de Inicio va subrayado siempre', () => {
        const src = readFileSync('components/PersonalizedOverview.tsx', 'utf8');
        const inlineLink = src.match(/<Link href="\/watchlist" className="([^"]*)">\s*\{t\('home\.watchlist\.seeFullList'\)\}/);
        expect(inlineLink, 'no se encuentra el enlace inline a /watchlist').not.toBeNull();
        expect(inlineLink![1]).toContain('underline');
        expect(inlineLink![1]).not.toMatch(/hover:underline(?!.*\bunderline\b)/);
    });
});
