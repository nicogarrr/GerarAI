/**
 * Guard: la reserva de alto del aviso de conexión depende de `data-online-banner`.
 *
 * El comportamiento del banner (live region SIEMPRE montada, sr-only con
 * conexión, aviso y `data-online-banner` solo sin conexión, misma región al
 * cambiar de estado) lo comprueba ahora un test de comportamiento que lo
 * renderiza: tests/unit/components/OnlineBanner.test.tsx (Vitest + Testing
 * Library). Aquí queda solo el contrato con el CSS, que un render en jsdom no
 * puede ver: globals.css reserva el alto del banner con
 * `body:has([data-online-banner])`; si el atributo fuera permanente el shell
 * quedaría desplazado 2rem siempre.
 *
 * Ejecución: node --experimental-strip-types --test scripts/online-banner-live-region-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const css = readFileSync('app/globals.css', 'utf8');

describe('OnlineBanner: contrato con globals.css', () => {
    it('la reserva de alto del shell se basa en data-online-banner', () => {
        assert.match(css, /body:has\(\[data-online-banner\]\)/);
    });
});
