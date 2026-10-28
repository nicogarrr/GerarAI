import { describe, expect, it } from 'vitest';
import { validateTransactionForm } from '@/components/portfolio/transactionValidation';

const base = { symbol: 'AAPL', type: 'buy' as const, quantity: '1', price: '1', date: '2026-01-15' };
const now = new Date('2026-02-01T10:00:00');
const AMBIGUO = 'Formato de número ambiguo';

describe('validateTransactionForm: formato ambiguo se explica en español', () => {
    it.each([
        ['1,234.5', 'orden US mezclado'],
        ['1,234', 'coma con 3 dígitos'],
    ])('cantidad %s (%s) no se reinterpreta con factor 1000', (quantity) => {
        expect(validateTransactionForm({ ...base, quantity }, now).quantity).toContain(AMBIGUO);
    });
    it('precio «1,234.5» rechazado con el mismo mensaje', () => {
        expect(validateTransactionForm({ ...base, price: '1,234.5' }, now).price).toContain(AMBIGUO);
    });
    it('comisión «1,234» rechazada con el mismo mensaje', () => {
        expect(validateTransactionForm({ ...base, fees: '1,234' }, now).fees).toContain(AMBIGUO);
    });
    it('los formatos es-ES normales siguen entrando', () => {
        expect(validateTransactionForm({ ...base, quantity: '32,5', price: '1.234,56', fees: '0,25' }, now)).toEqual({});
    });
    it('«1e3» ya no vale como 1000', () => {
        expect(validateTransactionForm({ ...base, quantity: '1e3' }, now).quantity).toContain('cantidad mayor que 0');
    });
    it('negativos: cantidad <= 0 mantiene su mensaje propio', () => {
        expect(validateTransactionForm({ ...base, quantity: '-32,5' }, now).quantity).toContain('cantidad mayor que 0');
    });
});
