import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { writeFileSync } from 'node:fs';
import { getResearchCompanySnapshot, getResearchThesisWorkspace } from '@/lib/actions/research.actions';
import { researchRequest } from '@/lib/research/client';
import ThesisReadingPage from '@/app/(root)/research/[ticker]/tesis/page';
vi.mock('@/lib/actions/research.actions', () => ({ getResearchCompanySnapshot: vi.fn(), getResearchThesisWorkspace: vi.fn() }));
vi.mock('@/lib/research/client', () => ({ researchRequest: vi.fn() }));
vi.mock('@/lib/public-fonts-editorial', () => ({ publicEditorial: { variable: '' } }));
vi.mock('@/components/research/PrintButton', () => ({ default: () => null }));
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
