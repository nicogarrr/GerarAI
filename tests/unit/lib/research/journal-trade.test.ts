import { describe, expect, it } from 'vitest';
import { dayEs, describeFairValue, describeTrade, type JournalFairValue } from '@/lib/research/journal-trade';

const trade = { id: 1, trade_date: '2026-03-05', action: 'buy', quantity: 10, price: 12.5, currency: 'EUR' };

describe('dayEs', () => {
    it('ISO -> dd/mm/aaaa; ausente o roto -> s/d', () => {
        expect(dayEs('2026-03-05T10:00:00Z')).toBe('05/03/2026');
        expect(dayEs(null)).toBe('s/d');
        expect(dayEs('5 marzo')).toBe('s/d');
    });
});

describe('describeTrade', () => {
    it('compra con cantidad, precio con coma decimal y divisa', () => {
        expect(describeTrade(trade)).toBe('Compra 10 @ 12,50 EUR · 05/03/2026');
    });
    it('venta, cantidad fraccionaria hasta 4 decimales y miles es-ES', () => {
        expect(describeTrade({ ...trade, action: 'sell', quantity: 12345.56789, price: 10000 })).toBe('Venta 12.345,5679 @ 10.000,00 EUR · 05/03/2026');
    });
    it('sin cantidad ni precio no inventa ceros; sin divisa no pone divisa', () => {
        expect(describeTrade({ ...trade, quantity: null, price: null })).toBe('Compra · 05/03/2026');
        expect(describeTrade({ ...trade, currency: null })).toBe('Compra 10 @ 12,50 · 05/03/2026');
    });
    it('cantidad 0 se muestra como 0 (no se confunde con ausente)', () => {
        expect(describeTrade({ ...trade, quantity: 0 })).toContain('Compra 0 @');
    });
    it('action_label manda; acción desconocida se muestra cruda; fecha mala -> s/d', () => {
        expect(describeTrade({ ...trade, action_label: 'Aportación' })).toMatch(/^Aportación/);
        expect(describeTrade({ ...trade, action: 'split', trade_date: 'x' })).toMatch(/^split 10 .* · s\/d$/);
    });
});

describe('describeFairValue', () => {
    const fv: JournalFairValue = { value: 100, source: 'tesis', version: 2, as_of: '2026-03-01', stale: false, label: 'Tesis v2', margin_vs_trade_price: 0.256, note: 'nota' };
    it('sin lectura: lo dice explícitamente', () => {
        expect(describeFairValue(null)).toBe('Valor justo ese día: sin valoración previa a la operación.');
        expect(describeFairValue(undefined)).toMatch(/sin valoración/);
    });
    it('con margen positivo lleva signo +, con coma', () => {
        expect(describeFairValue(fv)).toBe('Valor justo ese día: 100,00 (Tesis v2, 01/03/2026) · margen +25,6 %');
    });
    it('margen negativo lleva signo menos; margen 0 sin signo', () => {
        expect(describeFairValue({ ...fv, margin_vs_trade_price: -0.1 })).toMatch(/margen -10,0 %$/);
        expect(describeFairValue({ ...fv, margin_vs_trade_price: 0 })).toMatch(/margen 0,0 %$/);
    });
    it('sin margen muestra la nota; sin nota ni margen no añade nada; sin fecha solo etiqueta', () => {
        expect(describeFairValue({ ...fv, margin_vs_trade_price: null, as_of: null })).toBe('Valor justo ese día: 100,00 (Tesis v2) · nota');
        expect(describeFairValue({ ...fv, margin_vs_trade_price: null, note: null })).toBe('Valor justo ese día: 100,00 (Tesis v2, 01/03/2026)');
    });
});
