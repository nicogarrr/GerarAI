import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { LocaleProvider } from '@/lib/i18n/client';
import { createTranslator } from '@/lib/i18n/translate';
import DcaAlertSettingsList from '@/components/watchlist/DcaAlertSettingsList';
import DcaHitRatesCard from '@/components/watchlist/DcaHitRatesCard';
import DcaLevelBadge from '@/components/watchlist/DcaLevelBadge';
import DcaSignalsPanel from '@/components/watchlist/DcaSignalsPanel';
import type { DcaHitRates, DcaSignalItem, DcaSignalState, DcaSignalsResponse } from '@/lib/dca/types';
import { TooltipProvider } from '@/components/ui/tooltip';
vi.mock('@/components/watchlist/LazyDcaControls', () => ({ LazyDcaHitRatesPopover: ({ symbol }: { symbol: string }) => <button>History {symbol}</button>, LazyDcaWatchCardToggle: ({ symbol }: { symbol: string }) => <button>Card {symbol}</button>, LazyDcaEvaluateButton: () => <button>Run fixture</button> }));
const ti = createTranslator('en');
const state: DcaSignalState = { level: 2, previous_level: 1, key: '2x', label: '2X DCA', zone: '2X DCA', color: '#FFFFFF', fg: '#000000', status: 'forming', period: '2026-11', signal_date: '2026-10-30', close: 100, currency: 'USD', currency_label: null, metrics: { rsi: 35 }, level_prices: { '2x': 100, '3x': 90, '4x': 80 }, params_version: 'fixture', data_source: 'fixture', evaluated_at: '2026-11-01', last_alerted_level: null, last_alerted_period: null };
const item = (i: number, extra: Partial<DcaSignalItem> = {}): DcaSignalItem => ({ symbol: `T${i}`, company_name: `Company ${i}`, sources: [], in_watchlist: true, in_portfolio: false, min_level_override: null, effective_min_level: 2, alerts_on: true, state: null, ...extra });
const rates: DcaHitRates = { symbol: 'MSFT', available: true, reason: null, months_completed: 24, first_period: '2024-01', last_period: '2025-12', horizons: [3, 6], params_version: 'fixture', evaluated_at: null, rows: [{ key: '2x', label: '2X DCA', levels: [2], signal_months: 5, color: '#00AA78', cells: [{ horizon_months: 3, months: 5, pct_higher: 0.6, avg_return: 0.12 }, { horizon_months: 6, months: 0, pct_higher: null, avg_return: null }] }], disclaimer: 'Fixture historical only' };
const mount = (node: React.ReactNode) => render(<LocaleProvider locale="en">{node}</LocaleProvider>);

describe('bounded alert settings', () => {
    it('renders only five companies, advances and clamps if a refresh removes the last page', () => {
        const items = Array.from({ length: 6 }, (_, i) => item(i, { state: i === 0 ? state : null, in_portfolio: i === 0 }));
        const ui = mount(<DcaAlertSettingsList items={items} />);
        expect(screen.getByText('T0')).toBeInTheDocument(); expect(screen.queryByText('T5')).not.toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'History T0' })).toBeInTheDocument(); expect(screen.queryByRole('button', { name: 'History T1' })).not.toBeInTheDocument();
        const next = screen.getByRole('button', { name: /next/i }); fireEvent.click(next);
        expect(screen.getByText('T5')).toBeInTheDocument(); expect(next).toBeDisabled();
        fireEvent.click(screen.getByRole('button', { name: /previous/i })); expect(screen.getByText('T0')).toBeInTheDocument(); fireEvent.click(next);
        ui.rerender(<LocaleProvider locale="en"><DcaAlertSettingsList items={[item(99, { company_name: null, in_watchlist: false })]} /></LocaleProvider>);
        expect(screen.getByText('T99')).toBeInTheDocument(); expect(screen.getByRole('status')).toHaveTextContent(/1.*1/); expect(screen.getByRole('button', { name: /previous/i })).toBeDisabled();
    });
    it('says no companies instead of leaving an empty paginated list', () => { mount(<DcaAlertSettingsList items={[]} />); expect(screen.queryByRole('list')).not.toBeInTheDocument(); expect(screen.queryByRole('navigation')).not.toBeInTheDocument(); });
});

