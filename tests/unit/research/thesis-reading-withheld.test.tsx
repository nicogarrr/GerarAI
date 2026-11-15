import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { writeFileSync } from 'node:fs';
import { getResearchCompanySnapshot, getResearchThesisWorkspace } from '@/lib/actions/research.actions';
import { researchRequest } from '@/lib/research/client';
import { AppError } from '@/lib/types/errors';
import ThesisReadingPage from '@/app/(root)/research/[ticker]/tesis/page';
vi.mock('next/headers', () => ({ cookies: async () => ({ get: () => undefined }) }));
vi.mock('@/lib/actions/research.actions', () => ({ getResearchCompanySnapshot: vi.fn(), getResearchThesisWorkspace: vi.fn() }));
vi.mock('@/lib/research/client', () => ({ researchRequest: vi.fn() }));
vi.mock('@/lib/public-fonts-editorial', () => ({ publicEditorial: { variable: '' } }));
vi.mock('@/components/research/PrintButton', () => ({ default: () => null }));
vi.mock('@/components/research/ThesisGenerateButton', () => ({ default: ({ label }: { label?: string }) => <button type="button">{label ?? 'Generar tesis'}</button> }));
const leaked = 'Margen -65,1% valor esperado 119,92';
const thesis = { id: 1, version: 11, status: 'published', rating: 'buy', created_at: '2026-10-19T06:54:00Z', executive_summary: leaked, hypothesis: leaked, narrative_sections: [{ titulo: leaked, parrafos: [leaked] }], catalysts: [{ label: leaked }], invalidation_criteria: [leaked], current_price: '343', bear_value: '50', base_value: '100', bull_value: '200', expected_value: '119.92', margin_of_safety: '-0.651' };
function setup(publishable: boolean | null, status = 'published') {
 vi.mocked(getResearchCompanySnapshot).mockResolvedValue({ company: { name: 'Fixture', currency: 'USD' }, model_summary: publishable === null ? null : { publishable, status: 'ok' } } as never);
 vi.mocked(getResearchThesisWorkspace).mockResolvedValue({ thesis: { ...thesis, status } } as never);
 vi.mocked(researchRequest).mockResolvedValue(status === 'published' ? [thesis] : []);
}
describe('printable thesis does not bypass current valuation gate', () => {
 it.each([false, null])('withholds archived published text if publishable is %j', async (publishable) => {
  setup(publishable);
  render(await ThesisReadingPage({ params: Promise.resolve({ ticker: 'AAPL' }) }));
  expect(screen.queryByText(/65,1/)).not.toBeInTheDocument();
  expect(screen.queryByText(/119,92/)).not.toBeInTheDocument();
  expect(screen.getByRole('note')).toHaveTextContent('v11');
  expect(screen.getByRole('note')).toHaveTextContent('19 oct 2026');
  expect(screen.queryByRole('link', { name: 'PDF' })).not.toBeInTheDocument();
  expect(screen.queryByRole('link', { name: 'Markdown' })).not.toBeInTheDocument();
 });
 it.each([false, null])('offers a way out of the archived dead end when publishable is %j', async (publishable) => {
  // Auditoría 29-oct-2026: /research/ASTS/tesis mostraba solo la nota de
  // archivo y «Sin valoración…», sin acción ni ruta a seguir.
  setup(publishable);
  render(await ThesisReadingPage({ params: Promise.resolve({ ticker: 'AAPL' }) }));
  expect(screen.getByRole('link', { name: 'Revisar la tesis en la ficha' })).toHaveAttribute('href', '/research/AAPL?view=thesis');
  expect(screen.getByRole('button', { name: 'Regenerar tesis' })).toBeInTheDocument();
 });
 it('withholds provisional free text even when the current model is publishable', async () => {
  setup(true, 'insufficient_data');
  render(await ThesisReadingPage({ params: Promise.resolve({ ticker: 'AAPL' }) }));
  expect(screen.queryByText(/65,1/)).not.toBeInTheDocument();
  expect(screen.getByRole('note')).toHaveTextContent('no está publicada');
 });
 it('keeps published source text when model is publishable', async () => {
  setup(true);
  render(await ThesisReadingPage({ params: Promise.resolve({ ticker: 'AAPL' }) }));
  expect(screen.getAllByText(leaked).length).toBeGreaterThan(0);
  expect(screen.getByRole('link', { name: 'PDF' })).toBeInTheDocument();
 });
});

it('optional exact page SSR fixture for visual inspection', async () => {
 if (process.env.READING_VISUAL_OUT) { setup(false); writeFileSync(process.env.READING_VISUAL_OUT, renderToStaticMarkup(await ThesisReadingPage({ params: Promise.resolve({ ticker: 'AAPL' }) }))); }
});


it.each(['published', 'superseded', 'insufficient_data'])('keeps the isolated ASTS appendix visible for archived %s text', async (status) => {
 setup(false, status);
 const page = await ThesisReadingPage({ params: Promise.resolve({ ticker: 'ASTS' }) });
 if (process.env.ASTS_READING_VISUAL_OUT && status === 'superseded') writeFileSync(process.env.ASTS_READING_VISUAL_OUT, renderToStaticMarkup(page));
 render(page);
 expect(screen.getByTestId('asts-bank-supplement')).toBeInTheDocument();
 expect(screen.getAllByRole('note').some(note => note.textContent?.includes('v11'))).toBe(true);
 expect(screen.queryByText(/65,1/)).not.toBeInTheDocument();
 expect(screen.queryByText(/119,92/)).not.toBeInTheDocument();
 expect(screen.queryByRole('link', { name: 'PDF' })).not.toBeInTheDocument();
 expect(screen.getByRole('button', { name: 'Regenerar tesis' })).toBeInTheDocument();
});


it('does not show the ASTS appendix when the company is missing even with a stored archive', async () => {
 setup(false, 'superseded');
 vi.mocked(getResearchCompanySnapshot).mockResolvedValue(null);
 vi.mocked(researchRequest).mockRejectedValue(new AppError('Company not found', 'RESEARCH_API_ERROR', 404));
 render(await ThesisReadingPage({ params: Promise.resolve({ ticker: 'ASTS' }) }));
 expect(screen.queryByTestId('asts-bank-supplement')).not.toBeInTheDocument();
 expect(screen.queryByText(/65,1/)).not.toBeInTheDocument();
});
