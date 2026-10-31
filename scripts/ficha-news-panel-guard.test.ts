/**
 * Guard del panel «Últimas noticias» de la ficha (QA 18/10): fechas es-ES,
 * dedupe por el titular mostrado y cero relleno de «traducción no
 * disponible» bajo titulares en inglés.
 */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const fichaEs = JSON.parse(readFileSync('lib/i18n/messages/es/research.json', 'utf8')).ficha;
const page = readFileSync('app/(root)/research/[ticker]/page.tsx', 'utf8');
const headline = readFileSync('components/research/NewsHeadline.tsx', 'utf8');

test('la fecha de la noticia se pinta es-ES, nunca ISO crudo', () => {
    const fn = page.slice(page.indexOf('function newsDateLabel'));
    const body = fn.slice(0, fn.indexOf('\n}'));
    assert.ok(body.includes('formatUserDate(event.date, undefined, undefined, locale)'), 'newsDateLabel debe usar formatUserDate');
    assert.ok(!body.includes('.slice(0, 10)'), 'prohibido el ISO crudo YYYY-MM-DD');
    // La provenance se conserva: solo 'source' afirma fecha de publicación.
    assert.ok(body.includes("date_source === 'source'"));
    assert.ok(body.includes("t('research.ficha.dateDetected', { date: day })"));
    assert.ok(body.includes("t('research.ficha.dateIngested', { date: day })"));
    assert.equal(fichaEs.dateDetected, 'Detectada el {date}');
    assert.equal(fichaEs.dateIngested, 'Incorporada el {date}');
    assert.equal(fichaEs.dateUnverified, 'Fecha no verificada ({date})');
});

test('el panel deduplica por el titular que se pinta', () => {
    const start = page.indexOf("entry.key === 'overview-news'");
    const block = page.slice(start, page.indexOf('.slice(0, 5)', start));
    assert.ok(
        block.includes('newsDisplayTitle(event.title, event.ticker, event.headline_from_source, event.original_headline)'),
        'dedupeNewsEvents debe recibir el titular de display',
    );
});

test('sin relleno de traducción bajo el titular', () => {
    assert.ok(!headline.includes('traducción no disponible'), 'nada de meta-texto de fallo: el original ya es honesto');
    // La traducción, cuando existe, sigue etiquetada con su provenance.
    const es = JSON.parse(readFileSync('lib/i18n/messages/es/research.json', 'utf8')).translate;
    assert.ok(headline.includes("{t('research.translate.autoLabel')}"));
    assert.equal(es.autoLabel, 'Traducción automática · español');
    assert.ok(headline.includes("<summary className=\"min-h-11 cursor-pointer py-3\">{t('research.translate.viewOriginal')}</summary>"), 'misma etiqueta que el resumen: una sola «Ver original» por fila');
    assert.equal(es.viewOriginal, 'Ver original');
    assert.ok(!headline.includes('Ver titular original'), 'sin doble etiqueta «Ver titular original»/«Ver original» (Tester 4 nº4)');
});
