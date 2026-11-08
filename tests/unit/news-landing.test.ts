import { describe, expect, it } from 'vitest';

import { isQuoteLandingEvent } from '@/lib/news-landing';

// Barrera de presentación: una página de cotización (landing) indexada por la
// ingesta NO es una noticia y no puede pintarse como material. Caso real:
// ficha HYMC, 21-oct-2026 (/quote/HYMC de Yahoo colada en «5 noticias»).

describe('isQuoteLandingEvent', () => {
    it('URL de cotización de Yahoo: landing', () => {
        expect(isQuoteLandingEvent({ url: 'https://finance.yahoo.com/quote/HYMC' })).toBe(true);
        expect(isQuoteLandingEvent({ url: 'https://sg.finance.yahoo.com/quote/HYMC/key-statistics' })).toBe(true);
        expect(isQuoteLandingEvent({ url: 'HTTPS://UK.FINANCE.YAHOO.COM/QUOTE/TSLA' })).toBe(true);
    });

    it('artículo de Yahoo en /news/: NO se toca', () => {
        expect(isQuoteLandingEvent({ url: 'https://finance.yahoo.com/news/tesla-results-123456.html' })).toBe(false);
    });

    it('URL de cotización de otro dominio: no es el caso Yahoo', () => {
        expect(isQuoteLandingEvent({ url: 'https://example.com/quote/TSLA' })).toBe(false);
    });

    it('sin URL: la plantilla exacta del titular de la landing delata la página', () => {
        expect(
            isQuoteLandingEvent({
                original_headline: 'Hycroft Mining Holding Corporation (HYMC) Stock Price, News, Quote & History',
            }),
        ).toBe(true);
        expect(isQuoteLandingEvent({ title: 'Tesla, Inc. (TSLA) Stock Price, News, Quote and History' })).toBe(true);
    });

    it('el original de la fuente manda sobre el título traducido', () => {
        // Caso HYMC real: el título guardado era la traducción; el original
        // ingerido conserva la plantilla inglesa que lo delata.
        expect(
            isQuoteLandingEvent({
                title: 'Precio de la acción, noticias, cotización e historial de Hycroft Mining (HYMC)',
                original_headline: 'Hycroft Mining Holding Corporation (HYMC) Stock Price, News, Quote & History',
            }),
        ).toBe(true);
    });

    it('titular de noticia normal: no es landing', () => {
        expect(isQuoteLandingEvent({ title: 'Tesla supera previsiones de beneficios' })).toBe(false);
        expect(isQuoteLandingEvent({})).toBe(false);
    });
});
