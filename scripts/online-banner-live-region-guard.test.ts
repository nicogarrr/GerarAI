/**
 * Guard: la live region del aviso de conexión está SIEMPRE montada.
 *
 * El banner hacía `if (online) return null`: la región `role="status"
 * aria-live="polite"` se montaba al perder la conexión y parte de los
 * lectores de pantalla no anuncian una región que no existía. Ahora va
 * montada siempre (sr-only con conexión, para no salir del árbol de
 * accesibilidad) y solo cambian texto y visibilidad.
 *
 * `data-online-banner` NO puede ser permanente: globals.css reserva el alto
 * del banner con `body:has([data-online-banner])` y el shell quedaría
 * desplazado 2rem siempre.
 *
 * Ejecución: node --experimental-strip-types --test scripts/online-banner-live-region-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const banner = readFileSync('components/OnlineBanner.tsx', 'utf8');
const css = readFileSync('app/globals.css', 'utf8');

describe('OnlineBanner: live region permanente', () => {
    it('nunca desmonta la región (vetado el return null)', () => {
        assert.ok(!/if \(online\) return null/.test(banner), 'la región no se desmonta con conexión');
        assert.match(banner, /role="status"/);
        assert.match(banner, /aria-live="polite"/);
        assert.match(banner, /className=\{online \? 'sr-only' : 'w-full bg-amber-100/);
    });
    it('data-online-banner solo se emite sin conexión (reserva de alto en globals.css)', () => {
        assert.match(banner, /\{\.\.\.\(online \? \{\} : \{ 'data-online-banner': true \}\)\}/);
        // El CSS sigue basándose en el atributo: el guard cubre el contrato completo.
        assert.match(css, /body:has\(\[data-online-banner\]\)/);
    });
});
