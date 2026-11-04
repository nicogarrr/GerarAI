import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { AnalystHistorySkeleton, AnalystHistoryView } from '@/components/research/AnalystHistoryView';
import { LocaleProvider } from '@/lib/i18n/client';
import type { AnalystHistory } from '@/lib/research/analyst-history';

const firm = (name: string, rel: number, samples = 8) => ({
  firm: name, samples, median_abs_error_pct: 30, median_bias_pct: -10, direction_hit_rate: 0.75,
  relative_error: rel, peer_scored_samples: samples, small_sample: false, last_date: '2026-10-01', last_target: 200,
});

const available = {
  symbol: 'PLTR', status: 'available', source: 'Yahoo Finance (no oficial)', source_url: null, fetched_at: 1793120400,
  currency: 'USD', as_of: '2026-11-03', first_target_date: '2020-10-26', targets_total: 240, best_horizon: '6m', min_samples: 5,
  horizons: [
    { horizon: '6m', months: 6, matured_targets: 202, median_abs_error_pct: 45.9, median_bias_pct: -30, direction_hit_rate: 0.5,
      ranked_firms: 16, small_sample_firms: 13, top: [firm('Wedbush', -9.2)], bottom: [firm('RBC Capital', 45.2)] },
    { horizon: '12m', months: 12, matured_targets: 167, median_abs_error_pct: 56.9, median_bias_pct: -43, direction_hit_rate: 0.52,
      ranked_firms: 14, small_sample_firms: 10, top: [firm('Raymond James', -7.9)], bottom: [firm('Goldman Sachs', 12.7)] },
  ],
  consensus: { method: 'simple_mean', mean: 223.68, median: 234, firms: 22, reference_price: 175.4, upside_percent: 27.5 },
  rating_changes: { window_days: 90, upgrades: 1, downgrades: 0 },
  note: null, note_code: null,
} as AnalystHistory;

const es = (ui: React.ReactNode) => render(<LocaleProvider locale="es">{ui}</LocaleProvider>);
const en = (ui: React.ReactNode) => render(<LocaleProvider locale="en">{ui}</LocaleProvider>);

describe('AnalystHistoryView', () => {
  it('opens on the best horizon, says which, and lists top/bottom firms with the simple consensus', () => {
    es(<AnalystHistoryView data={available} />);
    expect(screen.getByText('Historial de analistas')).toBeInTheDocument();
    expect(screen.getByTestId('analyst-history-best')).toHaveTextContent('Mejor horizonte para este valor: 6 meses');
    expect(screen.getByRole('button', { name: /6 meses/ })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByTestId('analyst-history-top')).toHaveTextContent('Wedbush');
    expect(screen.getByTestId('analyst-history-bottom')).toHaveTextContent('RBC Capital');
    expect(screen.getByTestId('analyst-history-small-sample')).toHaveTextContent('13 firmas');
    expect(screen.getByTestId('analyst-history-consensus')).toHaveTextContent('Consenso simple');
    expect(screen.queryByText(/inteligente|ponderado/i)).not.toBeInTheDocument();
    expect(screen.getByTestId('analyst-history-rating-note')).toHaveTextContent('No es una señal validada');
    fireEvent.click(screen.getByRole('button', { name: /12 meses/ }));
    expect(screen.getByTestId('analyst-history-top')).toHaveTextContent('Raymond James');
    expect(screen.getByTestId('analyst-history-bottom')).toHaveTextContent('Goldman Sachs');
  });

  it('renders in English with no Spanish left', () => {
    en(<AnalystHistoryView data={available} />);
    expect(screen.getByText('Analyst track record')).toBeInTheDocument();
    expect(screen.getByTestId('analyst-history-best')).toHaveTextContent('Best horizon for this stock: 6 months');
    expect(screen.getByText('Most accurate')).toBeInTheDocument();
    expect(screen.getByTestId('analyst-history-consensus')).toHaveTextContent('Simple consensus');
    expect(screen.queryByText(/Historial|Consenso|meses|firmas|Mejor/)).not.toBeInTheDocument();
  });

  it('sin datos, not-a-stock, unavailable and no-ranked states', () => {
    const { unmount } = es(<AnalystHistoryView data={{ ...available, status: 'empty', horizons: [], consensus: null, note_code: 'no_history' }} />);
    expect(screen.getByTestId('analyst-history-empty')).toHaveTextContent(/^Sin datos/);
    unmount();
    const r2 = en(<AnalystHistoryView data={{ ...available, status: 'empty', horizons: [], consensus: null, note_code: 'not_equity' }} />);
    expect(screen.getByTestId('analyst-history-empty')).toHaveTextContent("isn't a stock");
    r2.unmount();
    const r3 = es(<AnalystHistoryView data={null} />);
    expect(screen.getByRole('status')).toHaveTextContent('No se pudo consultar');
    r3.unmount();
    const thin = {
      ...available, best_horizon: null,
      horizons: available.horizons.map((h) => ({ ...h, ranked_firms: 0, top: [], bottom: [] })),
    } as AnalystHistory;
    es(<AnalystHistoryView data={thin} />);
    expect(screen.getByTestId('analyst-history-no-ranked')).toHaveTextContent('muestra pequeña');
    expect(screen.getByTestId('analyst-history-best')).toHaveTextContent('Aún no hay muestra suficiente');
  });

  it('loading skeleton announces itself', () => {
    es(<AnalystHistorySkeleton />);
    expect(screen.getByTestId('analyst-history-loading')).toHaveAttribute('aria-busy', 'true');
    expect(screen.getByRole('status')).toHaveTextContent('Calculando');
  });
});
