import { render, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import PortfolioNavChart from '@/components/portfolio/PortfolioNavChart';

beforeEach(() => {
    // jsdom no mide layout: el ResizeObserver informa de inmediato con tamaño fijo.
    vi.stubGlobal('ResizeObserver', class {
        private cb: ResizeObserverCallback;
        constructor(cb: ResizeObserverCallback) { this.cb = cb; }
        observe(target: Element) {
            this.cb([{ target, contentRect: { width: 320, height: 200 } } as ResizeObserverEntry], this as unknown as ResizeObserver);
        }
        unobserve() {}
        disconnect() {}
    });
});

const data = [
    { date: '2026-10-01', value: 100_000 },
    { date: '2026-10-02', value: 101_500 },
    { date: '2026-10-03', value: 99_800 },
];

describe('PortfolioNavChart', () => {
    it('renderiza el gráfico de área con los puntos del NAV', async () => {
        const { container } = render(<PortfolioNavChart data={data} positive currency="EUR" />);
        await waitFor(() => expect(container.querySelector('svg')).not.toBeNull());
    });
    it('en positivo el trazo es teal y en negativo rojo', async () => {
        const up = render(<PortfolioNavChart data={data} positive />);
        await waitFor(() => expect(up.container.querySelector('linearGradient stop')).toHaveAttribute('stop-color', '#14b8a6'));
        up.unmount();
        const down = render(<PortfolioNavChart data={data} positive={false} />);
        await waitFor(() => expect(down.container.querySelector('linearGradient stop')).toHaveAttribute('stop-color', '#ef4444'));
    });
});
