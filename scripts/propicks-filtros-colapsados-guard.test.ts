// Guard: en móvil los filtros de ProPicks van colapsados por defecto (los
// picks primero) y el toggle es accesible; en xl siempre visibles.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const SRC = readFileSync('components/proPicks/EnhancedProPicksFilters.tsx', 'utf8');

test('cuerpo colapsado por defecto en móvil, visible en xl', () => {
    assert.ok(SRC.includes("useState(false)"), 'el panel debe arrancar colapsado');
    assert.ok(SRC.includes("hidden'} xl:block"), 'el cuerpo debe ocultarse en móvil y mostrarse en xl');
    assert.ok(SRC.includes('min-h-[44px] xl:hidden'), 'el toggle debe seguir accesible hasta xl');
    assert.ok(SRC.includes('aria-expanded={open}') && SRC.includes('aria-controls="propicks-filtros-cuerpo"'));
});

test('un filtro activo nunca queda invisible con el panel colapsado', () => {
    assert.ok(SRC.includes('activeFilterCount'), 'contador de filtros activos ausente');
    assert.ok(SRC.includes('DEFAULT_FILTERS'));
    assert.ok(SRC.includes("'filtro' : 'filtros'") || SRC.includes("'filtro' : 'filtros'".replace(' : ', ' : ')));
});


test('el grid y el panel cambian juntos en xl para evitar una sidebar estrecha', () => {
    const content = readFileSync('components/proPicks/EnhancedProPicksContent.tsx', 'utf8');
    for (const token of ['xl:grid-cols-4', 'xl:col-span-1', 'xl:col-span-3']) {
        assert.ok(content.includes(token), `falta ${token}`);
    }
    assert.ok(!content.includes('lg:grid-cols-4'));
    assert.ok(!SRC.includes("hidden'} lg:block"));
});
