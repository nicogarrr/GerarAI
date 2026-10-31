import { describe, expect, it } from 'vitest';
import { validateTransactionForm } from '@/components/portfolio/transactionValidation';

// El diálogo siembra la fecha con todayLocal() (Europe/Madrid, USER_TZ), pero
// el validador calculaba «hoy» con los getters locales del proceso. Entre las
// 23:00 y 00:00 UTC (invierno) Madrid ya está en el día siguiente: CI (UTC) o
// un navegador al oeste de Madrid rechazaban la fecha sembrada como «futura»
// y el submit moría en silencio (addTransaction no se llamaba: rojo nocturno
// intermitente de AddTransactionDialog.manual-symbol en CI).
const base = { symbol: 'AAPL', type: 'buy' as const, quantity: '1', price: '1' };

describe('validateTransactionForm: «hoy» en la misma zona que siembra el diálogo', () => {
  it('la fecha sembrada por todayLocal no es futura aunque el proceso vaya un día atrás', () => {
    // 23:30 UTC = 00:30 del 1 de noviembre en Madrid (CET): todayLocal() siembra 2026-11-01.
    const now = new Date('2026-10-31T23:30:00Z');
    expect(validateTransactionForm({ ...base, date: '2026-11-01' }, now)).toEqual({});
  });
  it('el día siguiente de verdad sí se rechaza en esa misma ventana', () => {
    const now = new Date('2026-10-31T23:30:00Z');
    expect(validateTransactionForm({ ...base, date: '2026-11-02' }, now).date).toContain('futura');
  });
  it('a plena luz del día el criterio no cambia', () => {
    const now = new Date('2026-06-15T12:00:00Z'); // 14:00 CEST
    expect(validateTransactionForm({ ...base, date: '2026-06-15' }, now)).toEqual({});
    expect(validateTransactionForm({ ...base, date: '2026-06-16' }, now).date).toContain('futura');
  });
});
