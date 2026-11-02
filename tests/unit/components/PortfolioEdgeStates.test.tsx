import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';

const h = vi.hoisted(() => ({
    del: vi.fn(), refreshPrices: vi.fn(), routerRefresh: vi.fn(),
    success: vi.fn(), error: vi.fn(), info: vi.fn(), showError: vi.fn(),
}));
vi.mock('next/navigation', () => ({ useRouter: () => ({ refresh: h.routerRefresh }) }));

vi.mock('sonner', () => ({ toast: { success: h.success, error: h.error, info: h.info } }));
vi.mock('@/lib/toast', () => ({ showErrorToast: h.showError }));
vi.mock('@/components/calendar/CompanyLogo', () => ({ CompanyLogo: () => null }));
vi.mock('@/components/common/TrackedAnalysisStatus', () => ({ TrackedAnalysisStatus: () => null }));
vi.mock('@/components/common/ExtendedHoursLine', () => ({ default: () => null }));
vi.mock('@/components/common/AnalystTargetLine', () => ({ default: () => null }));
vi.mock('@/components/portfolio/HoldingSignals', () => ({
    DcaLevelChip: () => null, FairValueLine: () => null, useHoldingSignals: () => null,
}));
vi.mock('@/components/portfolio/ImportIBKRButton', () => ({ default: () => <span>import-ibkr</span> }));
vi.mock('@/components/portfolio/ImportImageButton', () => ({ default: () => <span>import-image</span> }));
vi.mock('@/components/portfolio/AddTransactionButton', () => ({ default: () => <span>add-tx</span> }));

const { researchRequest, requireAuthenticatedUser } = vi.hoisted(() => ({ researchRequest: vi.fn(), requireAuthenticatedUser: vi.fn() }));
vi.mock('@/lib/research/client', () => ({ researchRequest, jsonBody: JSON.stringify }));
vi.mock('@/lib/auth/require-user', () => ({ requireAuthenticatedUser }));
vi.mock('@/lib/cache/memoryTTL', () => ({ cachedFetch: (_k: string, fetcher: () => Promise<unknown>) => fetcher() }));
vi.mock('@/lib/cache/requestCache', () => ({ requestCache: { invalidate: vi.fn() } }));
import { getPortfolioSummary } from '@/lib/actions/portfolio.actions';
import PortfolioHoldings from '@/components/portfolio/PortfolioHoldings';
import PortfolioSummary from '@/components/portfolio/PortfolioSummary';

// Respuestas reales del backend (Postgres 17, 2 nov 2026) para cuatro carteras
// límite: vacía, una posición sin cotización, todo vendido y solo un dividendo.
const SCENARIOS = {
 "empty": {
  "summary": {
   "total_value": 0.0,
   "equity_value": 0.0,
   "cash_assets_base": 0.0,
   "margin_debt_base": 0.0,
   "cash": {
    "EUR": 0.0
   },
   "top_1_weight": 0.0,
   "top_5_weight": 0.0,
   "status": "ok",
   "base_currency": "EUR",
   "cash_native": {},
   "missing_fx": [],
   "data_as_of": null,
   "cash_as_of": null,
   "fx_rates": [],
   "valuation_dates_differ": false,
   "valuation_hold": []
  },
  "positions": {
   "items": [],
   "page_info": {
    "page": 1,
    "page_size": 100,
    "total_items": 0,
    "total_pages": 0,
    "has_next": false,
    "has_prev": false
   }
  }
 },
 "unquoted": {
  "summary": {
   "total_value": 50.0,
   "equity_value": 50.0,
   "cash_assets_base": 0.0,
   "margin_debt_base": 0.0,
   "cash": {
    "EUR": 0.0
   },
   "top_1_weight": 1.0,
   "top_5_weight": 1.0,
   "status": "ok",
   "base_currency": "EUR",
   "cash_native": {},
   "missing_fx": [],
   "data_as_of": "2026-01-05",
   "cash_as_of": null,
   "fx_rates": [],
   "valuation_dates_differ": false,
   "valuation_hold": []
  },
  "positions": {
   "items": [
    {
     "ticker": "ZZQX",
     "name": "ZZQX",
     "sector": "Unknown",
     "quantity": 10.0,
     "average_cost": 5.0,
     "market_price": 5.0,
     "market_value": 50.0,
     "valuation_hold": null,
     "unrealized_pnl": null,
     "realized_pnl": 0.0,
     "cost_basis": 50.0,
     "as_of": "2026-01-05",
     "currency": "EUR",
     "native_currency": "EUR",
     "base_currency": "EUR",
     "market_value_native": 50.0,
     "market_value_base": 50.0,
     "cost_basis_native": 50.0,
     "cost_basis_base": 50.0,
     "unrealized_pnl_native": null,
     "unrealized_pnl_base": null,
     "realized_pnl_base": 0.0,
     "fx_rate": 1.0,
     "pnl_price_effect_base": null,
     "pnl_fx_effect_base": null,
     "source": "postgres_ledger",
     "first_buy_date": "2026-01-05",
     "holding_days": 301,
     "fiscal_bucket": "corto_plazo",
     "quote_missing": true,
     "cost_reconciliation": null
    }
   ],
   "page_info": {
    "page": 1,
    "page_size": 100,
    "total_items": 1,
    "total_pages": 1,
    "has_next": false,
    "has_prev": false
   }
  }
 },
 "sold": {
  "summary": {
   "total_value": 0.0,
   "equity_value": 0.0,
   "cash_assets_base": 0.0,
   "margin_debt_base": 0.0,
   "cash": {
    "EUR": 0.0
   },
   "top_1_weight": 0.0,
   "top_5_weight": 0.0,
   "status": "ok",
   "base_currency": "EUR",
   "cash_native": {},
   "missing_fx": [],
   "data_as_of": null,
   "cash_as_of": null,
   "fx_rates": [],
   "valuation_dates_differ": false,
   "valuation_hold": []
  },
  "positions": {
   "items": [],
   "page_info": {
    "page": 1,
    "page_size": 100,
    "total_items": 0,
    "total_pages": 0,
    "has_next": false,
    "has_prev": false
   }
  }
 },
 "dividend_only": {
  "summary": {
   "total_value": 0.0,
   "equity_value": 0.0,
   "cash_assets_base": 0.0,
   "margin_debt_base": 0.0,
   "cash": {
    "EUR": 0.0
   },
   "top_1_weight": 0.0,
   "top_5_weight": 0.0,
   "status": "ok",
   "base_currency": "EUR",
   "cash_native": {},
   "missing_fx": [],
   "data_as_of": null,
   "cash_as_of": null,
   "fx_rates": [],
   "valuation_dates_differ": false,
   "valuation_hold": []
  },
  "positions": {
   "items": [],
   "page_info": {
    "page": 1,
    "page_size": 100,
    "total_items": 0,
    "total_pages": 0,
    "has_next": false,
    "has_prev": false
   }
  }
 }
} as const;

