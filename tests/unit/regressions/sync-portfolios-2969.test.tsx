import React from 'react';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
const sync = vi.hoisted(() => vi.fn());
vi.mock('@/lib/actions/investors.actions', () => ({syncInvestorPortfoliosNow: sync}));
import { SyncPortfoliosButton } from '@/app/(root)/inversores/_components/SyncPortfoliosButton';
beforeEach(() => { localStorage.clear(); sync.mockReset(); });
afterEach(cleanup);
describe('#2969 sync persists timestamp only after success', () => {
  it.each(['failure','rejection'] as const)('%s leaves no timestamp and allows another attempt', async kind => {
    if (kind === 'failure') sync.mockResolvedValue({success:false});
    else sync.mockRejectedValue(new Error('offline'));
    render(<SyncPortfoliosButton />);
    await waitFor(() => expect(screen.getByText(/No se pudo encolar/)).toBeTruthy());
    expect(localStorage.getItem('sync-13f-last-auto')).toBeNull();
    expect(screen.getByRole('button').hasAttribute('disabled')).toBe(false);
  });
  it('success records timestamp and prevents immediate duplicate', async () => {
    sync.mockResolvedValue({success:true});
    const view = render(<SyncPortfoliosButton />);
    await waitFor(() => expect(localStorage.getItem('sync-13f-last-auto')).not.toBeNull());
    view.unmount();
    render(<SyncPortfoliosButton />);
    await new Promise(resolve => setTimeout(resolve, 0));
    expect(sync).toHaveBeenCalledTimes(1);
  });
});
