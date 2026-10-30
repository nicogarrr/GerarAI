import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { currencyOptions, defaultCurrencyFor, SUFFIX_CURRENCY_FOR_TESTS, TRANSACTION_CURRENCIES } from '@/components/portfolio/transactionCurrencies';

describe('divisa por defecto segun el sufijo del ticker', () => {
    it('nordicos y Varsovia en su divisa, no en EUR', () => {
        expect(defaultCurrencyFor('VOLV-B.ST')).toBe('SEK');
        expect(defaultCurrencyFor('NOVO-B.CO')).toBe('DKK');
        expect(defaultCurrencyFor('EQNR.OL')).toBe('NOK');
        expect(defaultCurrencyFor('PKO.WA')).toBe('PLN');
        expect(defaultCurrencyFor('NOKIA.HE')).toBe('EUR');
        expect(defaultCurrencyFor('SAN.MC')).toBe('EUR');
        expect(defaultCurrencyFor('AAPL')).toBeNull();
    });

    it('coincide con SUFFIX_QUOTE_UNIT del backend en cada sufijo que ambos conocen', () => {
        const py = readFileSync(join(process.cwd(), 'data-engine/app/valuation/currency.py'), 'utf8');
        const block = py.slice(py.indexOf('SUFFIX_QUOTE_UNIT'), py.indexOf('}', py.indexOf('SUFFIX_QUOTE_UNIT')));
        const backend = Object.fromEntries([...block.matchAll(/"\.([A-Z]+)":\s*"([A-Z]+)"/g)].map((m) => [m[1], m[2]]));
        const minor: Record<string, string> = { GBX: 'GBP', ZAC: 'ZAR', ILA: 'ILS' };
        const mismatches = Object.entries(SUFFIX_CURRENCY_FOR_TESTS)
            .filter(([suffix]) => suffix in backend)
            .filter(([suffix, cur]) => (minor[backend[suffix]] ?? backend[suffix]) !== cur)
            .map(([suffix, cur]) => `.${suffix}: front ${cur} / back ${backend[suffix]}`);
        expect(Object.keys(backend).length).toBeGreaterThan(20);
        expect(mismatches).toEqual([]);
    });

    it('cada divisa por defecto se puede elegir en el selector', () => {
        for (const cur of Object.values(SUFFIX_CURRENCY_FOR_TESTS)) expect(TRANSACTION_CURRENCIES).toContain(cur);
        expect(currencyOptions('ZAR')[0]).toBe('ZAR');
        expect(currencyOptions('EUR')).toBe(TRANSACTION_CURRENCIES);
    });
});
