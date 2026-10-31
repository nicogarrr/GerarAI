import { describe, expect, it } from 'vitest';

import { isTickerNotFound } from '@/lib/watchlist/lookup-status';
import esWatchlist from '@/lib/i18n/messages/es/watchlist.json';
import enWatchlist from '@/lib/i18n/messages/en/watchlist.json';

describe('isTickerNotFound (watchlist «No encontrado»)', () => {
    it('fuera del master y el proveedor no conoce el símbolo → no encontrado', () => {
        expect(isTickerNotFound(null, {}, 'ZZNOPE')).toBe(true);
        expect(isTickerNotFound(null, { name: 'ZZNOPE' }, 'zznope')).toBe(true);
    });
    it('en el master nunca es «no encontrado»', () => {
        expect(isTickerNotFound({ ticker: 'AAPL' }, {}, 'AAPL')).toBe(false);
    });
    it('proveedor caído (null) no prueba nada → sin etiqueta', () => {
        expect(isTickerNotFound(null, null, 'ZZNOPE')).toBe(false);
    });
    it('el proveedor conoce el símbolo → no es «no encontrado»', () => {
        expect(isTickerNotFound(null, { name: 'Almonty Industries' }, 'ALM')).toBe(false);
    });
    it('rótulo en español e inglés (diccionario)', () => {
        expect(esWatchlist.page.notFound.label).toBe('No encontrado');
        expect(enWatchlist.page.notFound.label).toBe('Not found');
    });
});
