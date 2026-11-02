import React from 'react';
import { act, cleanup, render } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const refresh = vi.fn();
vi.mock('next/navigation', () => ({ useRouter: () => ({ refresh }) }));
import DcaPreparingRefresh from '@/components/research/DcaPreparingRefresh';

describe('DcaPreparingRefresh compartido', () => {
  beforeEach(() => { vi.useFakeTimers(); refresh.mockClear(); });
  afterEach(() => { cleanup(); vi.useRealTimers(); });

  it('dos tarjetas preparando a la vez: un solo refresco cada 15 s, mismo tope de 5 min', () => {
    render(<><DcaPreparingRefresh /><DcaPreparingRefresh /></>);
    act(() => { vi.advanceTimersByTime(15_000); });
    expect(refresh).toHaveBeenCalledTimes(1);
    act(() => { vi.advanceTimersByTime(15_000 * 40); });
    expect(refresh).toHaveBeenCalledTimes(20);
  });

  it('si una tarjeta termina, la otra sigue refrescando; sin ninguna, para', () => {
    const one = render(<DcaPreparingRefresh />);
    const two = render(<DcaPreparingRefresh />);
    one.unmount();
    act(() => { vi.advanceTimersByTime(15_000); });
    expect(refresh).toHaveBeenCalledTimes(1);
    two.unmount();
    act(() => { vi.advanceTimersByTime(60_000); });
    expect(refresh).toHaveBeenCalledTimes(1);
  });
});
