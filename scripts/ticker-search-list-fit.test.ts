/**
 * Geometría de la lista del buscador con dirección forzada (review auditor,
 * 21-oct-2026): comportamiento, no solo wiring. La altura NUNCA supera el
 * espacio real bajo el input (suelo 0, sin mínimos mágicos) y el
 * reposicionamiento se pide una única vez por apertura.
 *
 * Ejecución: node --experimental-strip-types --test scripts/ticker-search-list-fit.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
// @ts-expect-error TS5097: la extensión explícita la exige node --experimental-strip-types.
import { computeListFit, computeSpaceBelow, LIST_COMFORTABLE_SPACE, LIST_GAP, LIST_MAX_HEIGHT_CAP } from '../components/search/list-fit.ts';

describe('computeSpaceBelow (espacio real bajo el input)', () => {
    it('descuenta el offset del visual viewport (teclado/barras de Safari)', () => {
        // viewport [100..500], input acaba en 300 → 500-300-8 = 192
        assert.equal(computeSpaceBelow(300, 400, 100), 192);
        // sin offset: viewport [0..400], input en 300 → 92
        assert.equal(computeSpaceBelow(300, 400, 0), 92);
    });
    it('puede salir cero o negativo si el input está bajo el pliegue', () => {
        assert.equal(computeSpaceBelow(492, 400, 100), 0);
        assert.equal(computeSpaceBelow(600, 400, 100), -108);
    });
});

describe('computeListFit (espacios 0 / 20 / 63 / 95 / 240 / grandes)', () => {
    it('la altura nunca supera el espacio real: suelo 0, sin mínimo mágico', () => {
        assert.deepEqual(computeListFit(0, true), { maxHeight: 0, shouldScroll: false });
        assert.deepEqual(computeListFit(20, true), { maxHeight: 20, shouldScroll: false });
        assert.deepEqual(computeListFit(63, true), { maxHeight: 63, shouldScroll: false });
        assert.deepEqual(computeListFit(-50, true), { maxHeight: 0, shouldScroll: false });
    });
    it('pide el reposicionamiento solo cuando el hueco es incómodo y aún no se hizo', () => {
        for (const space of [0, 20, 63, 95]) {
            const fit = computeListFit(space, false);
            assert.equal(fit.shouldScroll, true, `space=${space}`);
            assert.equal(fit.maxHeight, Math.max(0, space), `space=${space}`);
        }
        // Tras el scroll único, no vuelve a pedirlo (sin saltos repetidos).
        assert.equal(computeListFit(20, true).shouldScroll, false);
        assert.equal(computeListFit(95, true).shouldScroll, false);
    });
    it('con hueco cómodo no pide scroll y respeta el techo de 240px', () => {
        assert.deepEqual(computeListFit(LIST_COMFORTABLE_SPACE, false), { maxHeight: 96, shouldScroll: false });
        assert.deepEqual(computeListFit(150, false), { maxHeight: 150, shouldScroll: false });
        assert.deepEqual(computeListFit(240, false), { maxHeight: 240, shouldScroll: false });
        assert.deepEqual(computeListFit(500, false), { maxHeight: LIST_MAX_HEIGHT_CAP, shouldScroll: false });
    });
    it('constantes coherentes: gap positivo, confort por debajo del techo', () => {
        assert.ok(LIST_GAP > 0);
        assert.ok(LIST_COMFORTABLE_SPACE < LIST_MAX_HEIGHT_CAP);
    });
});

describe('wiring del componente con la geometría pura', () => {
    it('el componente consume las funciones puras y no reimplementa clamps', async () => {
        const { readFileSync } = await import('node:fs');
        const search = readFileSync('components/search/TickerSearchInput.tsx', 'utf8');
        assert.match(search, /import \{ computeListFit, computeSpaceBelow \} from '\.\/list-fit'/);
        assert.match(search, /computeSpaceBelow\(rect\.bottom/);
        assert.match(search, /computeListFit\(spaceBelow, scrolledForSpace\.current\)/);
        // Sin mínimos mágicos reintroducidos en el componente.
        assert.doesNotMatch(search, /Math\.max\((64|96), /);
    });
});
