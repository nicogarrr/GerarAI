/**
 * Guard: la identidad de marca (rediseño 1-nov-2026) no se degrada.
 *
 * El monograma propio (la G con la barra de gráfica) vive en el wordmark,
 * el app-icon SVG y el favicon SVG; los PNG del manifest y el apple-touch
 * se generan DESDE ese SVG a tamaños exactos; el favicon.ico lleva 16/32/48;
 * y la portada OG existe a 1200x630 con su metadata.
 *
 * Ejecución: node --experimental-strip-types --test scripts/brand-assets-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';

const MONOGRAM_ARC = 'M17.39 18.89';
const MONOGRAM_BAR = 'M12.4 12H18.8V14.3';

function pngSize(path: string): [number, number] {
    const b = readFileSync(path);
    assert.equal(b[0], 0x89, `${path}: no es PNG`);
    return [b.readUInt32BE(16), b.readUInt32BE(20)];
}

describe('identidad de marca', () => {
    it('el monograma vive en el wordmark, el app-icon y el favicon SVG', () => {
        for (const file of ['components/GerarAIWordmark.tsx', 'public/assets/icons/app-icon.svg', 'app/icon.svg', 'public/assets/icons/logo.svg']) {
            const text = readFileSync(file, 'utf8');
            assert.ok(text.includes(MONOGRAM_ARC), `${file}: falta el arco del monograma`);
            assert.ok(text.includes(MONOGRAM_BAR), `${file}: falta la barra del monograma`);
        }
        // El wordmark ya no importa el icono de stock.
        assert.ok(!/from ['"]lucide-react['"]/.test(readFileSync('components/GerarAIWordmark.tsx', 'utf8')), 'el wordmark no debe depender de lucide-react');
    });

    it('los PNG del manifest y el apple-touch-icon están a su tamaño exacto', () => {
        for (const [file, side] of [
            ['public/assets/icons/icon-192.png', 192],
            ['public/assets/icons/icon-512.png', 512],
            ['public/assets/icons/icon-maskable-192.png', 192],
            ['public/assets/icons/icon-maskable-512.png', 512],
            ['public/assets/icons/apple-touch-icon.png', 180],
        ] as const) {
            assert.deepEqual(pngSize(file), [side, side], `${file} debe ser ${side}x${side}`);
        }
    });

    it('el favicon.ico lleva las entradas 16, 32 y 48', () => {
        const b = readFileSync('app/favicon.ico');
        assert.equal(b.readUInt16LE(0), 0, 'ICO: reserved');
        assert.equal(b.readUInt16LE(2), 1, 'ICO: type');
        const count = b.readUInt16LE(4);
        const sides = new Set<number>();
        for (let i = 0; i < count; i++) sides.add(b[6 + i * 16]);
        for (const want of [16, 32, 48]) assert.ok(sides.has(want), `favicon.ico: falta la entrada ${want}`);
    });

    it('la portada OG existe a 1200x630 y el layout la declara', () => {
        assert.ok(existsSync('public/assets/og/cover.png'), 'falta public/assets/og/cover.png');
        assert.deepEqual(pngSize('public/assets/og/cover.png'), [1200, 630]);
        const layout = readFileSync('app/layout.tsx', 'utf8');
        assert.ok(layout.includes('/assets/og/cover.png'), 'app/layout.tsx debe referenciar la portada OG');
        assert.ok(layout.includes('metadataBase'), 'app/layout.tsx necesita metadataBase para la URL absoluta de OG');
    });
});