type ScenarioName = keyof typeof SCENARIOS;

async function summaryFor(name: ScenarioName) {
    requireAuthenticatedUser.mockResolvedValue({ id: 'u' });
    researchRequest.mockImplementation(async (path: string) => {
        if (path.startsWith('/api/portfolio/positions')) return SCENARIOS[name].positions;
        if (path === '/api/portfolio/summary') return SCENARIOS[name].summary;
        throw new Error(`sin datos para ${path}`);
    });
    return getPortfolioSummary('u');
}

const text = (el: HTMLElement) => (el.textContent ?? '').replace(/\s+/g, ' ');

describe('cartera en estados límite (datos reales del backend)', () => {
    beforeEach(() => vi.clearAllMocks());

    it.each(['empty', 'sold', 'dividend_only'] as const)('%s: totales N/D, nunca 0,00 € ni +0,00 %%', async (name) => {
        const summary = await summaryFor(name);
        expect(summary.holdings).toEqual([]);
        const { container } = render(<PortfolioSummary summary={summary} />);
        const shown = text(container);
        expect(shown).toContain('N/D');
        expect(shown).not.toMatch(/0,00\s?€|\+0,00/);
        expect(shown).not.toMatch(/NaN|Infinity|undefined/);
    });

    it.each(['empty', 'sold', 'dividend_only'] as const)('%s: la tabla dice que no hay posiciones abiertas', async (name) => {
        const summary = await summaryFor(name);
        render(<PortfolioHoldings holdings={summary.holdings} userId="u" />);
        expect(screen.getByText('No tienes posiciones abiertas')).toBeInTheDocument();
    });

    it('sin cotización: valor visible, coste y G/P N/D y la posición cuenta como excluida', async () => {
        const summary = await summaryFor('unquoted');
        expect(summary.totalsExcluded).toBe(1);
        expect(summary.holdings[0]).toMatchObject({ symbol: 'ZZQX', quoteMissing: true });
        const card = render(<PortfolioSummary summary={summary} />);
        const shown = text(card.container);
        expect(shown).toContain('50,00 €');
        expect(shown).not.toMatch(/NaN|Infinity|undefined|\+0,00/);
        card.unmount();
        render(<PortfolioHoldings holdings={summary.holdings} userId="u" />);
        const row = within(screen.getByRole('table')).getByText('ZZQX').closest('tr')!;
        expect(text(row)).toContain('N/D');
        expect(text(row)).not.toMatch(/NaN|Infinity|undefined/);
    });
});
