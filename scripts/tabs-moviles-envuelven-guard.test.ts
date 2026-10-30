// Guard: las tiras de tabs no se cortan a media palabra en móvil; envuelven
// a varias filas (patrón de HubNav), sin scroll horizontal oculto.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const SECTION = readFileSync('components/layout/SectionNav.tsx', 'utf8');
const PROPICKS = readFileSync('components/proPicks/ProPicksTabs.tsx', 'utf8');
const RESEARCH = readFileSync('components/research/CompanyNavigation.tsx', 'utf8');

test('las tres tiras envuelven en móvil', () => {
    // Decisión de Nico (WhatsApp 2026-10-20 01:34): la barra va PLEGADA en
    // móvil: una línea con la pestaña actual y chevron que despliega el resto
    // y el estado se recuerda. La lista desplegada sigue en una fila con
    // scroll; el wrap completo vuelve solo desde sm.
    assert.ok(SECTION.includes("localStorage.getItem('subnav-seccion')"), 'SectionNav: recuerda plegado/desplegado');
    assert.ok(SECTION.includes('aria-expanded={open}'), 'SectionNav: botón con aria-expanded');
    assert.ok(SECTION.includes('scroll={false}'), 'SectionNav: los enlaces conservan el scroll');
    // La fila con scroll vive en OverflowScrollRegion (pista de overflow);
    // la lista interna mantiene una fila en movil y wrap solo desde sm.
    assert.ok(SECTION.includes('flex flex-nowrap gap-1.5 sm:flex-wrap'), 'SectionNav: lista desplegada en una fila, wrap solo desde sm');
    assert.ok(SECTION.includes('<OverflowScrollRegion'), 'SectionNav: el scroll lo da la region con pista');
    assert.ok(PROPICKS.includes('flex-wrap justify-start gap-1'), 'TabsList ProPicks sin wrap');
    assert.ok(!PROPICKS.includes('snap-x'), 'TabsList ProPicks sigue con snap scroll');
    // Ficha (29-oct-2026, «Una fila, no tres menús»): UNA fila de seis
    // pestañas que se desliza en horizontal en móvil (scroll nativo), sin
    // cortar palabras (whitespace-nowrap + shrink-0 en cada pestaña).
    assert.ok(RESEARCH.includes('overflow-x-auto'), 'ficha: la fila de pestañas se desliza en móvil');
    assert.ok(RESEARCH.includes('whitespace-nowrap'), 'ficha: las pestañas no cortan palabras');
    assert.ok(RESEARCH.includes('data-testid="company-navigation"'), 'ficha: una sola navegación');
});
