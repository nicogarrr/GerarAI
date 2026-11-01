import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ locale: 'en' }));
vi.mock('next/headers', () => ({ cookies: async () => ({ get: () => ({ value: mocks.locale }) }) }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ replace: () => undefined }) }));

import { ThemeBrainButton } from '@/app/(root)/temas/_components/ThemeBrainButton';
import { ThemeFlow, ThemeFlowUnavailable } from '@/app/(root)/temas/_components/ThemeFlow';
import { ThemeFundamentals } from '@/app/(root)/temas/_components/ThemeFundamentals';
import { ThemeOrderToggle } from '@/app/(root)/temas/_components/ThemeOrderToggle';
import { LocaleProvider } from '@/lib/i18n/client';
import { formatFlowAmount, type MoneyFlow } from '@/lib/market/flows';

const source = { kind: 'reportado', label: '10-K', url: null, note: null };
const flow = {
    id: 'ia', name: 'AI', tagline: '', generated_at: '2026-10-01', period_label: null,
    spenders: [{ key: 'msft', label: 'Microsoft', ticker: 'MSFT', amount: 35.7e9, unit: 'USD', period_label: null, reason: null, source, note: null, extra_amount: null, extra_label: null, extra_source: null }],
    spenders_total: null,
    destinations: [{ label: 'GPUs', amount: 2e9, unit: 'USD', source: { ...source, kind: 'estimacion_terceros' } }],
    suppliers: [{ ticker: 'NVDA', name: 'NVIDIA', amount: null, unit: 'USD', reason: 'GPUs', note: null, source: null }],
    method: '', limitation: '', notes: [], destinations_note: null, suppliers_note: null,
} as unknown as MoneyFlow;
const holdings = { portfolio: new Set(['NVDA']), watchlist: new Set<string>(), unavailable: false };

describe('Temas: flujo de dinero, fundamentales y botones en inglés', () => {
    it('flujo de dinero en inglés con importes en formato inglés', async () => {
        mocks.locale = 'en';
        render(await ThemeFlow({ flow, holdings }));
        expect(screen.getByText('Who spends · reported')).toBeTruthy();
        expect(screen.getByText('$35.7B')).toBeTruthy();
        expect(screen.getByText(/third-party estimate/)).toBeTruthy();
        expect(screen.getByText('Who gets paid')).toBeTruthy();
        expect(screen.getByText(/in your portfolio/)).toBeTruthy();
    });

    it('en español no cambia', async () => {
        mocks.locale = 'es';
        render(await ThemeFlow({ flow, holdings }));
        expect(screen.getAllByText('Quién gasta · reportado').length).toBeGreaterThan(0);
        expect(screen.getAllByText(/35,7 mil M/).length).toBeGreaterThan(0);
        render(await ThemeFlowUnavailable());
        expect(screen.getByText(/Flujo de dinero N\/D/)).toBeTruthy();
    });

    it('flujo no entregado y fundamentales en inglés', async () => {
        mocks.locale = 'en';
        render(await ThemeFlowUnavailable());
        expect(screen.getByText(/Money flow N\/A/)).toBeTruthy();
        const fundamentals = await ThemeFundamentals({ themeId: 'nuclear' });
        expect(fundamentals).not.toBeNull();
        render(fundamentals!);
        expect(screen.getAllByText('Scope and limits').length).toBe(1);
        expect(screen.getAllByText(/cut-off/).length).toBeGreaterThan(0);
    });

    it('conmutador y botón del cerebro según idioma', () => {
        render(<LocaleProvider locale="en"><ThemeOrderToggle order="ytd" /><ThemeBrainButton question="q" /></LocaleProvider>);
        expect(screen.getByRole('group', { name: 'Sort themes by return' })).toBeTruthy();
        expect(screen.getByRole('button', { name: 'Analyse the theme' })).toBeTruthy();
    });

    it('formatFlowAmount: español por defecto, inglés corriente con en', () => {
        expect(formatFlowAmount(35.7e9, 'USD', 'N/A', 'en')).toBe('$35.7B');
        expect(formatFlowAmount(12_300_000, 'EUR', 'N/A', 'en')).toBe('12.3M EUR');
        expect(formatFlowAmount(null, 'USD', 'N/A', 'en')).toBe('N/A');
        expect(formatFlowAmount(35.7e9, 'USD').replace(/\u00a0/g, ' ')).toBe('35,7 mil M US$');
    });
});
