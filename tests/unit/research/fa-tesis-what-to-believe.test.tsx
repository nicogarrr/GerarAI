import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { WhatToBelieveView } from '@/components/research/WhatToBelieveView';
import { LocaleProvider } from '@/lib/i18n/client';
import type { WhatToBelieve } from '@/lib/research/what-to-believe';

// Auditoría fa-tesis (r5): la tarjeta «Qué hace falta creer» solo hablaba de
// WACC; la conclusión (valor DCF base frente al precio) no salía en ella.
// Cifras de las respuestas reales de /what-to-believe en local (POOL, UNH).
const pool = {
  ticker: 'POOL', status: 'ok', reason_code: null, reason: null, engine: 'standard_dcf', currency: 'USD',
  current_price: 211.699997, base_value: 137.51388364228077, wacc_used: 0.1, terminal_growth: 0.03,
  implied_wacc_price: { status: 'ok', target_price: 211.699997, wacc: 0.07892, direction: null, bounds: [0.0325, 0.25] },
  implied_wacc_consensus: null, consensus_price: null, consensus_source: null,
  implied_growth: { status: 'ok', required_revenue_growth: 0.0799, current_revenue_growth: -0.004059, method: 'reverse_dcf_stage1_growth' },
  exit_multiple: null,
} as WhatToBelieve;
const unh = { ...pool, ticker: 'UNH', current_price: 394.149994, base_value: 769.637341357258, wacc_used: 0.06656515 } as WhatToBelieve;

const es = (ui: React.ReactNode) => render(<LocaleProvider locale="es">{ui}</LocaleProvider>);
const en = (ui: React.ReactNode) => render(<LocaleProvider locale="en">{ui}</LocaleProvider>);

describe('WhatToBelieveView · conclusión primero', () => {
  it('precio por encima del DCF base: lo dice con el valor y la brecha, antes de los WACC', () => {
    es(<WhatToBelieveView data={pool} />);
    const verdict = screen.getByTestId('what-to-believe-verdict');
    expect(verdict).toHaveTextContent('Nuestro DCF base da 137,51');
    expect(verdict).toHaveTextContent('211,70');
    expect(verdict).toHaveTextContent('53,9 % por encima');
    // Va antes que la frase del WACC implícito.
    const wacc = screen.getByTestId('what-to-believe-wacc');
    expect(verdict.compareDocumentPosition(wacc) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('precio por debajo del DCF base', () => {
    es(<WhatToBelieveView data={unh} />);
    expect(screen.getByTestId('what-to-believe-verdict')).toHaveTextContent('48,8 % por debajo');
  });

  it('dentro de ±0,5 % dice «en línea» sin porcentaje', () => {
    es(<WhatToBelieveView data={{ ...pool, current_price: 137.9 } as WhatToBelieve} />);
    const verdict = screen.getByTestId('what-to-believe-verdict');
    expect(verdict).toHaveTextContent('en línea con el precio de hoy');
    expect(verdict).not.toHaveTextContent('%');
  });

  it.each([
    ['sin valor base', { base_value: null }],
    ['valor base negativo', { base_value: -3 }],
    ['sin precio', { current_price: null }],
  ])('%s: no hay frase (nunca una cifra inventada)', (_name, patch) => {
    es(<WhatToBelieveView data={{ ...pool, ...patch } as WhatToBelieve} />);
    expect(screen.queryByTestId('what-to-believe-verdict')).not.toBeInTheDocument();
  });

  it('no aplica: tampoco hay frase', () => {
    es(<WhatToBelieveView data={{ ticker: 'BN', status: 'not_applicable', reason_code: 'valuation_unavailable', base_value: 10, current_price: 20 } as WhatToBelieve} />);
    expect(screen.queryByTestId('what-to-believe-verdict')).not.toBeInTheDocument();
  });

  it('en inglés', () => {
    en(<WhatToBelieveView data={pool} />);
    expect(screen.getByTestId('what-to-believe-verdict')).toHaveTextContent("Our base DCF gives $137.51 per share: today's price ($211.70) is 53.9% above it.");
  });
});
