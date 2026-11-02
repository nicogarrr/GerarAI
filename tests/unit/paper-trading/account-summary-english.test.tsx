import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { AccountSummary } from '@/components/paper-trading/AccountSummary';
import { LedgerTable } from '@/components/paper-trading/LedgerTable';
import type { DemoStateView, HistoryRow } from '@/components/paper-trading/submit';
import { LocaleProvider } from '@/lib/i18n/client';

const account = {
  cashEUR: 100_000,
  cashUSD: 0,
  realizedEUR: 0,
  realizedUSD: 0,
  version: 1,
  positions: [],
  violations: ['venta ord-2 (EUR|SAN): pedida x10, posición x4; orden rechazada entera, sin movimiento'],
  notices: ['Cuenta demo manual: el dinero es ficticio y no toca tu broker real.'],
} as unknown as DemoStateView;

const rejected: HistoryRow = {
  clientOrderId: 'ord-rejected-1',
  kind: 'accion',
  symbol: 'AAPL',
  name: 'Apple',
  side: 'sell',
  openClose: 'close',
  quantity: 5,
  status: 'rejected',
  fillPrice: null,
  currency: 'USD',
  fee: 0,
  executedAt: Date.UTC(2026, 9, 20),
  rejectReason: 'No puedes vender 5 acciones de AAPL: la posición en USD es 2.',
  createdAt: Date.UTC(2026, 9, 20),
  simulated: true,
} as unknown as HistoryRow;

describe('demo account in English', () => {
  it('shows the fixed notices and integrity warnings in English', () => {
    render(<LocaleProvider locale="en"><AccountSummary account={account} /></LocaleProvider>);
    expect(screen.getByText('Manual demo account: the money is fictitious and does not touch your real broker.')).toBeVisible();
    expect(screen.getByText('sell ord-2 (EUR|SAN): requested x10, position x4; whole order rejected, nothing moved')).toBeVisible();
    expect(screen.queryByText(/dinero es ficticio/)).not.toBeInTheDocument();
  });

  it('keeps them in Spanish in Spanish mode', () => {
    render(<LocaleProvider locale="es"><AccountSummary account={account} /></LocaleProvider>);
    expect(screen.getByText('Cuenta demo manual: el dinero es ficticio y no toca tu broker real.')).toBeVisible();
  });

  it('shows the reason of a rejected order in English', () => {
    render(<LocaleProvider locale="en"><LedgerTable entries={[rejected]} /></LocaleProvider>);
    expect(screen.getByText(/You cannot sell 5 shares of AAPL: the USD position is 2\./)).toBeVisible();
    expect(screen.queryByText(/No puedes vender/)).not.toBeInTheDocument();
  });
});
