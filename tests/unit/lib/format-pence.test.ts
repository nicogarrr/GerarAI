import { describe, expect, it } from 'vitest';
import { currencySymbolEs, formatMoney, formatMoneyCompact, formatPrice } from '@/lib/format';

// Yahoo cotiza Londres en peniques («GBp»). Intl ignora mayúsculas en el código
// de divisa: formatMoney(118.25, 'GBp') salía «118,25 GBP» (libras, x100).
const nb = (s: string) => s.replace(/\u00a0|\u202f/g, ' ');

describe('peniques (GBp/GBX) se muestran como peniques', () => {
  it('formatMoney y formatPrice nunca rotulan peniques como libras', () => {
    expect(nb(formatMoney(118.25, 'GBp'))).toBe('118,25 p');
    expect(nb(formatMoney(4215, 'GBX'))).toBe('4.215,00 p');
    expect(nb(formatPrice(118.25, 'GBp'))).toBe('118,25 p');
    expect(nb(formatPrice(-0.004, 'GBp'))).toBe('-0,004 p');
    for (const s of [formatMoney(118.25, 'GBp'), formatPrice(118.25, 'GBX')]) {
      expect(s).not.toMatch(/GBP|GBX|£/);
    }
  });
  it('respeta las opciones de decimales', () => {
    expect(nb(formatMoney(1234.5, 'GBp', { maximumFractionDigits: 0, minimumFractionDigits: 0 }))).toBe('1.235 p');
  });
  it('compactos y símbolo', () => {
    expect(currencySymbolEs('GBp')).toBe('p');
    expect(nb(formatMoneyCompact(35.7e6, 'GBp'))).toBe('35,7 M p');
  });
  it('las libras siguen siendo libras', () => {
    expect(nb(formatMoney(118.25, 'GBP'))).toBe('118,25 GBP');
    expect(currencySymbolEs('GBP')).toBe('GBP');
  });
});
