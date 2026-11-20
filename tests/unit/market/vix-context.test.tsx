import { render, screen, cleanup } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { VixContextCard } from '@/components/market/VixContextCard';
import type { VixContext } from '@/lib/actions/market-regime.actions';
afterEach(cleanup);
describe('VIX context, synthetic fixtures only', () => {
  it.each(['es', 'en'] as const)('renders every reference band without provider labels in %s', locale => {
    for (const band of ['low', 'middle', 'high'] as const) {
      render(<VixContextCard locale={locale} context={{status:'available', band, value:31, date:'2026-11-19', source_url:'https://fred.stlouisfed.org/series/VIXCLS'}} />);
      expect(screen.getByText(/31[,.]00/)).toBeInTheDocument();
      expect(screen.getByText(/2026-11-19/)).toBeInTheDocument();
      expect(screen.queryByRole('link')).not.toBeInTheDocument();
      expect(screen.queryByText(/FRED|Cboe/)).not.toBeInTheDocument();
      expect(screen.getByText(locale==='es' ? /Sin backtest/ : /No return backtest/)).toBeInTheDocument();
      expect(screen.queryByRole('button')).not.toBeInTheDocument();
      cleanup();
    }
  });
  it.each([undefined, {status:'unavailable', value:99, reason:'stale'}, {status:'available', band:'high', value:NaN}, {status:'available', band:'high', value:0}, {status:'available', band:'unknown', value:31}, {status:'available', band:'high', value:31, date:'2026-11-19', source_url:'https://evil.invalid'}, {status:'available', band:'high', value:31, source_url:'https://fred.stlouisfed.org/series/VIXCLS'}] as (VixContext | undefined)[])('does not show stale or invalid context as a signal %o', context => {
    render(<VixContextCard locale="es" context={context} />);
    expect(screen.getByText('VIX sin lectura vigente')).toBeInTheDocument();
    expect(screen.getByText(/Sin contexto:/)).toBeInTheDocument();
    expect(screen.queryByText(/99[,.]00/)).not.toBeInTheDocument();
  });
});
