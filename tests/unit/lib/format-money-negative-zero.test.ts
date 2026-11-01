import { describe, expect, it } from 'vitest';
import { formatMoney, formatMoneyCompact, formatPrice } from '@/lib/format';

// Un importe que redondea a cero es cero, sin signo: una P&L de -0,004 € (o el
// -0 que da JavaScript al negar un 0) salía «-0,00 €». formatNumber y
// formatCompact ya lo hacían bien; el dinero no.
const MINUS = /[-\u2212]/;

describe('importes que redondean a cero', () => {
  for (const locale of ['es', 'en'] as const) {
    it(`formatMoney sin «-0» (${locale})`, () => {
      expect(formatMoney(-0, 'EUR', {}, undefined, locale)).toBe(formatMoney(0, 'EUR', {}, undefined, locale));
      expect(formatMoney(-0.004, 'USD', {}, undefined, locale)).not.toMatch(MINUS);
      expect(formatMoney(-0.4, 'GBp', { maximumFractionDigits: 0 }, undefined, locale)).not.toMatch(MINUS);
    });

    it(`formatPrice sin «-0» (${locale})`, () => {
      expect(formatPrice(-0, 'USD', {}, undefined, locale)).toBe(formatPrice(0, 'USD', {}, undefined, locale));
    });

    it(`formatMoneyCompact sin «-0» (${locale})`, () => {
      expect(formatMoneyCompact(-0.001, 'USD', {}, undefined, locale)).not.toMatch(MINUS);
    });

    it(`los negativos de verdad conservan el signo (${locale})`, () => {
      expect(formatMoney(-5, 'EUR', {}, undefined, locale)).toMatch(MINUS);
      expect(formatPrice(-0.004, 'USD', {}, undefined, locale)).toMatch(MINUS);
      expect(formatMoneyCompact(-2_500_000, 'USD', {}, undefined, locale)).toMatch(MINUS);
    });
  }

  it('respeta un signDisplay pedido por quien llama', () => {
    expect(formatMoney(5, 'EUR', { signDisplay: 'always' })).toMatch(/^\+/);
  });
});
