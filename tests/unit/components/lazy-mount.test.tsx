import { act } from 'react';
import { render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';

import LazyMount from '@/components/ui/lazy-mount';

// LazyMount: montaje diferido al viewport para los gráficos recharts de
// /portfolio (346 KB decodificados en la carga inicial pese a dynamic
// ssr:false, medido 18-nov-2026). Comportamiento exigido:
//  - reserva la caja desde el primer render (CLS 0),
//  - no monta los hijos hasta que el observer dice que asoma,
//  - lo montado no se desmonta nunca,
//  - sin IntersectionObserver monta de inmediato (degradar es mostrar).

type IOEntry = { isIntersecting: boolean };
let ioCallback: ((entries: IOEntry[]) => void) | null;
let ioDisconnected: boolean;
let ioOptions: { rootMargin?: string } | undefined;

beforeEach(() => {
    ioCallback = null;
    ioDisconnected = false;
    ioOptions = undefined;
    vi.stubGlobal('IntersectionObserver', class {
        constructor(cb: (entries: IOEntry[]) => void, options?: { rootMargin?: string }) {
            ioCallback = cb;
            ioOptions = options;
        }
        observe() {}
        disconnect() { ioDisconnected = true; }
    });
});

afterEach(() => { vi.unstubAllGlobals(); });

const children = <div data-testid="grafico-pesado" />;
const fallback = <div data-testid="esqueleto" role="status" />;

describe('LazyMount: comportamiento', () => {
    it('reserva la caja con el esqueleto y no monta los hijos al primer render', () => {
        const { container } = render(<LazyMount className="h-full" fallback={fallback}>{children}</LazyMount>);
        expect(screen.getByTestId('esqueleto')).toBeTruthy();
        expect(screen.queryByTestId('grafico-pesado')).toBeNull();
        // La caja existe desde ya con su clase: el sitio queda reservado.
        expect(container.firstChild).toMatchObject({ className: 'h-full' });
    });

    it('no monta mientras el observer no ve la caja', () => {
        render(<LazyMount fallback={fallback}>{children}</LazyMount>);
        act(() => { ioCallback?.([{ isIntersecting: false }]); });
        expect(screen.queryByTestId('grafico-pesado')).toBeNull();
        expect(screen.getByTestId('esqueleto')).toBeTruthy();
    });

    it('monta al asomar al viewport y desconecta el observer', () => {
        render(<LazyMount fallback={fallback}>{children}</LazyMount>);
        act(() => { ioCallback?.([{ isIntersecting: true }]); });
        expect(screen.getByTestId('grafico-pesado')).toBeTruthy();
        expect(screen.queryByTestId('esqueleto')).toBeNull();
        expect(ioDisconnected).toBe(true);
    });

    it('lo montado no se desmonta aunque la caja deje de verse', () => {
        render(<LazyMount fallback={fallback}>{children}</LazyMount>);
        act(() => { ioCallback?.([{ isIntersecting: true }]); });
        act(() => { ioCallback?.([{ isIntersecting: false }]); });
        expect(screen.getByTestId('grafico-pesado')).toBeTruthy();
    });

    it('observa sin margen por defecto: monta al asomar 1px', () => {
        render(<LazyMount>{children}</LazyMount>);
        expect(ioOptions?.rootMargin ?? '0px').toBe('0px');
    });

    it('sin IntersectionObserver monta en el próximo frame', async () => {
        vi.stubGlobal('IntersectionObserver', undefined);
        render(<LazyMount fallback={fallback}>{children}</LazyMount>);
        // Primer render: esqueleto (sin setState síncrono en el efecto).
        expect(screen.queryByTestId('grafico-pesado')).toBeNull();
        expect(await screen.findByTestId('grafico-pesado')).toBeTruthy();
    });
});

describe('LazyMount: cableado de los gráficos de /portfolio', () => {
    it('el gráfico NAV de la pestaña Resumen va envuelto en LazyMount', () => {
        const s = readFileSync('components/portfolio/PortfolioTabs.tsx', 'utf8');
        const nav = s.indexOf('<PortfolioNavChart');
        const lazy = s.lastIndexOf('<LazyMount', nav);
        expect(nav, 'no se encuentra PortfolioNavChart').toBeGreaterThan(-1);
        expect(lazy, 'PortfolioNavChart sin LazyMount').toBeGreaterThan(-1);
        expect(s.slice(lazy, nav)).toContain('fallback={<NavChartLoading />}');
    });

    it('el donut de distribución va envuelto en LazyMount', () => {
        const s = readFileSync('components/portfolio/PortfolioAllocation.tsx', 'utf8');
        const donut = s.indexOf('<PortfolioAllocationChart');
        const lazy = s.lastIndexOf('<LazyMount', donut);
        expect(donut, 'no se encuentra PortfolioAllocationChart').toBeGreaterThan(-1);
        expect(lazy, 'PortfolioAllocationChart sin LazyMount').toBeGreaterThan(-1);
    });

    it('los dos gráficos siguen siendo dynamic(ssr:false): no vuelven al bundle inicial', () => {
        const tabs = readFileSync('components/portfolio/PortfolioTabs.tsx', 'utf8');
        const alloc = readFileSync('components/portfolio/PortfolioAllocation.tsx', 'utf8');
        expect(tabs).toMatch(/dynamic\(\(\) => import\('\.\/PortfolioNavChart'\),\s*\{\s*ssr: false/);
        expect(alloc).toMatch(/dynamic\(\(\) => import\('\.\/PortfolioAllocationChart'\),\s*\{\s*ssr: false/);
    });
});
