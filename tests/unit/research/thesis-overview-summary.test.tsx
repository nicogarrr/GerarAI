import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { ThesisSummary } from '@/components/research/ThesisSummary';
const thesis = { status: 'published', version: 11, created_at: '2026-10-19T06:54:00Z', executive_summary: 'Margen -65,1% valor esperado 119,92' };
describe('overview latest thesis summary', () => {
 it.each([false, null])('withholds prose when publishability is %j', (publishable) => {
  render(<ThesisSummary thesis={thesis} model={publishable === null ? null : { publishable }} />);
  expect(screen.queryByText(/65,1/)).not.toBeInTheDocument();
  expect(screen.getByRole('note')).toHaveTextContent('v11');
  expect(screen.getByRole('note')).toHaveTextContent('19 oct 2026');
 });
 it('preserves usable source text', () => {
  render(<ThesisSummary thesis={thesis} model={{ publishable: true }} />);
  expect(screen.getByText(thesis.executive_summary)).toBeInTheDocument();
 });
 it('does not expose unpublished text against a publishable model', () => {
  render(<ThesisSummary thesis={{ ...thesis, status: 'draft' }} model={{ publishable: true }} />);
  expect(screen.queryByText(/65,1/)).not.toBeInTheDocument();
 });
});
