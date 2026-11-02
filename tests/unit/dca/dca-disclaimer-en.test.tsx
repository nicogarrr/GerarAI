import { readFileSync } from 'node:fs';
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import DcaHitRatesCard from '@/components/watchlist/DcaHitRatesCard';
import { dcaReasonText } from '@/lib/dca/reason-text';
import type { DcaHitRates } from '@/lib/dca/types';

// watchlist.py manda la salvedad de los aciertos y del backtest DCA siempre en
// castellano (valor por defecto del modelo de respuesta).
const DISCLAIMER = 'Histórico, hipotético. No es asesoramiento.';

describe('DCA disclaimer in English', () => {
  it('the backend still sends it in Spanish and it has an English version', () => {
    expect(readFileSync('data-engine/app/api/routes/watchlist.py', 'utf8').split(`disclaimer: str = "${DISCLAIMER}"`)).toHaveLength(3);
    expect(dcaReasonText(DISCLAIMER, 'en')).toBe('Historical, hypothetical. Not advice.');
    expect(dcaReasonText(DISCLAIMER, 'es')).toBe(DISCLAIMER);
  });

  it('the hit-rates card and the backtest panel show it in the chosen language', () => {
    const data: DcaHitRates = { symbol: 'TEST', available: true, reason: null, months_completed: 12, first_period: '2025-01', last_period: '2025-12', horizons: [1], params_version: 'v1', evaluated_at: null, disclaimer: DISCLAIMER,
      rows: [{ key: '2x', label: '2X', levels: [2], color: '#FFFFFF', signal_months: 4, cells: [{ horizon_months: 1, months: 4, pct_higher: 0.75, avg_return: 0.1 }] }] } as DcaHitRates;
    const { container } = render(<DcaHitRatesCard data={data} locale="en" />);
    expect(container.textContent).toContain('Historical, hypothetical. Not advice.');
    expect(container.textContent).not.toContain('asesoramiento');
    expect(screen.getByTestId('dca-hit-rates')).toBeTruthy();
    const panel = readFileSync('components/proPicks/DcaBacktestPanel.tsx', 'utf8');
    expect(panel).toContain('dcaReasonText(result.disclaimer, locale)');
  });
});
