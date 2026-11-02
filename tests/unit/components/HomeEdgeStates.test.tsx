import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const h = vi.hoisted(() => ({ researchRequest: vi.fn(), requireAuthenticatedUser: vi.fn() }));
vi.mock('next/navigation', () => ({ useRouter: () => ({ refresh: vi.fn(), push: vi.fn() }), usePathname: () => '/inicio' }));
vi.mock('@/components/HomeAttention', () => ({ default: () => null }));
vi.mock('@/lib/research/client', () => ({ researchRequest: h.researchRequest, jsonBody: JSON.stringify }));
vi.mock('@/lib/auth/require-user', () => ({ requireAuthenticatedUser: h.requireAuthenticatedUser }));
vi.mock('@/lib/cache/memoryTTL', () => ({ cachedFetch: (_k: string, fetcher: () => Promise<unknown>) => fetcher() }));
vi.mock('@/lib/cache/requestCache', () => ({ requestCache: { invalidate: vi.fn() } }));
vi.mock('@/lib/actions/alerts.actions', () => ({ getUserAlerts: async () => [], getRecentTriggeredAlerts: async () => [] }));
vi.mock('@/lib/actions/home-overview.actions', () => ({
    getHomeWatchlistPreview: async () => ({ unavailable: false, total: 0, items: [] }),
    getHomeOpportunities: async () => [],
}));
vi.mock('@/lib/actions/holding-signals.actions', () => ({ getHoldingSignals: async () => ({ fairValues: {}, dca: null }) }));

import PersonalizedOverview from '@/components/PersonalizedOverview';
import { LocaleProvider } from '@/lib/i18n/client';

