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
