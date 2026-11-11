import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { WhatToBelieveView } from '@/components/research/WhatToBelieveView';
import { LocaleProvider } from '@/lib/i18n/client';
import type { WhatToBelieve } from '@/lib/research/what-to-believe';

// r5-tesis2 (pistas de la auditoría fa-tesis):
// 1) «Con salida a 25x» salía aunque el backend no mandara el múltiplo (`?? 25`):
//    una cifra inventada. Sin múltiplo → N/D con su motivo.
// 2) «No aplica» en holdings, aseguradoras, REIT o preingresos no decía qué método
//    se usa en su lugar, aunque el motor ya llega en `engine`.
const base = {
  ticker: 'POOL', status: 'ok', reason_code: null, reason: null, engine: 'standard_dcf', currency: 'USD',
  current_price: 211.7, base_value: 137.51, wacc_used: 0.1, terminal_growth: 0.03,
  implied_wacc_price: null, implied_wacc_consensus: null, consensus_price: null, consensus_source: null,
  implied_growth: null,
  exit_multiple: { value_per_share: 180.25, gordon_value_per_share: 137.51, multiple: 18, implied_multiple_for_price: 21.4 },
} as unknown as WhatToBelieve;

const es = (ui: React.ReactNode) => render(<LocaleProvider locale="es">{ui}</LocaleProvider>);
const en = (ui: React.ReactNode) => render(<LocaleProvider locale="en">{ui}</LocaleProvider>);
const withExit = (patch: Record<string, unknown>) => ({ ...base, exit_multiple: { ...(base.exit_multiple as object), ...patch } }) as unknown as WhatToBelieve;
const na = (engine: string | null, reason_code = 'engine_not_dcf') =>
  ({ ticker: 'X', status: 'not_applicable', reason_code, reason: null, engine } as unknown as WhatToBelieve);

describe('WhatToBelieveView · múltiplo de salida', () => {
  it('con múltiplo: lo usa tal cual (18x, no 25x)', () => {
    es(<WhatToBelieveView data={base} />);
    expect(screen.getByTestId('what-to-believe-exit-label')).toHaveTextContent('Con salida a 18x');
    expect(screen.getByTestId('what-to-believe-exit-explain')).toHaveTextContent('18 veces');
  });

  it.each([['sin campo', { multiple: undefined }], ['nulo', { multiple: null }], ['cero', { multiple: 0 }]])(
    'múltiplo %s: N/D con motivo, nunca 25x', (_n, patch) => {
      es(<WhatToBelieveView data={withExit(patch)} />);
      const label = screen.getByTestId('what-to-believe-exit-label');
      expect(label).toHaveTextContent('N/D');
      expect(label).not.toHaveTextContent('25');
      const explain = screen.getByTestId('what-to-believe-exit-explain');
      expect(explain).toHaveTextContent('no indicó qué múltiplo usó');
      expect(explain).not.toHaveTextContent('25 veces');
      // El valor que sí llegó se sigue mostrando.
      expect(screen.getByTestId('what-to-believe-exit')).toHaveTextContent('180,25');
    });

  it('en inglés también N/A', () => {
    en(<WhatToBelieveView data={withExit({ multiple: null })} />);
    expect(screen.getByTestId('what-to-believe-exit-label')).toHaveTextContent('N/A');
  });
});

describe('WhatToBelieveView · «No aplica» dice qué método se usa', () => {
  it.each([
    ['holding_company', 'valor liquidativo (NAV)'],
    ['insurer', 'aseguradora'],
    ['reit', 'cap rate'],
    ['pre_revenue', 'sin ingresos'],
    ['bank', 'banco'],
  ])('%s', (engine, text) => {
    es(<WhatToBelieveView data={na(engine)} />);
    expect(screen.getByTestId('what-to-believe-na')).toHaveTextContent('No aplica');
    expect(screen.getByTestId('what-to-believe-method')).toHaveTextContent(`Esta empresa se valora por`);
    expect(screen.getByTestId('what-to-believe-method')).toHaveTextContent(text);
  });

  it('también cuando no hay valoración calculada pero el motor se conoce', () => {
    es(<WhatToBelieveView data={na('holding_company', 'valuation_unavailable')} />);
    expect(screen.getByTestId('what-to-believe-method')).toHaveTextContent('NAV');
  });

  it.each([[null], ['standard_dcf'], ['motor_desconocido']])('motor %s: sin frase de método ni clave cruda', (engine) => {
    es(<WhatToBelieveView data={na(engine as string | null, 'valuation_unavailable')} />);
    expect(screen.queryByTestId('what-to-believe-method')).not.toBeInTheDocument();
    expect(screen.getByTestId('what-to-believe-na')).not.toHaveTextContent('motor_desconocido');
  });

  it('en inglés', () => {
    en(<WhatToBelieveView data={na('insurer')} />);
    expect(screen.getByTestId('what-to-believe-method')).toHaveTextContent('This company is valued with price/book');
  });
});
