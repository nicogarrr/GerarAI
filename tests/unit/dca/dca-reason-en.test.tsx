import { readFileSync } from 'node:fs';
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import DcaHitRatesCard from '@/components/watchlist/DcaHitRatesCard';
import { dcaReasonText } from '@/lib/dca/reason-text';
import type { DcaHitRates } from '@/lib/dca/types';

// Motivos en castellano que manda el backend cuando no hay señal/backtest DCA
// (watchlist.py, dca_backtest.py, dca_signal_engine.py). Si cambian allí, este
// test avisa de que la tabla en inglés se ha quedado atrás.
const BACKEND: Array<[string, string]> = [
  ['data-engine/app/api/routes/watchlist.py', 'Preparando la señal DCA: se está evaluando en segundo plano'],
  ['data-engine/app/api/routes/watchlist.py', 'Aún sin histórico calculado: se rellena en la próxima evaluación'],
  ['data-engine/app/api/routes/watchlist.py', 'Sin histórico de precios para este ticker'],
  ['data-engine/app/services/dca_backtest.py', 'Historia insuficiente en ese rango: hacen falta al menos 2 meses con veredicto confirmado y compra.'],
  ['data-engine/app/services/dca_signal_engine.py', 'sin meses confirmados'],
];

describe('DCA reasons from the backend in English', () => {
  it('the backend still sends these sentences and each has an English version', () => {
    for (const [file, text] of BACKEND) {
      expect(readFileSync(file, 'utf8'), `${file}: ${text}`).toContain(`"${text}"`);
      const en = dcaReasonText(text, 'en');
      expect(en, text).not.toBe(text);
      expect(en).not.toMatch(/[áéíóúñ]|\b(sin|para|meses|histórico)\b/i);
      expect(dcaReasonText(text, 'es')).toBe(text);
    }
    expect(dcaReasonText('Motivo nuevo', 'en')).toBe('Motivo nuevo');
    expect(dcaReasonText(null, 'en')).toBeNull();
  });

  it('the hit-rates card shows the backend reason in English', () => {
    const data = { available: false, reason: 'Aún sin histórico calculado: se rellena en la próxima evaluación' } as unknown as DcaHitRates;
    const { rerender } = render(<DcaHitRatesCard data={data} locale="en" />);
    expect(screen.getByText('No history computed yet: it is filled in at the next evaluation')).toBeVisible();
    rerender(<DcaHitRatesCard data={data} />);
    expect(screen.getByText('Aún sin histórico calculado: se rellena en la próxima evaluación')).toBeVisible();
  });

  it('the backtest panel routes its reason through the translator', () => {
    const panel = readFileSync('components/proPicks/DcaBacktestPanel.tsx', 'utf8');
    expect(panel).toContain('dcaReasonText(result.reason, locale)');
  });
});
