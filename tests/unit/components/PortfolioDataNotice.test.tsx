import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import PortfolioDataNotice from '@/components/portfolio/PortfolioDataNotice';
import type { PortfolioDataQuality } from '@/lib/actions/portfolio.actions';
const quality: PortfolioDataQuality = {
 status: 'incomplete', positions: 7, missing_cost_positions: 0,
 position_dates: ['2026-10-29'], cash_dates: ['2026-10-28'],
 position_sources: ['ibkr_flex'], cash_sources: ['ibkr_flex'], cash_native: {EUR: 0.57, USD: -9954.44},
 snapshots: 20, complete_snapshots: 1, return_observations: 0,
 latest_snapshot_date: '2026-10-29', latest_pricing_coverage: 1,
 reasons: ['mixed_valuation_dates', 'ibkr_cost_mismatch'],
};
describe('PortfolioDataNotice', () => {
 it('keeps dates in closed audit details without a mixed-date warning', () => {
  render(<PortfolioDataNotice quality={quality} />);
  const dates=screen.getByText(/Datos de cartera: posiciones a/);
  const details=dates.closest('details');
  expect(details).not.toBeNull();
  expect(details).not.toHaveAttribute('open');
  expect(dates).toHaveTextContent('29 oct 2026');
  expect(dates).toHaveTextContent('28 oct 2026');
  expect(screen.queryByText(/Posiciones y caja tienen fechas distintas/)).not.toBeInTheDocument();
  expect(screen.queryByText(/Yahoo|FX|foto conciliada del mismo día/)).not.toBeInTheDocument();
  expect(screen.getByText(/La cobertura de precios no acredita/)).toBeInTheDocument();
 });
 it('preserves actionable missing-cost warning without inventing returns', () => {
  render(<PortfolioDataNotice quality={{...quality,missing_cost_positions:1}} />);
  expect(screen.getByText(/Falta una base de coste válida/)).toHaveTextContent('1 posición');
 });
});
