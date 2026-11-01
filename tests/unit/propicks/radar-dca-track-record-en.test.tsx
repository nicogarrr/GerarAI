import { render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { RadarDcaResult } from '@/lib/actions/propicks-radar-dca.actions';
import type { TrackRecordPick, TrackRecordResponse } from '@/lib/actions/propicks-track-record.actions';

const { getRadarDcaOpportunities, getTrackRecord } = vi.hoisted(() => ({
    getRadarDcaOpportunities: vi.fn(), getTrackRecord: vi.fn(),
}));
vi.mock('@/lib/actions/propicks-radar-dca.actions', () => ({ getRadarDcaOpportunities }));
vi.mock('@/lib/actions/propicks-track-record.actions', () => ({ getTrackRecord }));

import RadarDcaView from '@/components/proPicks/RadarDcaView';
import TrackRecordView from '@/components/proPicks/TrackRecordView';
import { LocaleProvider } from '@/lib/i18n/client';

const en = (ui: React.ReactNode) => render(<LocaleProvider locale="en">{ui}</LocaleProvider>);

const RADAR: RadarDcaResult = {
    as_of: '2026-10-31', page: 1, page_size: 20, total: 1, has_more: false, sectors: ['Technology'],
    counts_by_level: { '4': 1 },
    coverage: { universe: 27, evaluated: 26, ok: 25, invalid: 1, stale: 0 },
    items: [{
        ticker: 'T04', name: 'Co 4', sector: 'Technology', currency: 'USD',
        level: 4, level_label: '4X DCA', status: 'forming', signal_date: '2026-10-29',
        close: 91.5, price_date: '2026-10-29', source: 'yfinance', price_verified: false,
        confirmed_level: 1, confirmed_period: '2026-09', clear_price_signal: true,
        change: { status: 'compared', changed: true, from_level: 3, to_level: 4, since_price_date: '2026-10-15' },
        formula_version: 'nico-v1', scan_date: '2026-10-30',
        quality: { passed: true, reasons: [], policy: 'quality-v1', market_cap_usd: 2_000_000_000 },
    }],
} as RadarDcaResult;

const pick = (over: Partial<TrackRecordPick> = {}): TrackRecordPick => ({
    ticker: 'TEST', name: 'Synthetic', currency: 'EUR', entry_month: '2026-01', entry_price: 100,
    entry_price_date: '2026-01-02', status: 'activo', exit_month: null, exit_price: null, exit_price_date: null,
    exit_pct: null, spy_pct_exit: null, current_price: 110, current_price_date: '2026-10-27', current_stale: false,
    pct_since_entry: 0.1, spy_pct_since_entry: 0.02, horizon_date: '2026-04-02', pct_90d: null, spy_pct_90d: null, ...over,
});
const track = (picks: TrackRecordPick[], over: Partial<TrackRecordResponse> = {}): TrackRecordResponse => ({
    snapshots_count: 1, history_label: 'short', months: ['2026-01'], stale_threshold_days: 7, horizon_days: 90,
    spy: { available: true, source: 'local-fixture', latest_date: '2026-10-27' }, picks, ...over,
});

describe('Pro Picks en inglés: radar DCA y track record', () => {
    it('el radar DCA sale en inglés', async () => {
        getRadarDcaOpportunities.mockResolvedValue(RADAR);
        en(<RadarDcaView />);
        await waitFor(() => expect(screen.getByText('T04')).toBeTruthy());
        expect(screen.getByText('Forming')).toBeTruthy();
        expect(screen.getByText('Last confirmed: 1X · 2026-09')).toBeTruthy();
        expect(screen.getByText('Clear 4X')).toBeTruthy();
        expect(screen.getByText('Price not independently verified')).toBeTruthy();
        expect(screen.getByText('Clear quality')).toBeTruthy();
        expect(screen.getByText('Change 3X → 4X since 2026-10-15')).toBeTruthy();
        expect(screen.getByText(/Coverage: 25 current · 26 evaluated of 27/)).toBeTruthy();
        expect(screen.getByText(/Page 1 · 20 per page · 1 in total/)).toBeTruthy();
        expect(screen.getByRole('option', { name: 'All levels' })).toBeTruthy();
        expect(screen.getByRole('button', { name: /Next/ })).toBeTruthy();
        expect(document.body.textContent).not.toMatch(/Cobertura|Cierre|señal|Página|Siguiente|Confirmado|formación/);
    });

    it('el error del radar DCA sale en inglés', async () => {
        getRadarDcaOpportunities.mockRejectedValue(new Error('boom'));
        en(<RadarDcaView />);
        await waitFor(() => expect(screen.getByText(/The DCA radar is unavailable right now/)).toBeTruthy());
    });

    it('el track record sale en inglés con números y fechas en inglés', async () => {
        getTrackRecord.mockResolvedValue(track([pick(), pick({ ticker: 'OLD', status: 'salio', exit_month: '2026-03', exit_pct: -0.052, spy_pct_exit: 0.013 })]));
        en(<TrackRecordView />);
        await waitFor(() => expect(screen.getByText('Past winners')).toBeTruthy());
        expect(screen.getByRole('columnheader', { name: 'At 90 days' })).toBeTruthy();
        expect(screen.getByRole('columnheader', { name: 'Exit / current' })).toBeTruthy();
        expect(screen.getByText('active')).toBeTruthy();
        expect(screen.getByText('+10.0%')).toBeTruthy();
        expect(screen.getByText('-5.2%')).toBeTruthy();
        expect(screen.getByText('exit price missing')).toBeTruthy();
        expect(screen.getAllByText(/^pending \(/).length).toBe(2);
        expect(screen.getByText(/SPY \(local-fixture\) with data through/)).toBeTruthy();
        expect(document.body.textContent).not.toMatch(/Entrada|activo|pendiente|Actualizar|datos hasta/);
    });

    it('sin histórico, el estado vacío sale en inglés', async () => {
        getTrackRecord.mockResolvedValue(track([], { snapshots_count: 0 }));
        en(<TrackRecordView />);
        await waitFor(() => expect(screen.getByText("There's no history yet")).toBeTruthy());
        expect(screen.getByRole('button', { name: 'Refresh' })).toBeTruthy();
    });
});
