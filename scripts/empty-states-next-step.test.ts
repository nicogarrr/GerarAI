import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

/**
 * Guard: estados vacíos con siguiente paso (auditoría UX móvil 2026-10-27).
 * Medido a 375 px con la base vacía: /research/<ticker>/tesis sin ninguna
 * versión pintaba solo «Aún no hay ninguna tesis publicada» sin texto ni
 * acción, una pantalla sin salida.
 */

describe('estados vacíos con siguiente paso', () => {
    it('tesis sin ninguna versión: explica y enlaza a generar la primera', () => {
        const page = readFileSync('app/(root)/research/[ticker]/tesis/page.tsx', 'utf8');
        const i = page.indexOf("t('research.thesisDoc.noPublishedTitle'");
        const es = JSON.parse(readFileSync('lib/i18n/messages/es/research.json', 'utf8')).thesisDoc;
        assert.match(es.noPublishedTitle, /^Aún no hay ninguna tesis publicada/);
        assert.match(es.generateFirst, /^Generar la primera tesis/);
        assert.ok(i > 0, 'estado vacío de tesis existe');
        const block = page.slice(page.lastIndexOf('<EmptyState', i), i);
        assert.ok(/: <EmptyLink href=\{`\/research\/\$\{encoded\}`\}>\{t\('research\.thesisDoc\.generateFirst'\)\}/.test(block), 'sin versiones: CTA a la ficha para generar la primera tesis');
        assert.ok(!/description=\{latest \? [^}]*: undefined\}/.test(block), 'sin versiones: hay descripción, no undefined');
    });
});
