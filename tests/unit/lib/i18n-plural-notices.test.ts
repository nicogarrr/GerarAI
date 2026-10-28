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

describe('knowledge graph: singular/plural con conteo', () => {
  it('search.results: 1 resultado usa singular y conserva la query', () => {
    const msg = t('knowledgeGraph.search.results.one', { count: 1, query: 'AAPL' });
    expect(msg).toBe('1 nodo coincide con «AAPL».');
  });

  it('search.results: varios resultados usan plural', () => {
    expect(t('knowledgeGraph.search.results.other', { count: 4, query: 'AAPL' })).toBe('4 nodos coinciden con «AAPL».');
  });

  it('canvas.isolatedOn: 1 vecino', () => {
    expect(t('knowledgeGraph.canvas.isolatedOn.one', { count: 1 })).toContain('su único vecino');
  });

  it('canvas.isolatedOn: varios vecinos', () => {
    expect(t('knowledgeGraph.canvas.isolatedOn.other', { count: 3 })).toContain('sus 3 vecinos');
  });

  it('listing.rowCount: 1 nodo vs varios', () => {
    expect(t('knowledgeGraph.listing.rowCount.one', { count: 1 })).toBe('1 nodo en el subgrafo visible.');
    expect(t('knowledgeGraph.listing.rowCount.other', { count: 7 })).toBe('7 nodos en el subgrafo visible.');
  });
});