describe('historical rates are not invented', () => {
    it('distinguishes unavailable, unavailable-with-reason, missing percentages and measured cells', () => {
        const ui = render(<DcaHitRatesCard data={null} ti={ti} locale="en" />); expect(screen.queryByRole('table')).not.toBeInTheDocument();
        ui.rerender(<DcaHitRatesCard data={{ ...rates, available: false, reason: 'Fixture no history' }} ti={ti} locale="en" />); expect(screen.getByText('Fixture no history')).toBeInTheDocument();
        ui.rerender(<DcaHitRatesCard data={rates} ti={ti} locale="en" />); expect(screen.getByRole('table')).toBeInTheDocument(); expect(screen.getByText(/60.*%/)).toBeInTheDocument(); expect(screen.getByText('—')).toBeInTheDocument(); expect(screen.getByText(/n=5/)).toHaveTextContent(/12.*%/);
        ui.rerender(<DcaHitRatesCard data={rates} compact scope="range" ti={ti} locale="en" />); expect(screen.queryByText(/n=5/)).not.toBeInTheDocument(); expect(screen.getByText(/24.*range/i)).toBeInTheDocument();
    });
    it.each([0, 1, 3])('declares completed visits=%s, the open visit and excluded gaps separately', completed => {
        const zone_visits = { available: true, reason: null, levels: [2,3,4], months_completed: 24, first_period: null, last_period: null, completed_visits: completed, avg_months: completed ? 2.5 : null, max_months: 4, visits: [], open_visit_months: 3, excluded_gap_visits: completed === 1 ? 1 : 2, params_version: null };
        render(<DcaHitRatesCard data={{ ...rates, zone_visits }} ti={ti} locale="en" />);
        const visits = screen.getByTestId('dca-zone-visits'); expect(visits).toHaveTextContent(/3/); expect(visits).toHaveTextContent(/excluded|gap/i); if (completed) expect(visits).toHaveTextContent('2.5'); else expect(visits).toHaveTextContent(/no|none|not/i);
    });
});

describe('DCA level badge', () => {
    it.each(['never_run', 'job_failed', 'skipped'] as const)('explains %s without claiming an evaluated level; compact mode omits it', status => {
        const ui = mount(<DcaLevelBadge item={item(1, { evaluation_status: status, evaluation_reason: 'Fixture reason' })} signalMonths={null} />);
        expect(screen.getByTestId('dca-missing-badge')).not.toBeEmptyDOMElement();
        ui.rerender(<LocaleProvider locale="en"><DcaLevelBadge item={item(1)} signalMonths={null} compact /></LocaleProvider>); expect(screen.queryByTestId('dca-missing-badge')).not.toBeInTheDocument();
    });
    it('opens by touch/click with confirmed close, distinct live price, trigger levels and stale warning', () => {
        const live = { ...state, close_kind: 'live' as const, live_price: 105, live_session: 'pre', live_at: '2026-11-15T10:00:00Z', stale: true, data_age_days: 40 };
        mount(<TooltipProvider><DcaLevelBadge item={item(1, { state: live })} signalMonths={6} /></TooltipProvider>);
        expect(screen.getByTestId('dca-stale')).not.toBeEmptyDOMElement(); const trigger = screen.getByRole('button'); fireEvent.pointerDown(trigger); fireEvent.click(trigger);
        expect(trigger).toHaveAttribute('aria-expanded', 'true'); expect(screen.getAllByTestId('dca-badge-live')[0]).toHaveTextContent(/105/);
        expect(screen.getAllByText(/3X.*90/).length).toBeGreaterThan(0); expect(screen.getAllByText(/100/).length).toBeGreaterThan(0); fireEvent.click(trigger); expect(trigger).toHaveAttribute('aria-expanded', 'false');
    });
});

