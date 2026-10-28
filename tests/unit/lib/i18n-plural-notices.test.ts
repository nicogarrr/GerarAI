/**
 * Avisos de cartera con conteo {n}: la concordancia singular/plural debe
 * ser correcta en es-ES. Regresión: "excluyen 2 saldo o posición" (singular
 * con conteo plural) y su simétrico "excluyen 1 saldos o posiciones".
 */
import { describe, expect, it } from 'vitest';

import { t } from '@/lib/i18n/t';

describe('avisos de cartera con conteo: singular/plural', () => {
  it('fxMissingNotice: n=1 usa singular', () => {
    const msg = t('portfolio.fxMissingNotice.one', { n: 1 });
    expect(msg).toContain('1 saldo o posición');
    expect(msg).not.toContain('saldos o posiciones');
  });

  it('fxMissingNotice: n>1 interpola y usa plural', () => {
    const msg = t('portfolio.fxMissingNotice.other', { n: 2 });
    expect(msg).toContain('excluyen 2 saldos o posiciones');
    expect(msg).not.toContain('{n}');
  });

  it('valuationHoldNotice: n=1 usa singular y conserva tickers', () => {
    const msg = t('portfolio.valuationHoldNotice.one', { n: 1, tickers: 'AAPL' });
    expect(msg).toContain('excluyen 1 posición');
    expect(msg).toContain('(AAPL)');
    expect(msg).not.toContain('posiciones con valoración');
  });

  it('valuationHoldNotice: n>1 interpola n y tickers en plural', () => {
    const msg = t('portfolio.valuationHoldNotice.other', { n: 3, tickers: 'AAPL, MSFT, NVDA' });
    expect(msg).toContain('excluyen 3 posiciones');
    expect(msg).toContain('(AAPL, MSFT, NVDA)');
    expect(msg).not.toContain('{n}');
    expect(msg).not.toContain('{tickers}');
  });
});
