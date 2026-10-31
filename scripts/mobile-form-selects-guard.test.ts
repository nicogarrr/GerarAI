import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

/**
 * Guard: selects nativos de los formularios de la ficha a 390 px (31-oct-2026).
 * h-9 son 36 px, bajo el mínimo táctil de 44 px del repo, y text-sm (14 px)
 * provoca zoom de foco en iOS. Convención: h-11 + text-base en móvil,
 * compacto (h-9, text-sm) desde sm. Los inputs siguen la decisión registrada
 * de tamaño acotado por uso (min-h-11 local, no base compartida).
 */

const NUEVO = 'select className="h-11 rounded-md border border-gray-800 bg-black px-3 text-base text-gray-200 sm:h-9 sm:text-sm"';
const VIEJO = 'select className="h-9 rounded-md border border-gray-800 bg-black px-3 text-sm text-gray-200"';

const FILES = [
    'components/research/sections/DriverAssumptionsSection.tsx',
    'components/research/sections/ManagementCredibilitySection.tsx',
    'components/research/sections/FinancialTerminalSection.tsx',
    'components/research/sections/DecisionLessonsSection.tsx',
];

test('selects de formulario: 44 px y texto de 16 px en móvil', () => {
    let nuevos = 0;
    for (const path of FILES) {
        const src = readFileSync(path, 'utf8');
        assert.ok(!src.includes(VIEJO), `${path}: select de 36 px sin área táctil`);
        nuevos += src.split(NUEVO).length - 1;
    }
    assert.equal(nuevos, 4, 'los cuatro selects con 44 px en móvil');
});
