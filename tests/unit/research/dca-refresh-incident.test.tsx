import React from 'react';
import { act, cleanup, render } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
const refresh = vi.fn();
vi.mock('@/lib/actions/preparing-status.actions', () => ({getPreparingStatus: vi.fn().mockResolvedValue('preparing')}));
vi.mock('next/navigation', () => ({ useRouter: () => ({ refresh }) }));
import DcaPreparingRefresh from '@/components/research/DcaPreparingRefresh';
afterEach(() => { cleanup(); vi.useRealTimers(); refresh.mockClear(); });
it('preparing widgets never re-render the entire research page, even after remount', () => {
    vi.useFakeTimers();
    const first = render(<DcaPreparingRefresh ticker="ASTS" kind="dca" />);
    act(() => { vi.advanceTimersByTime(300_000); });
    first.unmount();
    render(<><DcaPreparingRefresh ticker="ASTS" kind="dca" /><DcaPreparingRefresh ticker="ASTS" kind="dca" /></>);
    act(() => { vi.advanceTimersByTime(300_000); });
    expect(refresh).not.toHaveBeenCalled();
});
