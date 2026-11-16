import React from 'react';
import { act, render } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const refresh = vi.fn();
vi.mock('@/lib/actions/preparing-status.actions', () => ({getPreparingStatus: vi.fn().mockResolvedValue('preparing')}));
vi.mock('next/navigation', () => ({ useRouter: () => ({ refresh }) }));
import DcaPreparingRefresh from '@/components/research/DcaPreparingRefresh';

describe('DcaPreparingRefresh', () => {
  beforeEach(() => { vi.useFakeTimers(); refresh.mockClear(); });
  afterEach(() => { vi.useRealTimers(); });

  it('no refresca toda la ficha mientras una tarjeta se prepara', () => {
    render(<DcaPreparingRefresh ticker="ASTS" kind="dca" />);
    act(() => { vi.advanceTimersByTime(15_000); });
    expect(refresh).not.toHaveBeenCalled();
    act(() => { vi.advanceTimersByTime(15_000 * 40); });
    expect(refresh).not.toHaveBeenCalled();
  });

  it('al desmontarse deja de refrescar', () => {
    const { unmount } = render(<DcaPreparingRefresh ticker="ASTS" kind="dca" />);
    unmount();
    act(() => { vi.advanceTimersByTime(60_000); });
    expect(refresh).not.toHaveBeenCalled();
  });
});
