import { readFileSync } from 'node:fs';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
vi.mock('@/lib/actions/paper-trading.actions', () => ({ feedPaperProposalsNow: vi.fn(), getPaperTrading: vi.fn() }));
import { PaperTradingContent } from '@/components/proPicks/PaperTradingView';
import { CompanyPaperTrades } from '@/components/research/CompanyPaperTrades';

// Errores REALES que devuelven las acciones de servidor (lib/actions/paper-trading.actions.ts),
// siempre en castellano: la pantalla los pintaba tal cual también con English elegido.
const ACTIONS = readFileSync('lib/actions/paper-trading.actions.ts', 'utf8');
const ERRORS = [...ACTIONS.matchAll(/error: '([^']+)'/g)].map((m) => m[1]);
const BOOK_ERROR = ERRORS.find((e) => e.includes('cartera')) ?? '';
const COMPANY_ERROR = ERRORS.find((e) => e.includes('operaciones')) ?? '';

describe('operaciones simuladas: error de carga en el idioma elegido', () => {
  it('los errores de prueba son los de las acciones', () => {
    expect(BOOK_ERROR).toBe('No se pudo cargar la cartera simulada.');
    expect(COMPANY_ERROR).toBe('No se pudieron cargar las operaciones simuladas.');
  });
  it('ProPicks › simuladas en inglés', () => {
    const html = renderToStaticMarkup(<PaperTradingContent data={{ trades: [], score: { groups: [] }, error: BOOK_ERROR } as never} locale="en" />);
    expect(html).toContain("Couldn&#x27;t load the paper portfolio.");
    expect(html).not.toContain(BOOK_ERROR);
  });
  it('ficha › operaciones simuladas en inglés', () => {
    const html = renderToStaticMarkup(<CompanyPaperTrades ticker="AAPL" state={{ trades: [], error: COMPANY_ERROR }} locale="en" />);
    expect(html).not.toContain(COMPANY_ERROR);
    expect(html).not.toMatch(/[áéíóúñ]|No se pud/);
  });
  it('en castellano, la misma frase de siempre', () => {
    expect(renderToStaticMarkup(<PaperTradingContent data={{ trades: [], score: { groups: [] }, error: BOOK_ERROR } as never} />)).toContain(BOOK_ERROR);
    expect(renderToStaticMarkup(<CompanyPaperTrades ticker="AAPL" state={{ trades: [], error: COMPANY_ERROR }} />)).toContain(COMPANY_ERROR);
  });
});
