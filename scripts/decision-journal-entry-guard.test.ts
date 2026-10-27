import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

/**
 * Prueba real en vivo: desde /research/POOL no había forma de llegar al
 * formulario «Decisión» del diario (vive en ?view=changes, rotulado «Cambios y
 * revisiones», sin ningún enlace desde el resumen). El resumen enlaza ahora al
 * diario con un ancla que existe en el panel, visible también en móvil.
 */
const page = readFileSync('app/(root)/research/[ticker]/page.tsx', 'utf8');
const panels = readFileSync('components/research/FundamentalModelPanels.tsx', 'utf8');

describe('entrada al diario de decisiones desde la ficha', () => {
    it('el resumen enlaza al diario con ancla', () => {
        assert.match(page, /data-testid="decision-journal-entry"/);
        assert.match(page, /\?view=changes#diario-decisiones/);
        assert.match(page, /Registrar una decisión/);
    });
    it('el enlace no está oculto en móvil (no va dentro del panel hidden md:block)', () => {
        const entry = page.indexOf('data-testid="decision-journal-entry"');
        const linkStart = page.lastIndexOf('<Link', entry);
        const tag = page.slice(linkStart, page.indexOf('>', entry));
        assert.doesNotMatch(tag, /\bhidden\b/);
        const porDondeSeguir = page.indexOf('title="Por dónde seguir"');
        const panelEnd = page.indexOf('</Panel>', porDondeSeguir);
        assert.ok(entry > panelEnd, 'el enlace debe ir fuera del panel solo-escritorio «Por dónde seguir»');
    });
    it('el ancla existe en el panel que contiene el formulario «Decisión»', () => {
        assert.match(panels, /id="diario-decisiones"/);
        const anchor = panels.indexOf('id="diario-decisiones"');
        const form = panels.indexOf('aria-label="Decisión"');
        assert.ok(anchor > 0 && form > anchor, 'el ancla debe preceder al select «Decisión»');
    });
    it('la vista changes sigue pintando el panel del diario', () => {
        assert.match(page, /<DecisionAndRealityPanel ticker=\{ticker\}/);
    });
});
