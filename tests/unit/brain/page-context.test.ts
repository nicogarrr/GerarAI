import { describe, expect, it } from 'vitest';
import { brainPageContext } from '@/lib/brain/page-context';

/**
 * Auditoría v1.0 (2026-10-27): el cerebro rotulaba las rutas propias de
 * /research (news, sources, assistant) como si fueran tickers ("NEWS",
 * "SOURCES", "ASSISTANT") y pedía al catálogo la ficha de esa "empresa".
 * Y el índice /research y /settings quedaban sin contexto (pastilla vacía).
 */
describe('brainPageContext', () => {
  it('las rutas propias de /research no son tickers', () => {
    for (const [path, label] of [
      ['/research/news', 'Noticias'],
      ['/research/sources', 'Fuentes'],
      ['/research/assistant', 'Asistente'],
    ] as const) {
      const context = brainPageContext(path);
      expect(context?.label, path).toBe(label);
      expect(context?.ticker, path).toBeNull();
    }
  });

  it('el índice /research y /settings tienen contexto de sección', () => {
    expect(brainPageContext('/research')).toEqual({ path: '/research', label: 'Research', ticker: null });
    expect(brainPageContext('/settings')).toEqual({ path: '/settings', label: 'Ajustes', ticker: null });
  });

  it('una ficha real sigue resolviendo su ticker', () => {
    expect(brainPageContext('/research/ASTS')).toEqual({ path: '/research/ASTS', label: 'ASTS', ticker: 'ASTS' });
    expect(brainPageContext('/research/CGEO.L/filings')?.ticker).toBe('CGEO.L');
    expect(brainPageContext('/stocks/BRK.B')?.ticker).toBe('BRK.B');
  });

  it('el resto de secciones no cambia', () => {
    expect(brainPageContext('/inicio')?.label).toBe('Inicio');
    expect(brainPageContext('/taxes')?.label).toBe('Impuestos');
    expect(brainPageContext(null)).toBeNull();
  });
});

describe('brainPageContext i18n', () => {
  it('las etiquetas de sección se resuelven en inglés con locale en', () => {
    expect(brainPageContext('/inicio', 'en')?.label).toBe('Home');
    expect(brainPageContext('/portfolio', 'en')?.label).toBe('Portfolio');
    expect(brainPageContext('/watchlist', 'en')?.label).toBe('Watchlist');
    expect(brainPageContext('/knowledge', 'en')?.label).toBe('Library');
    expect(brainPageContext('/inversores', 'en')?.label).toBe('Investors');
    expect(brainPageContext('/temas', 'en')?.label).toBe('Themes');
    expect(brainPageContext('/propicks', 'en')?.label).toBe('ProPicks');
    expect(brainPageContext('/calendar', 'en')?.label).toBe('Calendar');
    expect(brainPageContext('/macro-calendar', 'en')?.label).toBe('Macro calendar');
    expect(brainPageContext('/screener', 'en')?.label).toBe('Screener');
    expect(brainPageContext('/discover', 'en')?.label).toBe('Discover');
    expect(brainPageContext('/cuellos', 'en')?.label).toBe('Bottlenecks');
    expect(brainPageContext('/alerts', 'en')?.label).toBe('Alerts');
    expect(brainPageContext('/plan', 'en')?.label).toBe('Plan');
    expect(brainPageContext('/risk', 'en')?.label).toBe('Risk');
    expect(brainPageContext('/taxes', 'en')?.label).toBe('Taxes');
    expect(brainPageContext('/security', 'en')?.label).toBe('Security');
    expect(brainPageContext('/research', 'en')?.label).toBe('Research');
    expect(brainPageContext('/settings', 'en')?.label).toBe('Settings');
  });

  it('las rutas reservadas de /research se resuelven en inglés', () => {
    expect(brainPageContext('/research/news', 'en')?.label).toBe('News');
    expect(brainPageContext('/research/sources', 'en')?.label).toBe('Sources');
    expect(brainPageContext('/research/assistant', 'en')?.label).toBe('Assistant');
  });

  it('los tickers no se traducen y ES sigue siendo el locale por defecto', () => {
    expect(brainPageContext('/research/ASTS', 'en')).toEqual({ path: '/research/ASTS', label: 'ASTS', ticker: 'ASTS' });
    expect(brainPageContext('/stocks/BRK.B', 'en')?.label).toBe('BRK.B');
    expect(brainPageContext('/inicio')?.label).toBe('Inicio');
    expect(brainPageContext('/research/news')?.label).toBe('Noticias');
  });
});
