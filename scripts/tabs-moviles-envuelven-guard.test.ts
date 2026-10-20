// Guard: las tiras de tabs no se cortan a media palabra en móvil; envuelven
// a varias filas (patrón de HubNav), sin scroll horizontal oculto.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const SECTION = readFileSync('components/layout/SectionNav.tsx', 'utf8');
const PROPICKS = readFileSync('components/proPicks/ProPicksTabs.tsx', 'utf8');
const RESEARCH = readFileSync('app/(root)/research/[ticker]/page.tsx', 'utf8');

test('las tres tiras envuelven en móvil', () => {
    // Decisión de Nico (WhatsApp 2026-10-20 01:34): la barra va PLEGADA en
    // móvil: una línea con la pestaña actual y chevron que despliega el resto
    // y el estado se recuerda. La lista desplegada sigue en una fila con
    // scroll; el wrap completo vuelve solo desde sm.
    assert.ok(SECTION.includes("localStorage.getItem('subnav-seccion')"), 'SectionNav: recuerda plegado/desplegado');
    assert.ok(SECTION.includes('aria-expanded={open}'), 'SectionNav: botón con aria-expanded');
    assert.ok(SECTION.includes('scroll={false}'), 'SectionNav: los enlaces conservan el scroll');
    assert.ok(SECTION.includes('flex-nowrap gap-1.5 overflow-x-auto'), 'SectionNav: lista desplegada en una fila con scroll');
    assert.ok(SECTION.includes('sm:flex-wrap'), 'SectionNav: wrap solo desde sm');
    assert.ok(PROPICKS.includes('flex-wrap justify-start gap-1'), 'TabsList ProPicks sin wrap');
    assert.ok(!PROPICKS.includes('snap-x'), 'TabsList ProPicks sigue con snap scroll');
    assert.ok(RESEARCH.includes('flex-wrap gap-x-6 gap-y-2'), 'nav de etapas sin wrap');
    assert.ok(RESEARCH.includes('mb-7 flex flex-wrap gap-2'), 'nav de módulos sin wrap móvil');
});
