import { readFileSync } from 'node:fs';
import { describe, it, expect, vi } from 'vitest';
import { render } from '@testing-library/react';
import type { ReactElement } from 'react';

const src = (p: string) => readFileSync(p, 'utf8');

// Captura el fallback de carga que PortfolioAllocation pasa a next/dynamic:
// mockeado como stub no se renderiza nunca y quedaba sin cobertura.
const dyn = vi.hoisted(() => ({
    loading: null as null | (() => ReactElement),
    loader: null as null | (() => Promise<unknown>),
}));
vi.mock('next/dynamic', () => ({
    default: (loader: unknown, opts?: { loading?: () => ReactElement }) => {
        dyn.loader = loader as () => Promise<unknown>;
        dyn.loading = opts?.loading ?? null;
        return () => null;
    },
}));

import PortfolioAllocation from '@/components/portfolio/PortfolioAllocation';

// eslint-disable-next-line @typescript-eslint/no-explicit-any -- fixture parcial: el componente solo lee symbol/value/flags
const holding = (symbol: string, value: number): any => ({
    symbol, value, cost: value, gain: 0, gainPercent: 0, valueMissing: false, fxMissing: false,
});

// FAB del cerebro sobre la leyenda del donut en /portfolio desktop
// (medido 17-nov-2026, 1280x800): en horizontal el % terminaba en x=1231 y
// el botón ocupa la franja x>=1200 al hacer scroll. En esa tarjeta (428px
// útiles) donut 250 + gap 24 + leyenda mínima 160 = 434px: no cabe la
// franja de 80px, así que la leyenda va apilada a ancho completo con
// md:pr-24 (% medido después: x=1127, 73px de holgura).
describe('donut /portfolio: la leyenda no queda bajo el cerebro flotante', () => {
    it('guard: leyenda apilada a ancho completo con reserva para la franja del FAB', () => {
        const a = src('components/portfolio/PortfolioAllocation.tsx');
        expect(a).toContain('flex-1 flex flex-col items-center justify-center gap-6');
        expect(a).not.toContain('sm:flex-row sm:justify-between');
        expect(a).toContain('sm:max-h-none sm:overflow-visible md:pr-24');
        expect(a).not.toContain('sm:w-auto sm:min-w-[160px]');
        // La franja del botón sigue siendo de 80px (right-6 + w-14) desde md.
        const fab = src('components/brain/GlobalBrain.tsx');
        expect(fab).toContain('right-[calc(1.5rem+env(safe-area-inset-right))]');
        expect(fab).toContain('h-14 w-14');
    });

    it('la leyenda lleva la reserva al DOM y pinta símbolos y porcentajes', () => {
        const { container } = render(<PortfolioAllocation holdings={[holding('AAA', 300), holding('BBB', 100)]} />);
        const legend = container.querySelector('#portfolio-allocation-legend')!;
        expect(legend.className).toContain('w-full');
        expect(legend.className).toContain('md:pr-24');
        expect(legend.textContent).toContain('AAA');
        expect(legend.textContent).toContain('75,0');
    });

    it('el dynamic del donut carga el chart real', async () => {
        render(<PortfolioAllocation holdings={[holding('AAA', 300)]} />);
        expect(dyn.loader).not.toBeNull();
        const mod = (await dyn.loader!()) as { default?: unknown };
        expect(mod.default).toBeTruthy();
    });

    it('el placeholder de carga del donut conserva su caja heredada', () => {
        render(<PortfolioAllocation holdings={[holding('AAA', 300)]} />);
        expect(dyn.loading).not.toBeNull();
        const Loading = dyn.loading!;
        const { container } = render(<Loading />);
        const pulse = container.querySelector('[role="status"]');
        expect(pulse?.className).toContain('h-full w-full animate-pulse rounded-full');
    });

    it('la fila de caja del donut usa etiqueta, no enlace a research', () => {
        const { container } = render(<PortfolioAllocation holdings={[holding('AAA', 300)]} cash={120} />);
        const legend = container.querySelector('#portfolio-allocation-legend')!;
        expect(legend.querySelector('a')).not.toBeNull();
        expect(legend.textContent).toContain('AAA');
    });
});
