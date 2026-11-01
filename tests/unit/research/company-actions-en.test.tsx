import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { LocaleProvider } from '@/lib/i18n/client';
import type { PortfolioHolding } from '@/lib/actions/portfolio.actions';

const mocks = vi.hoisted(() => ({ create: vi.fn(), success: vi.fn(), error: vi.fn(), info: vi.fn() }));
vi.mock('@/lib/actions/alerts.actions', () => ({ createAlertResult: mocks.create }));
vi.mock('sonner', () => ({ toast: { success: mocks.success, error: mocks.error, info: mocks.info } }));

import CompanyActionsMenu from '@/components/research/CompanyActionsMenu';
import { CompanyPositionPanel } from '@/components/research/CompanyPositionPanel';
import QuickAlertPopoverBody from '@/components/research/QuickAlertPopoverBody';

vi.mock('@/components/research/GuideBrainButton', () => ({ GuideBrainButton: () => null }));
vi.mock('@/components/research/DecisionJournalEntryLink', () => ({ DecisionJournalEntryLink: () => null }));

const holding = (over: Partial<PortfolioHolding> = {}): PortfolioHolding => ({
    symbol: 'TEST', quantity: 10, avgPrice: 100, costReviewMessage: null, currentPrice: 150,
    valuationHold: null, value: 1350, cost: 900, gain: 450, gainPercent: 50, nativeCurrency: 'USD',
    baseCurrency: 'EUR', fxMissing: false, nativeGain: 500, nativeCost: 1000, valueMissing: false,
    firstBuyDate: '2025-01-01', holdingDays: 300, fiscalBucket: 'corto_plazo', ...over,
});

beforeEach(() => { vi.stubGlobal('matchMedia', () => ({ matches: false, addEventListener() {}, removeEventListener() {} })); });
afterEach(() => { vi.unstubAllGlobals(); vi.clearAllMocks(); });

describe('company page actions in English', () => {
    it('more-actions menu', () => {
        render(<LocaleProvider locale="en"><CompanyActionsMenu ticker="MSFT" changeCount={3} /></LocaleProvider>);
        fireEvent.click(screen.getByRole('button', { name: 'More actions' }));
        expect(screen.getByRole('link', { name: 'What changed (3)' })).toHaveAttribute('href', '/research/MSFT?view=seguimiento');
        for (const name of ['Financial terminal', 'Driver assumptions', 'Management credibility', 'Dilution and buybacks', 'Public short reports', 'Dividends and splits']) {
            expect(screen.getByRole('link', { name })).toBeInTheDocument();
        }
        expect(screen.getByText('Deep analysis')).toBeInTheDocument();
        expect(screen.queryByText(/Qué ha cambiado|Cortos públicos/)).toBeNull();
    });

    it('position panel with English labels and numbers', () => {
        render(<CompanyPositionPanel context={{ status: 'held', holding: holding(), weightPercent: 39.7, positionsAsOf: '2026-10-27' }} locale="en" />);
        expect(screen.getByRole('heading', { name: 'Your position' })).toBeVisible();
        expect(screen.getByText('Unrealized gain').parentElement).toHaveTextContent('€450.00 (+50.0%)');
        expect(screen.getByText('Unrealized gain').parentElement).toHaveTextContent('$500.00 in USD');
        expect(screen.getByText('of positions with a value')).toBeInTheDocument();
        expect(screen.getByRole('link', { name: 'Record a buy or sell' })).toBeInTheDocument();
        expect(screen.queryByText(/Plusvalía|Tu posición/)).toBeNull();
    });

    it('position panel warnings and N/A in English', () => {
        render(<CompanyPositionPanel context={{ status: 'held', holding: holding({ avgPrice: 0, cost: 0 }), weightPercent: null, positionsAsOf: null }} locale="en" />);
        expect(screen.getByText('Purchase cost unknown. The gain can’t be calculated.')).toBeInTheDocument();
        expect(screen.getByText('Weight').parentElement).toHaveTextContent('N/A');
    });

    it('quick alert: type list, validation and created toast', async () => {
        mocks.create.mockResolvedValue({ ok: true });
        render(<LocaleProvider locale="en"><QuickAlertPopoverBody ticker="MSFT" currency="USD" /></LocaleProvider>);
        expect(screen.getByRole('combobox', { name: 'Alert type' })).toHaveTextContent('Price above');
        const input = screen.getByRole('textbox', { name: 'Target price in USD' });
        expect(input).toHaveAttribute('placeholder', 'Target price $');
        expect(screen.getByRole('link', { name: 'View alerts' })).toHaveAttribute('href', '/alerts');
        await waitFor(() => expect(screen.getByRole('button', { name: '+ Alert' })).toBeEnabled());
        fireEvent.click(screen.getByRole('button', { name: '+ Alert' }));
        expect(mocks.error).toHaveBeenCalledWith('Enter a valid target price');
        fireEvent.change(input, { target: { value: '1,234.5' } });
        fireEvent.click(screen.getByRole('button', { name: '+ Alert' }));
        await waitFor(() => expect(mocks.success).toHaveBeenCalledWith('Alert created: MSFT price above $1,234.50'));
    });
});
