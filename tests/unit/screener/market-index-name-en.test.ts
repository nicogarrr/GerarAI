import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

import { marketIndexName } from '@/lib/market/index-name';

// Lista real de market.py (_INDEXES), leída del .py: si cambia, el test lo nota.
const PY = readFileSync('data-engine/app/api/routes/market.py', 'utf8');
const INDEXES = [...PY.matchAll(/\{"symbol": "([^"]+)", "name": "([^"]+)", "unit": "\w+"\}/g)].map((m) => ({ symbol: m[1], name: m[2] }));

describe('Mercado: nombres de los índices en el idioma de la pantalla', () => {
    it('lee los 5 del backend', () => {
        expect(INDEXES.map((i) => i.symbol)).toEqual(['^GSPC', '^IXIC', 'BTC-USD', 'GC=F', 'SI=F']);
    });

    it('en inglés, el oro y la plata ya no salen en castellano', () => {
        expect(INDEXES.map((i) => marketIndexName(i, 'en'))).toEqual(['S&P 500', 'Nasdaq Composite', 'Bitcoin', 'Gold', 'Silver']);
    });

    it('en castellano, tal cual', () => {
        expect(INDEXES.map((i) => marketIndexName(i, 'es'))).toEqual(INDEXES.map((i) => i.name));
    });

    it('un nombre distinto del esperado pasa tal cual', () => {
        expect(marketIndexName({ symbol: 'GC=F', name: 'Gold Futures' }, 'en')).toBe('Gold Futures');
    });
});
