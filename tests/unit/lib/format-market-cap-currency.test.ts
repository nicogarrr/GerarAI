import { describe, expect, it } from 'vitest';
import { formatMarketCap, formatMoneyCompact } from '@/lib/format';

// Watchlist: la capitalización en EUR/GBP salía con la escala compacta de Intl
// es-ES, la inconsistente que formatCompact ya corrigió para el USD (B18):
// 9.447 M € en vez de «9,45 mil M €». Y una cotización en peniques (GBp) salía
// rotulada «GBP», cien veces más grande de lo que es.
const nb = (s: string) => s.replace(/\u00a0|\u202f/g, ' ');

describe('formatMarketCap en divisas distintas del USD', () => {
    it('usa la escala es-ES fija («mil M») también en EUR y GBP', () => {
        expect(nb(formatMarketCap(9.447e9, 'EUR'))).toBe('9,45 mil M €');
        expect(nb(formatMarketCap(416.16e9, 'EUR'))).toBe('416,16 mil M €');
        expect(nb(formatMarketCap(3.4e12, 'EUR'))).toBe('3,4 B €');
        expect(nb(formatMarketCap(9.447e9, 'GBP'))).toBe('9,45 mil M GBP');
    });
    it('peniques: símbolo «p», nunca «GBP»', () => {
        expect(nb(formatMarketCap(9.447e9, 'GBp'))).toBe('9,45 mil M p');
        expect(nb(formatMarketCap(9.447e9, 'GBX'))).toBe('9,45 mil M p');
        expect(nb(formatMarketCap(9.447e9, 'GBp', undefined, 'en'))).toBe('9.45B p');
        expect(nb(formatMoneyCompact(1.2e9, 'GBp', {}, undefined, 'en'))).toBe('1.2B p');
    });
    it('sin divisa: número compacto con la misma escala fija', () => {
        expect(nb(formatMarketCap(9.447e9, null))).toBe('9,45 mil M');
        expect(nb(formatMarketCap(9.447e9, null, undefined, 'en'))).toBe('9.45B');
    });
    it('en inglés sigue la escala inglesa', () => {
        expect(nb(formatMarketCap(9.447e9, 'EUR', undefined, 'en'))).toBe('€9.45B');
    });
});
