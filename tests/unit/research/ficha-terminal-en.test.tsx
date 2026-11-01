import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/actions/research.actions', () => ({ refreshCompanyFinancialsSEC: vi.fn() }));
vi.mock('@/components/forms/MutationForm', () => ({ MutationForm: ({ children, successMessage }: { children: React.ReactNode; successMessage: string }) => <form data-success={successMessage}>{children}</form> }));

import { FinancialTerminalSection, type FinancialTerminalData } from '@/components/research/sections/FinancialTerminalSection';
import { CompanyPaperTrades } from '@/components/research/CompanyPaperTrades';
import { SectionLoadError } from '@/components/research/sections/SectionLoadError';
import { ShareCapitalSection } from '@/components/research/sections/ShareCapitalSection';
import { financialDefinition, financialSegment } from '@/lib/research/financial-display';
import { formatProvenanceValue } from '@/lib/research/provenance-format';

const terminal = {
    coverage: { percent: 50, available: 1, requested: 2 },
    periodicity: 'annual',
    metrics: [
        {
            metric: 'revenue', status: 'available', definition: 'Reported consolidated or segment revenue.', canonical_formula: null, periods: 1, segments: ['consolidated'], missing_reason: null,
            series: [{ id: 1, period: '2025-12-31:FY', value: 70918000, unit: 'USD', status: 'reported', segment: 'consolidated', confidence: 0.9, source: { title: '10-K', type: 'sec' } }],
        },
        { metric: 'fcf', status: 'unavailable', definition: 'Operating cash flow less capital expenditure.', canonical_formula: null, periods: 0, segments: [], missing_reason: null, series: [] },
    ],
} as unknown as FinancialTerminalData;

describe('ficha en inglés: terminal financiero, dilución y avisos de carga', () => {
    it('el terminal financiero sale en inglés con English picked', () => {
        render(<FinancialTerminalSection locale="en" periodicity="annual" terminal={terminal} years={10} />);
        expect(screen.getByText('Coverage')).toBeInTheDocument();
        expect(screen.getByText('Fiscal years loaded')).toBeInTheDocument();
        expect(screen.getByRole('heading', { name: 'Terminal controls' })).toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'Apply' })).toBeInTheDocument();
        expect(screen.getByText('1 period')).toBeInTheDocument();
        expect(screen.getByText('Reported consolidated or segment revenue.')).toBeInTheDocument();
        expect(screen.getByRole('columnheader', { name: 'Confidence' })).toBeInTheDocument();
        expect(screen.getByText('$70.92M')).toBeInTheDocument();
        expect(screen.getAllByText('Consolidated').length).toBeGreaterThan(0);
        expect(screen.getByText('No observations for this metric and period filter.')).toBeInTheDocument();
        expect(document.body.textContent).not.toMatch(/Cobertura|Aplicar|periodo|Sin observaciones|Consolidado/);
    });

    it('en español el terminal se ve igual que antes', () => {
        render(<FinancialTerminalSection periodicity="annual" terminal={terminal} years={10} />);
        expect(screen.getByText('Cobertura')).toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'Aplicar' })).toBeInTheDocument();
        expect(screen.getByText('1 periodo')).toBeInTheDocument();
        expect(document.body.textContent).toContain('70,92 M\u00a0US$');
        expect(screen.getByText('Ingresos publicados, consolidados o por segmento.')).toBeInTheDocument();
    });

    it('dilución y recompras vacía y aviso de sección caída en inglés', () => {
        render(<><ShareCapitalSection data={null} locale="en" ticker="AAPL" /><SectionLoadError locale="en" retryHref="/research/AAPL#noticias" title="News" /></>);
        expect(screen.getByRole('button', { name: 'Refresh SEC data' })).toBeInTheDocument();
        expect(screen.getByRole('status')).toHaveTextContent('No dilution or buyback data loaded yet');
        expect(screen.getByText("Couldn't load News.")).toBeInTheDocument();
        expect(screen.getByRole('link', { name: 'Retry' })).toHaveAttribute('href', '/research/AAPL#noticias');
    });

    it('en español los avisos no cambian', () => {
        render(<><ShareCapitalSection data={null} ticker="AAPL" /><SectionLoadError retryHref="/x" title="Noticias" /></>);
        expect(screen.getByRole('button', { name: 'Actualizar SEC' })).toBeInTheDocument();
        expect(screen.getByText('No se pudo cargar Noticias.')).toBeInTheDocument();
        expect(screen.getByRole('link', { name: 'Reintentar' })).toBeInTheDocument();
    });

    it('formatos auxiliares por idioma', () => {
        expect(formatProvenanceValue(0.144, 'ratio', 'en')).toBe('14.4%');
        expect(formatProvenanceValue(1234, 'shares', 'en')).toBe('1,234 shares');
        expect(formatProvenanceValue(null, 'USD', 'en')).toBe('N/A');
        expect(formatProvenanceValue(70918000, 'USD')).toBe('70,92 M\u00a0US$');
        expect(financialSegment('consolidated', 'en')).toBe('Consolidated');
        expect(financialDefinition('Net Margin', 'en')).toBe('Net Margin');
        expect(financialDefinition('Net Margin')).toBe('Margen neto');
    });

    it('operaciones simuladas de la empresa en inglés', () => {
        Object.defineProperty(window, 'matchMedia', { configurable: true, value: () => ({ matches: false, addEventListener: () => undefined, removeEventListener: () => undefined }) });
        const trade = { id: 1, ticker: 'AAPL', status: 'closed', direction: 'short', horizon: 'thirty_days', created_at: '2026-10-05T10:00:00Z', currency: 'USD', realized_pnl: '1234.5', realized_pnl_net: null, thesis_anchor: null };
        const { unmount } = render(<CompanyPaperTrades locale="en" state={{ trades: [trade] as never }} ticker="AAPL" />);
        expect(screen.getByRole('list', { name: 'AAPL paper trades' })).toBeInTheDocument();
        expect(screen.getByText('Short · 30-day trade')).toBeInTheDocument();
        expect(screen.getByText('Closed · created 10/5/2026')).toBeInTheDocument();
        expect(screen.getByText('Gross result +1,234.5 USD · net N/A')).toBeInTheDocument();
        unmount();
        render(<CompanyPaperTrades locale="en" state={{ trades: [] }} ticker="AAPL" />);
        expect(screen.getByText('No paper trades for this company.')).toBeInTheDocument();
        expect(screen.getByRole('link', { name: 'Go to paper trading' })).toBeInTheDocument();
    });
});
