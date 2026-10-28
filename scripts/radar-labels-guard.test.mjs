// Guard del radar global (B2): las protecciones de honestidad que Nico
// mantiene (cotejo HKEXnews, N/D, yield extremo, error honesto) no se pueden
// quitar sin romper este test. Los rotulos "Yahoo (fuente no oficial)" por
// cifra se retiraron a peticion expresa de Nico (28-oct): el guard fija esa
// decision para que no reaparezcan por accidente.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const view = readFileSync(new URL('../components/proPicks/RadarGlobalView.tsx', import.meta.url), 'utf8');

test('el enlace de cotejo oficial HKEXnews se mantiene', () => {
    assert.match(view, /Cotejar en HKEXnews \(fuente oficial\)/);
});

test('la ausencia de cifra es N/D y el yield extremo se marca', () => {
    assert.match(view, /N\/D/);
    assert.match(view, /Yield muy alto/);
});

test('el error es honesto: no se sirven candidatos inventados', () => {
    assert.match(view, /no se han generado candidatos/);
    assert.doesNotMatch(view, /recomendaci[oó]n de compra/i);
});

test('decision de Nico (28-oct): sin rotulo "fuente no oficial" por cifra ni aviso largo', () => {
    assert.doesNotMatch(view, /fuente no oficial/);
    assert.doesNotMatch(view, /SOLO propone candidatos/);
    assert.match(view, /Candidatos de Yahoo Finance; conviene cotejo oficial/);
});