// Respuestas reales del backend (Postgres 17, 2 nov 2026): cartera vacía, una
// posición sin cotización, todo vendido, solo un dividendo y venta parcial.
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
   "alerts": [],
   "status": "ok",
   "base_currency": "EUR",
   "cash_native": {},
   "missing_fx": [],
   "data_as_of": null,
   "cash_as_of": null,
   "fx_rates": [],
   "valuation_dates_differ": false,
   "valuation_hold": [],
   "provenance": {
    "source": "Base de datos de GerarAI",
    "source_kind": "internal",
    "source_url": null,
    "fetched_at": "2026-11-01T23:56:25.064291+00:00",
    "coverage": "ok",
    "note": "Calculado desde posiciones/precios/FX persistidos; cada fila upstream lleva su propia procedencia."
   }
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
   "alerts": [
    {
     "severity": "high",
     "ticker": "ZZQX",
     "message": "ZZQX supera el 20 % de peso en la cartera",
     "metric_value": 1.0,
     "threshold": 0.2
    }
   ],
   "status": "ok",
   "base_currency": "EUR",
   "cash_native": {},
   "missing_fx": [],
   "data_as_of": "2026-01-05",
   "cash_as_of": null,
   "fx_rates": [],
   "valuation_dates_differ": false,
   "valuation_hold": [],
   "provenance": {
    "source": "Base de datos de GerarAI",
    "source_kind": "internal",
    "source_url": null,
    "fetched_at": "2026-11-01T23:56:56.146470+00:00",
    "coverage": "ok",
    "note": "Calculado desde posiciones/precios/FX persistidos; cada fila upstream lleva su propia procedencia."
   }
  },
  "positions": {
   "items": [
    {
     "ticker": "ZZQX",
     "name": "ZZQX",
     "sector": "Unknown",
     "analysis": {
      "status": "queued",
      "as_of": "2026-11-01T23:56:56.115846+00:00",
      "thesis_status": null
     },
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
   "alerts": [],
   "status": "ok",
   "base_currency": "EUR",
   "cash_native": {},
   "missing_fx": [],
   "data_as_of": null,
   "cash_as_of": null,
   "fx_rates": [],
   "valuation_dates_differ": false,
   "valuation_hold": [],
   "provenance": {
    "source": "Base de datos de GerarAI",
    "source_kind": "internal",
    "source_url": null,
    "fetched_at": "2026-11-01T23:56:56.286965+00:00",
    "coverage": "ok",
    "note": "Calculado desde posiciones/precios/FX persistidos; cada fila upstream lleva su propia procedencia."
   }
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
   "alerts": [],
   "status": "ok",
   "base_currency": "EUR",
   "cash_native": {},
   "missing_fx": [],
   "data_as_of": null,
   "cash_as_of": null,
   "fx_rates": [],
   "valuation_dates_differ": false,
   "valuation_hold": [],
   "provenance": {
    "source": "Base de datos de GerarAI",
    "source_kind": "internal",
    "source_url": null,
    "fetched_at": "2026-11-01T23:56:56.379306+00:00",
    "coverage": "ok",
    "note": "Calculado desde posiciones/precios/FX persistidos; cada fila upstream lleva su propia procedencia."
   }
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
 "partial_sold": {
  "summary": {
   "total_value": 42.0,
   "equity_value": 42.0,
   "cash_assets_base": 0.0,
   "margin_debt_base": 0.0,
   "cash": {
    "EUR": 0.0
   },
   "top_1_weight": 1.0,
   "top_5_weight": 1.0,
   "alerts": [
    {
     "severity": "high",
     "ticker": "ZZQX",
     "message": "ZZQX supera el 20 % de peso en la cartera",
     "metric_value": 1.0,
     "threshold": 0.2
    }
   ],
   "status": "ok",
   "base_currency": "EUR",
   "cash_native": {},
   "missing_fx": [],
   "data_as_of": "2026-02-05",
   "cash_as_of": null,
   "fx_rates": [],
   "valuation_dates_differ": false,
   "valuation_hold": [],
   "provenance": {
    "source": "Base de datos de GerarAI",
    "source_kind": "internal",
    "source_url": null,
    "fetched_at": "2026-11-01T23:56:56.643002+00:00",
    "coverage": "ok",
    "note": "Calculado desde posiciones/precios/FX persistidos; cada fila upstream lleva su propia procedencia."
   }
  },
  "positions": {
   "items": [
    {
     "ticker": "ZZQX",
     "name": "ZZQX",
     "sector": "Unknown",
     "analysis": {
      "status": "queued",
      "as_of": "2026-11-01T23:56:56.603564+00:00",
      "thesis_status": null
     },
     "quantity": 6.0,
     "average_cost": 5.0,
     "market_price": 7.0,
     "market_value": 42.0,
     "valuation_hold": null,
     "unrealized_pnl": null,
     "realized_pnl": 8.0,
     "cost_basis": 30.0,
     "as_of": "2026-02-05",
     "currency": "EUR",
     "native_currency": "EUR",
     "base_currency": "EUR",
     "market_value_native": 42.0,
     "market_value_base": 42.0,
     "cost_basis_native": 30.0,
     "cost_basis_base": 30.0,
     "unrealized_pnl_native": null,
     "unrealized_pnl_base": null,
     "realized_pnl_base": 8.0,
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
 }
} as const;
type Name = keyof typeof SCENARIOS;

async function renderHome(name: Name, locale: 'es' | 'en') {
    h.requireAuthenticatedUser.mockResolvedValue({ id: 'u1' });
    h.researchRequest.mockImplementation(async (path: string) => {
        if (path.startsWith('/api/portfolio/positions')) return SCENARIOS[name].positions;
        if (path === '/api/portfolio/summary') return SCENARIOS[name].summary;
        throw new Error(`sin datos para ${path}`);
    });
    const view = render(<LocaleProvider locale={locale}><PersonalizedOverview userId="u1" /></LocaleProvider>);
    await waitFor(() => expect(screen.queryAllByText(/Cargando|Loading/u)).toHaveLength(0));
    await waitFor(() => expect(view.container.querySelector('[aria-busy="true"]')).toBeNull());
    return (view.container.textContent ?? '').replace(/\s+/g, ' ');
}

describe('inicio en estados límite (datos reales del backend)', () => {
    beforeEach(() => vi.clearAllMocks());

    it.each(['empty', 'unquoted', 'sold', 'dividend_only', 'partial_sold'] as const)('%s: sin valores rotos en castellano ni en inglés', async (name) => {
        for (const locale of ['es', 'en'] as const) {
            const text = await renderHome(name, locale);
            expect(text).not.toMatch(/NaN|undefined|Infinity|\[object|\+0,00|\+0\.00/);
        }
    });

    it.each(['empty', 'sold', 'dividend_only'] as const)('%s: sin posiciones abiertas, primeros pasos', async (name) => {
        const text = await renderHome(name, 'es');
        expect(text).toContain('Primeros pasos');
        expect(text).not.toContain('Ganancia/Pérdida');
    });

    it.each(['unquoted', 'partial_sold'] as const)('%s: sin cotización dice eso, no que falte la base de coste', async (name) => {
        const es = await renderHome(name, 'es');
        expect(es).toContain('Ganancia/Pérdida desde la compraN/D');
        expect(es).toContain('Todavía no hay cotización de tus posiciones');
        expect(es).not.toContain('base de coste');
        const en = await renderHome(name, 'en');
        expect(en).toContain("There's no quote for your positions yet");
        expect(en).not.toContain('cost basis');
    });

    it('en inglés, el botón de la watchlist vacía también', async () => {
        const text = await renderHome('empty', 'en');
        expect(text).toContain('Add companies');
        expect(text).not.toContain('Añadir empresas');
    });
});
