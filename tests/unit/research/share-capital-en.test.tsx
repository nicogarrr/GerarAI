import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ShareCapitalPanel } from '@/components/research/ShareCapitalPanel';
import { LocaleProvider } from '@/lib/i18n/client';

beforeEach(() => {
    vi.stubGlobal('matchMedia', () => ({ matches: false, addEventListener() {}, removeEventListener() {} }));
});

const fact = (date: string, value: number, over: Record<string, unknown> = {}) => ({
    value, unit: 'shares', date, fact_id: 1, source: 'SEC 10-Q', source_url: 'https://sec.gov/a', reported_on: null, source_updated_on: null,
    status: 'OFICIAL', concept: null, previous_date: null, net_change: null, net_change_pct: null, change_status: 'SIN_DATOS', split_between_dates: false, ...over,
});
const capital = (over: Record<string, unknown> = {}) => ({ ticker: 'X', status: 'OFICIAL', as_of: '2026-10-01', share_basis: 'reported_unadjusted', series: [], annual_flows: [], ...over }) as never;

describe('ShareCapitalPanel · formato por idioma', () => {
    it('en inglés: porcentaje con punto decimal y N/A', () => {
        const down = { series: [fact('2025-06-30', 100), fact('2026-06-30', 95, { previous_date: '2025-06-30', net_change_pct: -5.5, change_status: 'DERIVADO' })] };
        render(<LocaleProvider locale="en"><ShareCapitalPanel data={capital(down)} /></LocaleProvider>);
        expect(screen.getAllByText('-5.50%').length).toBeGreaterThan(0);
        expect(screen.queryByText('-5,50%')).toBeNull();
    });
    it('en inglés sin saldos no pinta «N/D»', () => {
        render(<LocaleProvider locale="en"><ShareCapitalPanel data={capital()} /></LocaleProvider>);
        expect(screen.queryByText('N/D')).toBeNull();
    });
});
