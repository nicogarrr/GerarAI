import React from 'react';
import { readFileSync } from 'node:fs';
import { act, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ refresh: vi.fn() }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ refresh: mocks.refresh }) }));

import { MarketThemesRefreshing } from '@/app/(root)/temas/_components/MarketThemesRefreshing';
import es from '@/lib/i18n/messages/es/themes.json';
import en from '@/lib/i18n/messages/en/themes.json';

describe('MarketThemesRefreshing', () => {
  afterEach(() => {
    vi.useRealTimers();
    mocks.refresh.mockReset();
  });

  it('dice «Preparando datos de mercado» y reconsulta cada 15 s sin ráfagas', () => {
    vi.useFakeTimers();
    render(<MarketThemesRefreshing />);

    expect(screen.getByRole('status')).toHaveTextContent('Preparando datos de mercado');
    expect(screen.getByRole('status')).toHaveTextContent('se actualizará sola');
    expect(mocks.refresh).not.toHaveBeenCalled();

    act(() => { vi.advanceTimersByTime(14_999); });
    expect(mocks.refresh).not.toHaveBeenCalled();
    act(() => { vi.advanceTimersByTime(1); });
    expect(mocks.refresh).toHaveBeenCalledTimes(1);
    act(() => { vi.advanceTimersByTime(15_000); });
    expect(mocks.refresh).toHaveBeenCalledTimes(2);
  });

  it('deja de reconsultar al desmontarse (cuando ya hay datos)', () => {
    vi.useFakeTimers();
    const view = render(<MarketThemesRefreshing />);
    view.unmount();
    act(() => { vi.advanceTimersByTime(45_000); });
    expect(mocks.refresh).not.toHaveBeenCalled();
  });

  it('solo sustituye el vacío cuando refreshing=true llega sin temas', () => {
    const page = readFileSync('app/(root)/temas/page.tsx', 'utf8');
    expect(page).toContain('if (data.refreshing === true && data.themes.length === 0)');
    expect(page).toContain('return <MarketThemesRefreshing />;');
    expect(es.page.preparingTitle).toBe('Preparando datos de mercado');
    expect(en.page.preparingTitle).toBe('Preparing market data');
  });
});
