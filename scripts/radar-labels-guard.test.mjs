// Guard de rotulos del radar global (B2): los textos de veracidad no se
// pueden quitar ni suavizar sin romcer este test.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const view = readFileSync(new URL('../components/proPicks/RadarGlobalView.tsx', import.meta.url), 'utf8');

test('el aviso fijo nombra fuente no oficial, no-veracidad y cotejo HKEXnews', () => {
    assert.match(view, /fuente no oficial/);
    assert.match(view, /no\s+son dato verificado/);
    assert.match(view, /HKEXnews/);
});

test('cada cifra de yield va rotulada y la ausencia es N/D', () => {
    assert.match(view, /Yahoo \(fuente no oficial\)/);
    assert.match(view, /N\/D/);
});

test('el yield extremo y el enlace de cotejo oficial se muestran', () => {
    assert.match(view, /Yield muy alto/);
    assert.match(view, /Cotejar en HKEXnews \(fuente oficial\)/);
});

test('el error es honesto: no se sirven candidatos inventados', () => {
    assert.match(view, /no se han generado candidatos/);
    assert.doesNotMatch(view, /recomendaci[oó]n de compra/i);
});
