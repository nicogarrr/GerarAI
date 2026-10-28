// Guard: la tarjeta «Última tesis» nunca dice «Sin tesis todavía» mientras
// anuncia una tesis recién generada. El copy de vacío vive en el componente
// cliente (que conoce el estado del job), no en JSX de servidor estático.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const PAGE = readFileSync('app/(root)/research/[ticker]/page.tsx', 'utf8');
const BTN = readFileSync('components/research/ThesisGenerateButton.tsx', 'utf8');

test('el copy de vacío solo entra por la prop emptyCopy del componente cliente', () => {
    const occurrences = PAGE.split('Sin tesis todavía.').length - 1;
    assert.equal(occurrences, 1, 'una sola mención en la página');
    assert.ok(PAGE.includes('emptyCopy="Sin tesis todavía."'), 'entra como prop, no como JSX hermano');
    assert.ok(BTN.includes('emptyCopy && !succeededHere'), 'el componente oculta el copy al completar');
});

test('el éxito no esconde el botón de regenerar ni falsea publicación', () => {
    assert.ok(BTN.includes("insufficient_data: 'datos insuficientes'"), 'datos insuficientes se etiquetan como tales');
    // El botón solo se oculta en el caso «primera tesis» (emptyCopy presente).
    assert.ok(BTN.includes('succeededHere && emptyCopy'), 'ocultar botón solo con emptyCopy');
});

test('completar el job NO dispara router.refresh global (scroll del lector)', () => {
    const tick = BTN.slice(BTN.indexOf('const tick = async'), BTN.indexOf('setExhaustedJobId(jobId);'));
    assert.ok(!/router\.refresh\(\s*\)\s*;/.test(tick), 'el polling no refresca la ruta entera');
});
