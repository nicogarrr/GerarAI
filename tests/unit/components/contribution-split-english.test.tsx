import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';

import ContributionSplitCard from '@/components/plan/ContributionSplitCard';
import { LocaleProvider } from '@/lib/i18n/client';
import { splitNoteText, splitReasonText } from '@/lib/plan/split-text';
import type { ContributionAllocation, ContributionSplit } from '@/lib/plan/contribution-split';

// Textos tal cual los manda plan_contribution_split.py.
const row = (over: Partial<ContributionAllocation>): ContributionAllocation => ({
  ticker: 'POOL', amount: 100, share_pct: 50, base_weight: 1, dca_level: 2, dca_label: '2X DCA', dca_period: '2026-10',
  dca_status: 'ok', dca_stale: false, multiplier: 2, reason: '2X DCA: peso ×2', ...over,
});

describe('contribution split in English', () => {
  it('reasons per row', () => {
    expect(splitReasonText(row({}), 'en')).toBe('2X DCA: weight ×2');
    expect(splitReasonText(row({ dca_level: -2, dca_label: 'RECORTE FUERTE', multiplier: 0, reason: 'RECORTE FUERTE: zona de recorte, este mes no recibe aportación' }), 'en'))
      .toBe('HEAVY TRIM: trim zone, no contribution this month');
    expect(splitReasonText(row({ dca_level: null, dca_label: null, multiplier: 1, reason: 'sin nivel DCA: peso normal (1X)' }), 'en')).toBe('no DCA level: normal weight (1X)');
    expect(splitReasonText(row({ dca_level: null, dca_stale: true, multiplier: 1, dca_period: '2026-07', reason: 'nivel DCA caducado (mes 2026-07): peso normal (1X) hasta reevaluar' }), 'en'))
      .toBe('stale DCA level (month 2026-07): normal weight (1X) until re-evaluated');
    expect(splitReasonText(row({}), 'es')).toBe('2X DCA: peso ×2');
  });

  it('notes', () => {
    const notes: Array<[string, string]> = [
      ['El plan no tiene objetivos por ticker: se reparte a partes iguales entre las posiciones vivas.', 'The plan has no per-ticker targets: the contribution is split equally across open positions.'],
      ['El motor DCA no está desplegado todavía: el reparto sigue solo los pesos del plan (todos como 1X).', 'The DCA engine is not deployed yet: the split follows only the plan weights (all as 1X).'],
      ['Nivel DCA de hace más de un mes en POOL, UBER: pesa como 1X hasta que se vuelva a evaluar.', 'DCA level older than a month for POOL, UBER: weighted as 1X until re-evaluated.'],
      ['Ningún ticker del plan tiene nivel DCA calculado: todos pesan como 1X.', 'No ticker in the plan has a computed DCA level: all weigh as 1X.'],
      ['La divisa de la aportación no está registrada en el plan.', 'The contribution currency is not recorded in the plan.'],
    ];
    for (const [es, en] of notes) {
      expect(splitNoteText(es, 'en')).toBe(en);
      expect(splitNoteText(es, 'es')).toBe(es);
    }
    expect(splitNoteText('Nota nueva', 'en')).toBe('Nota nueva');
  });

  it('the card reads in English', () => {
    const split: ContributionSplit = {
      plan_exists: true, status: 'ok', amount: 300, currency: 'EUR', basis: 'objetivos_ticker', dca_available: true,
      summary: 'Este mes 200,00 EUR a POOL, 100,00 EUR a UBER',
      notes: ['La divisa de la aportación no está registrada en el plan.'],
      allocations: [row({ amount: 200 }), row({ ticker: 'UBER', dca_level: 1, dca_label: '1X DCA', multiplier: 1, reason: '1X DCA: peso ×1' })],
      unallocated: 0,
    };
    render(<LocaleProvider locale="en"><ContributionSplitCard split={split} /></LocaleProvider>);
    expect(screen.getByText(/^This month 200\.00 EUR to POOL, 100\.00 EUR to UBER$/)).toBeInTheDocument();
    expect(screen.getByText('1X DCA: weight ×1')).toBeInTheDocument();
    expect(screen.queryByText(/Este mes|peso|divisa/)).not.toBeInTheDocument();
  });

  it('all-trim summary in English', () => {
    const split: ContributionSplit = { plan_exists: true, status: 'all_trim', amount: 300, currency: 'EUR', allocations: [row({ amount: 0, multiplier: 0, dca_level: -1, dca_label: 'RECORTE LIGERO', reason: 'RECORTE LIGERO: zona de recorte, este mes no recibe aportación' })],
      summary: 'Este mes todo el plan está en zona de recorte: los 300,00 EUR quedan en liquidez.' };
    render(<LocaleProvider locale="en"><ContributionSplitCard split={split} /></LocaleProvider>);
    expect(screen.getByText('This month the whole plan is in the trim zone: the 300.00 EUR stay in cash.')).toBeInTheDocument();
    expect(screen.getByText('LIGHT TRIM: trim zone, no contribution this month')).toBeInTheDocument();
  });
});
