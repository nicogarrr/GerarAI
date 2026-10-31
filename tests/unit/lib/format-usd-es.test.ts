import { describe, expect, it } from 'vitest';
import { formatCompact, formatMarketCap, formatMarketCapUsd, formatMoney, formatMoneyCompact, formatPrice } from '@/lib/format';
import { formatFlowAmount } from '@/lib/market/flows';

// Nico (29-oct-2026, «Soluciona esos 5»): los importes en USD y demás divisas
// van en formato español, como los porcentajes: «1.500,00 US$», nunca «$1,500.00».
const nb = (s: string) => s.replace(/\u00a0|\u202f/g, ' ');

describe('USD en formato es-ES', () => {
  it('formatMoney y formatPrice', () => {
    expect(nb(formatMoney(1500, 'USD'))).toBe('1.500,00 US$');
    expect(nb(formatPrice(349.64, 'USD'))).toBe('349,64 US$');
    expect(nb(formatPrice(1500, 'GBP'))).toBe('1.500,00 GBP');
    expect(nb(formatMoney(1500, 'EUR'))).toBe('1.500,00 €');
  });
  it('compactos con la escala es-ES fija', () => {
    expect(nb(formatMarketCapUsd(4.87e9))).toBe('4,87 mil M US$');
    expect(nb(formatMarketCap(9.447e9, 'USD'))).toBe('9,45 mil M US$');
    expect(nb(formatMoneyCompact(35.7e6, 'USD'))).toBe('35,7 M US$');
    expect(nb(formatFlowAmount(35.7e9, 'USD'))).toBe('35,7 mil M US$');
  });
  it('nunca el formato inglés', () => {
    for (const s of [formatMoney(1500, 'USD'), formatPrice(93.9, 'USD'), formatMarketCapUsd(4.87e9)]) {
      expect(s).not.toMatch(/\$\d|\d,\d{3}\.\d/);
    }
  });
});

describe('escala de billones (10^12)', () => {
    // Visto en prod: la capitalización de GOOGL salía «3.414 mil M US$» y se
    // leía como tres mil cuatrocientos. Desde 1e12 la escala es «B».
    it('formatea trillones USD como B en es-ES', () => {
        expect(nb(formatMarketCapUsd(3.414e12))).toBe('3,41 B US$');
        expect(nb(formatMarketCapUsd(1e12))).toBe('1 B US$');
        expect(nb(formatCompact(3.414e12))).toBe('3,41 B');
        expect(nb(formatCompact(-3.4e12))).toBe('-3,4 B');
    });
    it('999.999.999.999 redondea a 1.000 mil M y sube a B', () => {
        expect(nb(formatCompact(999_999_999_999, { maximumFractionDigits: 0 }))).toBe('1 B');
    });
    it('por debajo de 1e12 conserva mil M', () => {
        expect(nb(formatCompact(9.447e11))).toBe('944,7 mil M');
    });
});
