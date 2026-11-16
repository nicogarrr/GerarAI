import React from 'react';
import { act, cleanup, render } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const refresh = vi.fn();
vi.mock('@/lib/actions/preparing-status.actions', () => ({getPreparingStatus: vi.fn().mockResolvedValue('preparing')}));
vi.mock('next/navigation', () => ({ useRouter: () => ({ refresh }) }));
import DcaPreparingRefresh from '@/components/research/DcaPreparingRefresh';

describe('DcaPreparingRefresh compartido', () => {
  beforeEach(() => { vi.useFakeTimers(); refresh.mockClear(); });
  afterEach(() => { cleanup(); vi.useRealTimers(); });

  it('dos tarjetas preparando no provocan refrescos de pagina', () => {
    render(<><DcaPreparingRefresh ticker="ASTS" kind="dca" /><DcaPreparingRefresh ticker="ASTS" kind="dca" /></>);
    act(() => { vi.advanceTimersByTime(15_000); });
    expect(refresh).not.toHaveBeenCalled();
    act(() => { vi.advanceTimersByTime(15_000 * 40); });
    expect(refresh).not.toHaveBeenCalled();
  });

  it('montar y desmontar tarjetas nunca reinicia un presupuesto de refrescos', () => {
    const one = render(<DcaPreparingRefresh ticker="ASTS" kind="dca" />);
    const two = render(<DcaPreparingRefresh ticker="ASTS" kind="dca" />);
    one.unmount();
    act(() => { vi.advanceTimersByTime(15_000); });
    expect(refresh).not.toHaveBeenCalled();
    two.unmount();
    act(() => { vi.advanceTimersByTime(60_000); });
    expect(refresh).not.toHaveBeenCalled();
  });
});
