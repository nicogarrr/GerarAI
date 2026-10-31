// Guard del radar global (B2): las protecciones de honestidad que Nico
// mantiene (cotejo HKEXnews, N/D, yield extremo, error honesto) no se pueden
// quitar sin romper este test. Los rotulos "Yahoo (fuente no oficial)" por
// cifra se retiraron a peticion expresa de Nico (28-oct). Orden vigente de
// Nico (31-oct): quitar el nombre del proveedor de TODAS las etiquetas
// visibles; la procedencia se mantiene en la pestana Fuentes, la ayuda y el
// registro interno. El guard fija ambas decisiones.
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

test('decision de Nico (28-oct y 31-oct): sin rotulo largo ni nombre de proveedor visible', () => {
    assert.doesNotMatch(view, /fuente no oficial/, 'sin rotulo "fuente no oficial" por cifra (28-oct)');
    assert.doesNotMatch(view, /SOLO propone candidatos/);
    assert.doesNotMatch(view, /Yahoo/i, 'el nombre del proveedor no aparece en etiquetas visibles (orden 31-oct; la procedencia vive en Fuentes/ayuda)');
    assert.match(view, /Candidatos de fuente de mercado no oficial; conviene cotejo oficial/);
});
