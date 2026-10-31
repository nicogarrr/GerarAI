// Guard: Inicio no repite el rendimiento en una tarjeta de prosa aparte; el
// % de ganancia/pérdida y el enlace "Ver qué ha cambiado en X" se mantienen.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const SRC = readFileSync('components/PersonalizedOverview.tsx', 'utf8');

test('no hay tarjeta "Tu cartera en una línea"', () => {
    assert.ok(!SRC.includes('Tu cartera en una línea'));
});

test('se conserva el enlace al cambio de la posición top y la fila de ganancia/pérdida', () => {
    assert.ok(SRC.includes('home.portfolio.reviewMover'));
    const dict = JSON.parse(readFileSync('lib/i18n/messages/es/home.json', 'utf8'));
    assert.equal(dict.portfolio.reviewMover, 'Revisar {symbol} (mayor variación desde la compra)');
    assert.ok(SRC.includes('home.portfolio.gainLoss'));
    assert.equal(dict.portfolio.gainLoss, 'Ganancia/Pérdida desde la compra');;
});
