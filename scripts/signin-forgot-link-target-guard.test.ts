/**
 * Guarda del enlace de recuperación de contraseña (#6022, D16): es un
 * enlace standalone (su propia línea, no una frase) y WCAG 2.5.8 exige un
 * objetivo de al menos 24×24 px. La receta anterior era un inline suelto de
 * ~20 px de alto. Los enlaces inline dentro de una frase están exentos y no
 * entran en esta guarda.
 * Ejecución: node --experimental-strip-types --test scripts/signin-forgot-link-target-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const source = (relativePath: string): string => readFileSync(join(here, '..', relativePath), 'utf8');

describe('enlace de recuperación de /sign-in: objetivo táctil >=24px', () => {
    const form = source(join('components', 'forms', 'SignInForm.tsx'));
    const linkBlock = form.match(/<Link\s+className="([^"]+)"\s+href="\/forgot-password"/);

    it('el enlace a /forgot-password lleva min-h-6 (24px) con caja flex', () => {
        assert.ok(linkBlock, 'debe existir el enlace de recuperación con su className');
        const classes = linkBlock[1];
        assert.match(classes, /(?:^|\s)min-h-6(?:\s|$)/, 'min-h-6 = 24px de alto de objetivo (WCAG 2.5.8)');
        assert.match(classes, /(?:^|\s)inline-flex(?:\s|$)/, 'inline-flex da caja real al min-h (un inline lo ignora)');
    });

    it('la receta vieja sin altura de objetivo no vuelve', () => {
        assert.ok(
            !form.includes('className="text-sm text-gray-400 underline-offset-4 transition-colors hover:text-teal-300 hover:underline"'),
            'el enlace standalone sin min-h-6 quedaba por debajo de 24px de objetivo',
        );
    });
});
