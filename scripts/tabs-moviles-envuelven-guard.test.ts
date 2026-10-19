// Guard: las tiras de tabs no se cortan a media palabra en móvil; envuelven
// a varias filas (patrón de HubNav), sin scroll horizontal oculto.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const SECTION = readFileSync('components/layout/SectionNav.tsx', 'utf8');
const PROPICKS = readFileSync('components/proPicks/ProPicksTabs.tsx', 'utf8');
const RESEARCH = readFileSync('app/(root)/research/[ticker]/page.tsx', 'utf8');

test('las tres tiras envuelven en móvil', () => {
    // Decisión de Nico (WhatsApp 2026-10-20 01:15): la barra de 10 envuelta
    // ocupaba 4 filas en móvil ("la mitad es menú"). Ahora UNA fila con scroll
    // horizontal en móvil; el wrap vuelve desde sm.
    assert.ok(SECTION.includes('flex flex-nowrap gap-1.5 overflow-x-auto'), 'SectionNav: una fila con scroll en móvil');
    assert.ok(SECTION.includes('sm:flex-wrap'), 'SectionNav: wrap solo desde sm');
    assert.ok(PROPICKS.includes('flex-wrap justify-start gap-1'), 'TabsList ProPicks sin wrap');
    assert.ok(!PROPICKS.includes('snap-x'), 'TabsList ProPicks sigue con snap scroll');
    assert.ok(RESEARCH.includes('flex-wrap gap-x-6 gap-y-2'), 'nav de etapas sin wrap');
    assert.ok(RESEARCH.includes('mb-7 flex flex-wrap gap-2'), 'nav de módulos sin wrap móvil');
});
