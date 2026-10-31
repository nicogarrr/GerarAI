/**
 * «Sin empresas del universo expuestas» sobre una noticia etiquetada ASTS
 * parecía un fallo de la etiqueta: el análisis de segundo orden excluye a
 * propósito a la empresa protagonista (second_order_news_service.py) y el
 * copy no lo decía. Ahora la fila declara la exclusión con el ticker.
 * Ejecución: node --experimental-strip-types --test scripts/news-second-order-subject-guard.test.ts
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const source = (rel: string) => readFileSync(join(here, '..', rel), 'utf8');

void test('el estado sin_datos explica la exclusión de la empresa protagonista', () => {
    const panel = source('components/research/NewsSecondOrder.tsx');
    assert.ok(panel.includes('subjectTicker'), 'recibe el ticker protagonista');
    assert.ok(panel.includes("t('research.flow.second.noneWithSubject', { ticker: subjectTicker })"), 'declara la exclusión');
    const es = JSON.parse(source('lib/i18n/messages/es/research.json')).flow.second;
    assert.ok(es.noneWithSubject.includes('excluye a propósito a la propia {ticker}'), 'ES conserva el literal');
});

void test('ambos call sites pasan el ticker del evento', () => {
    const flow = source('components/research/NewsEventsFlow.tsx');
    const occurrences = flow.split('<NewsSecondOrder eventId={event.id} subjectTicker={event.ticker}').length - 1;
    assert.equal(occurrences, 2, 'lista móvil y tabla escritorio');
});
