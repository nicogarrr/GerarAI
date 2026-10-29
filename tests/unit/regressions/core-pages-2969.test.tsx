import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  actions: vi.fn(), status: vi.fn(), calendar: vi.fn(), materials: vi.fn(),
  signals: vi.fn(), filings: vi.fn(), feed: vi.fn(), operations: vi.fn(),
}));
vi.mock('@/lib/actions/corporate-actions.actions', () => ({ getCorporateActions: mocks.actions, getCorporateActionsSyncStatus: mocks.status }));
vi.mock('@/lib/actions/catalysts.actions', () => ({ getFollowedEarnings: mocks.calendar }));
vi.mock('@/lib/actions/earnings-materials.actions', () => ({ getEarningsMaterials: mocks.materials }));
vi.mock('@/lib/actions/insider.actions', () => ({ getInsiderSignals: mocks.signals, getInsiderFilings: mocks.filings, getInsiderFeed: mocks.feed, getInsiderOperations: mocks.operations }));
vi.mock('@/lib/backend-offline', () => ({ isBackendUnavailableError: (e: unknown) => e instanceof Error && e.message === 'offline' }));
vi.mock('@/components/system/BackendOffline', () => ({ default: ({retryHref}: {retryHref: string}) => <a href={retryHref}>Backend offline</a> }));
vi.mock('@/components/corporate-actions/CorporateActionsView', () => ({ default: ({emptyMessage}: {emptyMessage?: string}) => <p>{emptyMessage}</p> }));
vi.mock('@/components/insider/InsiderFeed', () => ({ default: () => <p>Feed available</p> }));
vi.mock('@/components/insider/InsiderOperationsView', () => ({ default: () => <p>Operations available</p> }));
vi.mock('@/components/insider/InsiderSignalsView', () => ({ default: () => null }));
import CorporatePage from '@/app/(root)/corporate-actions/page';
import CalendarPage from '@/app/(root)/calendar/resultados/page';
import InsiderPage from '@/app/(root)/insider/page';

beforeEach(() => {
  vi.clearAllMocks();
  mocks.actions.mockResolvedValue([{ ticker: 'AAPL' }]);
  mocks.status.mockRejectedValue(new Error('sync unavailable'));
  mocks.materials.mockResolvedValue({});
});
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });

describe('#2969 corporate actions regression', () => {
  it('counts filtered ticker and tolerates sync-status failure', async () => {
    const html = renderToStaticMarkup(await CorporatePage({ searchParams: Promise.resolve({ticker: ' msft '}) }));
    expect(mocks.status).toHaveBeenCalledTimes(1);
    expect(html).toContain('0 eventos');
    expect(html).toContain('Sin eventos pendientes de MSFT.');
  });
  it('does not request sync status when visible actions exist', async () => {
    const html = renderToStaticMarkup(await CorporatePage({ searchParams: Promise.resolve({ticker: 'AAPL'}) }));
    expect(mocks.status).not.toHaveBeenCalled();
    expect(html).toContain('1 eventos');
  });
});

it('#2969 calendar uses one Madrid date across an awaited midnight', async () => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date('2026-10-29T22:59:59Z'));
  const formatter = vi.spyOn(Intl, 'DateTimeFormat');
  mocks.calendar.mockImplementation(async () => {
    vi.setSystemTime(new Date('2026-10-29T23:00:01Z'));
    return {followed_count: 1, days: [], without_date_in_range: []};
  });
  await CalendarPage();
  expect(formatter).toHaveBeenCalledTimes(1);
  expect(formatter).toHaveBeenCalledWith('en-CA', {timeZone: 'Europe/Madrid'});
  expect(mocks.calendar).toHaveBeenCalledWith(expect.objectContaining({hasta: '2026-12-28'}));
});

describe('#2969 insider outages', () => {
  it('both sections offline retain filters in retry URL', async () => {
    mocks.feed.mockRejectedValue(new Error('offline'));
    mocks.operations.mockRejectedValue(new Error('offline'));
    const html = renderToStaticMarkup(await InsiderPage({searchParams: Promise.resolve({lado:'sell',dias:'365'})}));
    expect(html).toContain('/insider?lado=sell&amp;dias=365');
    expect(html).toContain('Backend offline');
  });
  it('ticker outage preserves ticker and filters', async () => {
    mocks.signals.mockRejectedValue(new Error('offline'));
    mocks.filings.mockResolvedValue(null);
    const html = renderToStaticMarkup(await InsiderPage({searchParams: Promise.resolve({ticker:' asts ',lado:'buy',dias:'30'})}));
    expect(html).toContain('/insider?ticker=ASTS&amp;lado=buy&amp;dias=30');
  });
  it('a single failed section does not replace the whole page', async () => {
    mocks.feed.mockRejectedValue(new Error('offline'));
    mocks.operations.mockResolvedValue({});
    const html = renderToStaticMarkup(await InsiderPage({searchParams: Promise.resolve({})}));
    expect(html).not.toContain('Backend offline');
    expect(html).toContain('Operations available');
  });
});
