import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

/** The journal stays reachable on mobile through the compact advanced menu. */
const page = readFileSync('app/(root)/research/[ticker]/page.tsx', 'utf8');
const navigation = readFileSync('components/research/CompanyNavigation.tsx', 'utf8');
const panels = readFileSync('components/research/FundamentalModelPanels.tsx', 'utf8');

describe('entrada al diario de decisiones desde la ficha', () => {
    it('la ficha monta la navegación con el enlace compacto y su ancla', () => {
        assert.match(page, /<CompanyNavigation ticker=\{ticker\} activeView=\{activeView\}/);
        assert.match(navigation, /data-testid="decision-journal-entry"/);
        assert.match(navigation, /\?view=changes#diario-decisiones/);
        assert.match(navigation, /Diario de decisiones/);
    });
    it('el enlace está en avanzados accesible también en móvil', () => {
        const entry = navigation.indexOf('data-testid="decision-journal-entry"');
        const linkStart = navigation.lastIndexOf('<Link', entry);
        const tag = navigation.slice(linkStart, navigation.indexOf('>', entry));
        assert.doesNotMatch(tag, /\bhidden\b/);
        // Enlace a un ancla: con scroll={false} Next no baja hasta el diario.
        assert.doesNotMatch(tag, /scroll=\{false\}/);
        const details = navigation.indexOf('<details');
        const summary = navigation.indexOf('<summary', details);
        assert.ok(details >= 0 && summary > details && entry > summary);
        assert.match(navigation, /Análisis avanzado/);
        assert.match(navigation, /min-h-\[44px\]/);
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
