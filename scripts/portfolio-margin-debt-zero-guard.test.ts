// Guard: la deuda de margen solo va en ámbar si es mayor que cero.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const SRC = readFileSync('components/portfolio/PortfolioValueBreakdown.tsx', 'utf8');

test('deuda de margen cero no se pinta como aviso', () => {
    assert.ok(SRC.includes("marginDebt > 0 ? 'text-amber-300' : 'text-gray-100'"));
});
