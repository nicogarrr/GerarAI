import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import DcaWatchCard from '@/components/watchlist/DcaWatchCard';
import DcaLevelBadge from '@/components/watchlist/DcaLevelBadge';
import { TooltipProvider } from '@/components/ui/tooltip';
import { LocaleProvider } from '@/lib/i18n/client';
import { createTranslator } from '@/lib/i18n/translate';
import type { DcaWatchCardData, DcaSignalItem } from '@/lib/dca/types';
import fixture from '../watchlist-dca-card.fixture.json';
const base = fixture as unknown as DcaWatchCardData;
const ti = createTranslator('en');
const card = (data: DcaWatchCardData | null) => <DcaWatchCard data={data} ti={ti} locale="en" />;

describe('DCA card with partial backend information', () => {
    it('distinguishes unavailable from insufficient history and never invents a current level', () => {
        const ui = render(card(null)); expect(screen.getByRole('status')).toHaveTextContent(/unavailable|available/i); expect(screen.queryByTestId('dca-card-current')).not.toBeInTheDocument();
        ui.rerender(card({ ...base, available: false })); expect(screen.getByRole('status')).toHaveTextContent(/not enough|insufficient/i);
        ui.rerender(card({ ...base, current: undefined })); expect(screen.getByRole('status')).toHaveTextContent(/not enough|insufficient/i);
    });
    it('does not invent missing timeframe, risk, change or formula inputs', () => {
        render(card({ ...base, current: { ...base.current!, status: 'confirmed', color: '#FFFFFF', fg: '#000000' }, timeframes: [{ ...base.timeframes[0], available: false, zone: undefined }], risk: undefined, last_change: null, why: undefined }));
        expect(screen.getByTestId('dca-tf-week')).toHaveTextContent('—'); expect(screen.queryByTestId('dca-card-risk')).not.toBeInTheDocument(); expect(screen.queryByTestId('dca-card-change')).not.toBeInTheDocument(); expect(screen.queryByText('Why this level?')).not.toBeInTheDocument(); expect(screen.getByTestId('dca-card-current')).toHaveStyle({ borderColor: '#9CA3AF' });
    });
    it('keeps unknown formula values as dashes, omits unavailable SMA/volatility and preserves an unknown risk reason', () => {
        render(card({ ...base, risk: { ...base.risk!, reasons: [{ key: 'future_reason', value: null }, { key: 'short_history', value: null }] }, why: { ...base.why!, drawdown: null, high: null, sma: null, vol: null, binding: null, level_drawdown: null, dd_thresholds: [0.15, 0.25, 0.4], level_prices: { '2x': null, '3x': null, '4x': null } } }));
        expect(screen.getByText(/future_reason/)).toBeInTheDocument(); expect(screen.getByText(/2X —.*3X —.*4X —/)).toBeInTheDocument(); expect(screen.queryByText(/SMA.*30/)).not.toBeInTheDocument();
    });
    it('shows missing SMA window and level honestly, with a safe fallback for an unknown binding', () => {
        render(card({ ...base, risk: undefined, why: { ...base.why!, sma_months: null, sma_gap: null, adj_gap: null, level_sma_gap: null, binding: 'future_binding' } }));
        expect(screen.getByText(/Distance below/)).toHaveTextContent('—'); expect(screen.queryByTestId('dca-card-risk')).not.toBeInTheDocument(); expect(screen.getByText(/Closes that would trigger/)).not.toHaveTextContent('NaN');
    });
    it.each(['post', 'regular'] as const)('labels %s live prices without assuming an absent timestamp', session => {
        render(card({ ...base, live: { used: true, session, price: 123.45, timestamp: null } }));
        expect(screen.getByTestId('dca-card-live')).toHaveTextContent(/123.45/); expect(screen.getByTestId('dca-card-live')).toHaveTextContent('—'); expect(screen.getByTestId('dca-card-live')).toHaveTextContent(session === 'post' ? /after|post/i : /current price/i);
    });
    it('does not treat zero return as a missing return', () => {
        render(card({ ...base, last_change: { ...base.last_change!, change: 0, close: 0 } })); expect(screen.getByTestId('dca-card-change')).toHaveTextContent(/0.*%/); expect(screen.getByTestId('dca-card-change')).not.toHaveTextContent('NaN');
    });
});

describe('DCA badge settled versus current data', () => {
    const item = (extra: Record<string, unknown> = {}): DcaSignalItem => ({ symbol: 'INTC', company_name: null, sources: [], in_watchlist: true, in_portfolio: false, min_level_override: null, effective_min_level: 2, alerts_on: true, state: { ...base.current!, previous_level: null, currency: 'USD', currency_label: null, metrics: {}, level_prices: {}, params_version: 'test', data_source: 'fixture', evaluated_at: '', last_alerted_level: null, last_alerted_period: null, ...extra } });
    const badge = (value: DcaSignalItem | undefined) => <LocaleProvider locale="en"><TooltipProvider><DcaLevelBadge item={value} signalMonths={null} /></TooltipProvider></LocaleProvider>;
    it('shows no evaluated level for a missing company record', () => { render(badge(undefined)); expect(screen.getByTestId('dca-missing-badge')).toBeInTheDocument(); expect(screen.queryByRole('button')).not.toBeInTheDocument(); });
    it('does not label settled data as live or stale and omits missing prices', () => {
        render(badge(item({ status: 'confirmed', close: null }))); const button = screen.getByRole('button'); fireEvent.click(button); expect(button).toHaveAttribute('aria-expanded', 'true'); expect(screen.queryByTestId('dca-badge-live')).not.toBeInTheDocument(); expect(screen.queryByTestId('dca-stale')).not.toBeInTheDocument(); expect(screen.queryByText(/2X.*3X/)).not.toBeInTheDocument();
    });
    it.each(['post', 'regular', 'future_session'])('labels live session %s even with no time and unknown stale age', session => {
        render(badge(item({ close_kind: 'live', live_price: 101, live_session: session, stale: true, data_age_days: null, status: 'confirmed' }))); fireEvent.click(screen.getByRole('button')); expect(screen.getAllByTestId('dca-badge-live')[0]).toHaveTextContent(/101/); expect(screen.getAllByTestId('dca-badge-live')[0]).toHaveTextContent('—'); expect(screen.getByTestId('dca-stale')).toBeInTheDocument();
    });
    it('does not invent a current price when the backend marks live but omits the value', () => {
        render(badge(item({ close_kind: 'live', live_price: null }))); fireEvent.click(screen.getByRole('button')); expect(screen.queryByTestId('dca-badge-live')).not.toBeInTheDocument();
    });
});
