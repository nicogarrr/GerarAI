import React from 'react';
import { act, render } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const refresh = vi.fn();
vi.mock('next/navigation', () => ({ useRouter: () => ({ refresh }) }));
import DcaPreparingRefresh from '@/components/research/DcaPreparingRefresh';

describe('DcaPreparingRefresh', () => {
  beforeEach(() => { vi.useFakeTimers(); refresh.mockClear(); });
  afterEach(() => { vi.useRealTimers(); });

  it('refresca la ficha cada 15 s y para tras 20 intentos (5 min)', () => {
    render(<DcaPreparingRefresh />);
    act(() => { vi.advanceTimersByTime(15_000); });
    expect(refresh).toHaveBeenCalledTimes(1);
    act(() => { vi.advanceTimersByTime(15_000 * 40); });
    expect(refresh).toHaveBeenCalledTimes(20);
  });

  it('al desmontarse deja de refrescar', () => {
    const { unmount } = render(<DcaPreparingRefresh />);
    unmount();
    act(() => { vi.advanceTimersByTime(60_000); });
    expect(refresh).not.toHaveBeenCalled();
  });
});
