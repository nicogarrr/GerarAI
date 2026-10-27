import { describe, expect, it } from 'vitest';
import { validateTransactionForm } from '@/components/portfolio/transactionValidation';

const base = { symbol: 'AAPL', type: 'buy' as const, quantity: '1', price: '1', date: '2026-01-15' };
const now = new Date('2026-02-01T10:00:00');

describe('validateTransactionForm comisión', () => {
  it('vacía o ausente es válida (opcional)', () => {
    expect(validateTransactionForm(base, now)).toEqual({});
    expect(validateTransactionForm({ ...base, fees: '' }, now)).toEqual({});
  });
  it('acepta 0 y decimales con coma', () => {
    expect(validateTransactionForm({ ...base, fees: '0' }, now)).toEqual({});
    expect(validateTransactionForm({ ...base, fees: '1,25' }, now)).toEqual({});
  });
  it('rechaza negativa o no numérica', () => {
    expect(validateTransactionForm({ ...base, fees: '-1' }, now).fees).toContain('comisión válida');
    expect(validateTransactionForm({ ...base, fees: 'abc' }, now).fees).toContain('comisión válida');
  });
});