describe('signals panel honest status', () => {
    const data: DcaSignalsResponse = { alerts_enabled: false, evaluation_enabled: false, global_min_level: 2, trims_enabled: false, channels: ['in_app', 'email', 'other'], email_configured: false, signal_months: 6, zones: [], items: [item(1)], last_run: null };
    it('distinguishes unavailable from empty and shows disabled evaluation and email/alert limits', () => {
        const ui = mount(<DcaSignalsPanel data={null} unavailable ti={ti} locale="en" />); expect(screen.getByTestId('dca-signals-unavailable')).not.toBeEmptyDOMElement();
        ui.rerender(<LocaleProvider locale="en"><DcaSignalsPanel data={data} unavailable={false} ti={ti} locale="en" /></LocaleProvider>);
        expect(screen.getByTestId('dca-evaluation-disabled')).not.toBeEmptyDOMElement(); expect(screen.getByTestId('dca-last-run')).not.toBeEmptyDOMElement();
        expect(screen.getByRole('link', { hidden: true })).toHaveAttribute('href', '/settings#dca');
        ui.rerender(<LocaleProvider locale="en"><DcaSignalsPanel data={{ ...data, directional_policy: true, up_min_level: 3, down_max_level: 1, trims_enabled: true, items: [item(1, { state })] }} unavailable={false} ti={ti} locale="en" /></LocaleProvider>);
        expect(screen.getByTestId('dca-evaluation-disabled')).toHaveTextContent(/turned off.*levels don.t update/i);
    });
});

describe('partial historical results and enabled settings', () => {
    it('keeps uncolored rows and missing periods neutral, omits unavailable visits and missing return averages', () => {
        const data = { ...rates, first_period: null, last_period: null, rows: [{ ...rates.rows[0], color: null, cells: [{ horizon_months: 3, months: 5, pct_higher: 0, avg_return: null }] }], zone_visits: { available: false, reason: 'partial' } as DcaHitRates['zone_visits'] };
        const ui = render(<DcaHitRatesCard data={data} ti={ti} locale="en" />);
        expect(screen.queryByText(/2024-01/)).not.toBeInTheDocument(); expect(screen.queryByTestId('dca-zone-visits')).not.toBeInTheDocument(); expect(screen.getByText('n=5')).not.toHaveTextContent(/average/i); expect(screen.getByRole('rowheader').querySelector('span')).toHaveStyle({ backgroundColor: '#374151' });
        ui.rerender(<DcaHitRatesCard data={{ ...data, available: false, reason: null }} ti={ti} locale="en" />); expect(screen.queryByRole('table')).not.toBeInTheDocument();
        ui.rerender(<DcaHitRatesCard data={{ ...data, zone_visits: { available: true, completed_visits: 2, avg_months: null, open_visit_months: 0 } as DcaHitRates['zone_visits'] }} ti={ti} locale="en" />); expect(screen.getByTestId('dca-zone-visits')).not.toHaveTextContent(/open visit/i);
    });
    it('shows enabled delivery, disabled directions, and actual last run without inventing a missing run', () => {
        const data: DcaSignalsResponse = { alerts_enabled: true, email_configured: true, evaluation_enabled: true, directional_policy: true, up_min_level: null, down_max_level: null, global_min_level: 2, trims_enabled: true, channels: [], signal_months: null, zones: [], items: [] };
        const ui = mount(<DcaSignalsPanel data={data} unavailable={false} ti={ti} locale="en" />); expect(screen.queryByTestId('dca-last-run')).not.toBeInTheDocument(); expect(screen.queryByTestId('dca-evaluation-disabled')).not.toBeInTheDocument(); expect(screen.getByTestId('dca-signals')).toHaveTextContent(/off/i);
        ui.rerender(<LocaleProvider locale="en"><DcaSignalsPanel data={{ ...data, last_run: { status: 'ok', trigger: 'manual', started_at: '2026-11-15T10:00:00Z', finished_at: '2026-11-15T10:01:00Z', tracked: 2, evaluated: 2, skipped: 0, errors: 0, alerted: 0, error: null }, channels: ['email'], items: [item(1), item(2)] }} unavailable={false} ti={ti} locale="en" /></LocaleProvider>); expect(screen.getByTestId('dca-last-run')).not.toBeEmptyDOMElement(); expect(screen.getByTestId('dca-signals')).toHaveTextContent(/email/i);
        ui.rerender(<LocaleProvider locale="en"><DcaSignalsPanel data={null} unavailable={false} ti={ti} locale="en" /></LocaleProvider>); expect(screen.getByTestId('dca-signals-unavailable')).toBeInTheDocument();
    });
});
