import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { LocaleProvider } from '@/lib/i18n/client';
import { ThesisTrackRecordCard } from '@/components/research/ThesisTrackRecordCard';
import type { ThesisTrackRecord } from '@/lib/actions/thesis-track-record.actions';

const empty = { samples: 0, hits: 0, hit_rate: null, median_abs_error: null, median_signed_error: null, touched_rate: null };

const pending: ThesisTrackRecord = {
  ticker: 'TEST', status: 'pending', first_maturity_date: '2027-03-24', horizons: { '6M': empty, '12M': empty },
  best_horizon: null, best_horizon_reason: 'insufficient_samples', min_samples_best_horizon: 3, versions_tracked: 4, last_computed_at: null,
};

const ready: ThesisTrackRecord = {
  ...pending, status: 'ready', best_horizon: '12M', best_horizon_reason: 'hit_rate',
  horizons: {
    '6M': { samples: 5, hits: 3, hit_rate: 0.6, median_abs_error: 0.2, median_signed_error: 0.15, touched_rate: 0.4 },
    '12M': { samples: 4, hits: 3, hit_rate: 0.75, median_abs_error: 0.1, median_signed_error: -0.08, touched_rate: 0.5 },
  },
};

describe('«Nuestro acierto»', () => {
  it('pendiente: fecha del primer resultado (es)', () => {
    render(<LocaleProvider locale="es"><ThesisTrackRecordCard data={pending} /></LocaleProvider>);
    expect(screen.getByText('Nuestro acierto')).toBeInTheDocument();
    expect(screen.getByTestId('thesis-track-record-pending').textContent).toBe('Primer resultado el 24/03/2027.');
  });

  it('pendiente en inglés, sin castellano', () => {
    render(<LocaleProvider locale="en"><ThesisTrackRecordCard data={pending} /></LocaleProvider>);
    expect(screen.getByText('Our track record')).toBeInTheDocument();
    expect(screen.getByTestId('thesis-track-record-pending').textContent).toMatch(/^First result on 03\/24\/2027\.$/);
    expect(document.body.textContent).not.toMatch(/acierto|Primer|meses/);
  });

  it('con resultados: acierto, error, toque y mejor horizonte', () => {
    render(<LocaleProvider locale="es"><ThesisTrackRecordCard data={ready} /></LocaleProvider>);
    const h12 = screen.getByTestId('thesis-track-record-12M');
    expect(h12.textContent).toMatch(/75\s?%/);
    expect(h12.textContent).toContain('(3 de 4)');
    expect(h12.textContent).toContain('Mejor');
    expect(screen.getByTestId('thesis-track-record-6M').textContent).toMatch(/\+15\s?%/);
    expect(screen.getByTestId('thesis-track-record-best').textContent).toBe('Mejor horizonte para esta acción: A 12 meses, por acierto.');
  });

  it('pocas muestras: lo dice en vez de elegir horizonte', () => {
    render(<LocaleProvider locale="en"><ThesisTrackRecordCard data={{ ...ready, best_horizon: null, best_horizon_reason: 'insufficient_samples' }} /></LocaleProvider>);
    expect(screen.getByTestId('thesis-track-record-best').textContent).toBe('Not enough samples to pick a horizon (at least 3 per horizon).');
  });

  it('sin tesis con valor razonable no pinta nada', () => {
    const { container } = render(<LocaleProvider locale="es"><ThesisTrackRecordCard data={{ ...pending, status: 'no_data', first_maturity_date: null }} /></LocaleProvider>);
    expect(container.textContent).toBe('');
    const second = render(<LocaleProvider locale="es"><ThesisTrackRecordCard data={null} /></LocaleProvider>);
    expect(second.container.textContent).toBe('');
    // Una respuesta con otra forma (proxy o mock genérico) tampoco rompe la tesis.
    const third = render(<LocaleProvider locale="es"><ThesisTrackRecordCard data={{ ok: true } as unknown as ThesisTrackRecord} /></LocaleProvider>);
    expect(third.container.textContent).toBe('');
  });
});
