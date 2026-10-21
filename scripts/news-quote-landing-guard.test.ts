/**
 * Guard de la barrera anti-landing en noticias (caso real HYMC 21-oct-2026:
 * la página /quote/HYMC de Yahoo Finance, «…Stock Price, News, Quote &
 * History», apareció traducida entre las «5 noticias de mayor
 * materialidad»). Una página de cotización NO es una noticia.
 *
 * Ejecución: node --experimental-strip-types --test scripts/news-quote-landing-guard.test.ts
 */
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
// @ts-expect-error TS5097: la extensión .ts explícita la exige el runner de node.
import { isQuoteLandingEvent } from '../lib/news-landing.ts';

describe('isQuoteLandingEvent: detección estricta de landings de cotización', () => {
    it('URL /quote/ de Yahoo (raíz y regionales) es landing', () => {
        assert.equal(isQuoteLandingEvent({ url: 'https://finance.yahoo.com/quote/HYMC/' }), true);
        assert.equal(isQuoteLandingEvent({ url: 'https://sg.finance.yahoo.com/quote/HYMC?p=HYMC' }), true);
        assert.equal(isQuoteLandingEvent({ url: 'https://uk.finance.yahoo.com/quote/ASTS' }), true);
    });

    it('artículos reales de Yahoo (/news/) y otras fuentes NO son landing', () => {
        assert.equal(isQuoteLandingEvent({ url: 'https://finance.yahoo.com/news/hycroft-announces-results-123456789.html' }), false);
        assert.equal(isQuoteLandingEvent({ url: 'https://www.reuters.com/business/hycroft-2026-10-20/' }), false);
        assert.equal(isQuoteLandingEvent({ url: null, title: 'Hycroft announces drill results' }), false);
    });

    it('sin URL, la plantilla EXACTA del titular original de la página /quote es landing', () => {
        const yahooTitle = 'Hycroft Mining Holding Corporation (HYMC) Stock Price, News, Quote & History';
        assert.equal(isQuoteLandingEvent({ url: null, original_headline: yahooTitle }), true);
        assert.equal(isQuoteLandingEvent({ url: null, title: yahooTitle, original_headline: yahooTitle }), true);
        // La traducción NO se usa para clasificar (se clasifica el verbatim):
        // con solo el título traducido y sin original, no hay evidencia.
        assert.equal(isQuoteLandingEvent({ url: null, title: 'Precio de la acción, noticias, cotización e historial de Hycroft (HYMC)' }), false);
        // Un titular real que menciona cotización no cae: plantilla exacta.
        assert.equal(isQuoteLandingEvent({ url: null, original_headline: 'HYMC stock price jumps after drill results' }), false);
    });
});

describe('barrera aplicada en la acción de noticias', () => {
    it('getResearchNews filtra landings para TODAS las superficies', () => {
        const actions = readFileSync('lib/actions/research.actions.ts', 'utf8');
        assert.match(actions, /import \{ isQuoteLandingEvent \} from '@\/lib\/news-landing';/);
        assert.match(actions, /return events\.filter\(\(event\) => !isQuoteLandingEvent\(event\)\)/);
    });
});
