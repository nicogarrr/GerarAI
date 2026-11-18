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

    it('posiciones sin operaciones: enlaza a la cuenta demo', () => {
        // Ruta verificada: el componente se pinta dentro de /paper-trading y
        // el CTA devuelve al alta (pestaña «Operar») de esa misma ruta.
        readFileSync('app/(root)/paper-trading/page.tsx', 'utf8');
        const table = readFileSync('components/paper-trading/PositionsTable.tsx', 'utf8');
        const es = JSON.parse(readFileSync('lib/i18n/messages/es/paperTrading.json', 'utf8'));
        assert.equal(es.panel.tradePanel, 'Registrar operación');
        assert.ok(table.includes("<EmptyLink href=\"/paper-trading\">{ti('paperTrading.panel.tradePanel')}</EmptyLink>"), 'CTA reutiliza la etiqueta del alta');
    });

    it('lecciones sin datos: enlaza al diario de decisiones de la ficha', () => {
        // Ruta y ancla verificadas: DecisionJournalEntryLink y ResearchHashScroll.
        readFileSync('app/(root)/research/[ticker]/page.tsx', 'utf8');
        const section = readFileSync('components/research/sections/DecisionLessonsSection.tsx', 'utf8');
        const es = JSON.parse(readFileSync('lib/i18n/messages/es/research.json', 'utf8'));
        assert.equal(es.journal.title, 'Diario de decisiones');
        const empty = section.slice(section.indexOf('!lessons.length'));
        assert.ok(/<EmptyLink href=\{`\/research\/\$\{encodeURIComponent\(ticker\)\}\?view=seguimiento#diario-decisiones`\}>\{t\('research\.journal\.title'\)\}<\/EmptyLink>/.test(empty), 'CTA al diario con el ancla existente');
    });

    it('sin noticias recientes: enlaza a /research/news', () => {
        readFileSync('app/(root)/research/news/page.tsx', 'utf8');
        const page = readFileSync('app/(root)/research/[ticker]/page.tsx', 'utf8');
        const notice = page.slice(page.indexOf('fichaNoRecentNews') - 400, page.indexOf('fichaNoRecentNews') + 100);
        assert.ok(notice.includes('<NewsPreparingNotice'), 'el vacío sigue pasando por NewsPreparingNotice');
        assert.ok(notice.includes('action={<EmptyLink href="/research/news">{t(\'research.fichaAnalyzeLatestNews\')}</EmptyLink>}'), 'reutiliza el EmptyLink y la clave ya existentes');
        assert.ok(!notice.includes('description='), 'el vacío de noticias sigue siendo solo título + CTA');
    });

    it('los enlaces a /security de las páginas legales avisan de que requieren sesión', () => {
        for (const area of ['terminos', 'privacidad']) {
            const page = readFileSync(`app/(public)/${area}/page.tsx`, 'utf8');
            const links = (page.match(/href="\/security"/g) ?? []).length;
            const notes = (page.match(/\{t\('landing\.securityLinkNote'\)\}/g) ?? []).length;
            assert.ok(links > 0, `${area}: hay enlaces a /security`);
            assert.equal(notes, links, `${area}: cada enlace lleva su aviso`);
        }
        const es = JSON.parse(readFileSync('lib/i18n/messages/es/landing.json', 'utf8'));
        const en = JSON.parse(readFileSync('lib/i18n/messages/en/landing.json', 'utf8'));
        assert.match(es.securityLinkNote, /sesión/);
        assert.match(en.securityLinkNote, /sign-in/i);
    });
});
