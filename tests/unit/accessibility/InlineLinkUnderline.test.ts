import { readFileSync } from 'node:fs';

import { describe, expect, it } from 'vitest';

// Enlaces dentro de bloques de texto: distinguibles sin depender del color
// (WCAG 2.2 SC 1.4.1, uso del color). Regresión vista con axe-core 4.10.2 en
// producción a 390 px (regla link-in-text-block, seria): el enlace «ver la
// lista completa» de /inicio, dentro de un <p> text-gray-500, solo se
// distinguía por el amarillo y subrayaba solo al hover.
//
// La comprobación tokeniza className por espacios y exige el token EXACTO
// `underline`: una búsqueda por substring o por regex con \b aceptaría el
// prefijo de `underline-offset-2` o `hover:underline` y el test seguiría
// verde con la regresión puesta (medido en revisión).

/** Tokens de className separados por espacios. */
function classTokens(className: string): string[] {
    return className.split(/\s+/).filter(Boolean);
}

describe('enlaces inline en texto', () => {
    it('el enlace a /watchlist dentro del contador de Inicio va subrayado siempre', () => {
        const src = readFileSync('components/PersonalizedOverview.tsx', 'utf8');
        const inlineLink = src.match(/<Link href="\/watchlist" className="([^"]*)">\s*\{t\('home\.watchlist\.seeFullList'\)\}/);
        expect(inlineLink, 'no se encuentra el enlace inline a /watchlist').not.toBeNull();
        const tokens = classTokens(inlineLink![1]);
        expect(tokens, 'el enlace necesita el token exacto `underline`, no solo hover:underline').toContain('underline');
        expect(tokens).not.toContain('hover:underline');
    });

    it('control negativo: la comprobación rechaza la clase regresada', () => {
        // La clase con la regresión original: subraya solo al hover.
        const regressed = classTokens('text-yellow-400 hover:underline underline-offset-2');
        expect(regressed).not.toContain('underline');
        // Y el substring engañoso que una regex con \b aceptaría por error:
        expect(regressed.join(' ')).toContain('underline');
    });
});
