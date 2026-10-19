// Guard: en móvil los filtros de ProPicks van colapsados por defecto (los
// picks primero) y el toggle es accesible; en lg siempre visibles.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const SRC = readFileSync('components/proPicks/EnhancedProPicksFilters.tsx', 'utf8');

test('cuerpo colapsado por defecto en móvil, visible en lg', () => {
    assert.ok(SRC.includes("useState(false)"), 'el panel debe arrancar colapsado');
    assert.ok(SRC.includes("hidden'} lg:block"), 'el cuerpo debe ocultarse en móvil y mostrarse en lg');
    assert.ok(SRC.includes('aria-expanded={open}') && SRC.includes('aria-controls="propicks-filtros-cuerpo"'));
});
