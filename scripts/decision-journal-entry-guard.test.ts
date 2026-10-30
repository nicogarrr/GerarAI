import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

/** The journal stays reachable on mobile through the compact advanced menu. */
const page = readFileSync('app/(root)/research/[ticker]/page.tsx', 'utf8');
const menu = readFileSync('components/research/CompanyActionsMenu.tsx', 'utf8');
const journalLink = readFileSync('components/research/DecisionJournalEntryLink.tsx', 'utf8');
const panels = readFileSync('components/research/FundamentalModelPanels.tsx', 'utf8');

describe('entrada al diario de decisiones desde la ficha', () => {
    it('la ficha monta el menú de cabecera con el enlace compacto y su ancla', () => {
        // Con la navegación de una fila (29-oct-2026) el enlace vive en el
        // menú compacto de cabecera, accesible también en móvil.
        assert.match(page, /<CompanyActionsMenu/);
        assert.match(menu, /<DecisionJournalEntryLink className=\{ITEM\} ticker=\{ticker\} \/>/);
        assert.match(journalLink, /data-testid="decision-journal-entry"/);
        assert.match(journalLink, /DECISION_JOURNAL_ANCHOR = 'diario-decisiones'/);
        assert.match(journalLink, /\?view=seguimiento#\$\{DECISION_JOURNAL_ANCHOR\}/);
        assert.match(journalLink, /scrollToHashAnchor\(DECISION_JOURNAL_ANCHOR\)/);
        assert.match(journalLink, /Diario de decisiones/);
    });
    it('el enlace sigue siendo un ancla con scroll gestionado por el llamador', () => {
        // Enlace a un ancla: con scroll={false} Next no baja hasta el diario.
        assert.doesNotMatch(journalLink.slice(journalLink.indexOf('return <Link')), /scroll=\{false\}/);
        // El área táctil la da la clase ITEM del menú (44px en móvil).
        assert.match(menu, /const ITEM = 'flex min-h-\[44px\] items-center/);
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
