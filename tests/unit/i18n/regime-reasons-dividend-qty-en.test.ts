import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

import { textoRegimen } from '@/components/market/MarketRegime';
import { formatPositionQuantity } from '@/lib/portfolio-dividends-display';

const root = join(__dirname, '..', '..', '..');
const engine = (relative: string) => readFileSync(join(root, 'data-engine', relative), 'utf8');

describe('Régimen de mercado en inglés: motivos y métodos del motor', () => {
    it('traduce los motivos del modelo de estados y de la beta de cartera', () => {
        expect(textoRegimen('historial insuficiente', 'en')).toBe('not enough history');
        expect(textoRegimen('modelo no disponible', 'en')).toBe('model not available');
        expect(
            textoRegimen('La beta de tu cartera aún no está disponible; el snapshot macro es global y no mezcla carteras.', 'en'),
        ).toBe('Your portfolio beta is not available yet; the macro snapshot is global and does not mix portfolios.');
        expect(textoRegimen('DGS10 menos DGS2 en la misma fecha', 'en')).toBe('DGS10 minus DGS2 on the same date');
    });

    it('en español y con textos desconocidos no cambia nada', () => {
        expect(textoRegimen('historial insuficiente')).toBe('historial insuficiente');
        expect(textoRegimen('historial insuficiente', 'es')).toBe('historial insuficiente');
        expect(textoRegimen('otro motivo', 'en')).toBe('otro motivo');
    });

    it('cubre todos los motivos y métodos en español que declara el motor', () => {
        const sources = engine('app/services/market_regime_quant.py') + engine('app/services/market_snapshot_service.py');
        const declared = [...sources.matchAll(/"(?:reason|method)":\s*"([^"]+)"/g)]
            .map((match) => match[1])
            .filter((text) => !/^[a-z0-9_]+$/.test(text));
        expect(declared.length).toBeGreaterThan(10);
        for (const text of declared) {
            expect(textoRegimen(text, 'en'), text).not.toBe(text);
        }
    });
});

describe('Dividendos: número de títulos según el idioma', () => {
    it('en inglés usa punto decimal y separador de miles', () => {
        expect(formatPositionQuantity(25.5, 'en')).toBe('25.5');
        expect(formatPositionQuantity(1234.123456, 'en')).toBe('1,234.123456');
        expect(formatPositionQuantity(0.000001, 'en')).toBe('0.000001');
    });

    it('en español sigue igual', () => {
        expect(formatPositionQuantity(25.5)).toBe('25,5');
        expect(formatPositionQuantity(1234.123456, 'es')).toBe('1234,123456');
    });
});
