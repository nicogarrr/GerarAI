import { render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { OwnershipSignalsPanel } from '@/components/research/OwnershipSignalsPanel';
import { holderChangeLabel, holdersLines, insiderLines, ownershipMoney, type OwnershipSignals } from '@/lib/research/ownership-signals';

const signals: OwnershipSignals = {
    ticker: 'MSFT',
    insider: {
        status: 'ok', window_days: 90, source: 'SEC', net_value: -50000, cluster_buying: false, last_date: '2026-10-20', reading: 'Neutral',
        buys: { trades: 1, insiders: 1, shares: 10, value: 10000 },
        sells: { trades: 3, insiders: 2, shares: 30, value: 60000, planned_10b5_1: 2 },
    },
    holders: {
        status: 'ok', source: '13F', holders_count: 12, managers_with_data: 40, report_date: '2026-06-30', total_value_usd: 113100,
        changes: { new: 2, increased: 3, decreased: 1, closed: 1 },
        top_holders: [{ name: 'Fund A', value_usd: 50000, change: 'new' }],
        exited: ['Fund Z'], limitations: [],
    },
};

beforeEach(() => { vi.stubGlobal('matchMedia', () => ({ matches: false, addEventListener() {}, removeEventListener() {} })); });
afterEach(() => vi.unstubAllGlobals());

describe('ownership signals in English', () => {
    it('lines and labels', () => {
        expect(ownershipMoney(113100, 'en')).toBe('$113,100');
        expect(holderChangeLabel('decreased', 'en')).toBe('trims');
        expect(holderChangeLabel(null, 'en')).toBe('no comparison');
        expect(insiderLines(signals.insider, 'en')).toEqual([
            'Buys: 1 by 1 insider for $10,000.',
            'Sells: 3 by 2 insiders for $60,000 (2 under a 10b5-1 plan).',
            'Net: -$50,000 · last trade 2026-10-20.',
        ]);
        expect(holdersLines(signals.holders, 'en')).toEqual([
            '12 of 40 managers reviewed report it (13F for 2026-06-30) worth $113,100.',
            'Versus the previous quarter: 2 new, 3 adding, 1 trimming, 1 exiting.',
            'Exiting: Fund Z.',
        ]);
        expect(insiderLines({ status: 'sin_datos' }, 'en')).toEqual(['No insider data.']);
    });

    it('Spanish stays the default', () => {
        expect(holderChangeLabel('new')).toBe('nueva posición');
        expect(insiderLines(signals.insider)[0]).toMatch(/^Compras: 1 de 1 insiders por/);
    });

    it('panel', () => {
        render(<OwnershipSignalsPanel locale="en" signals={signals} ticker="MSFT" />);
        expect(screen.getAllByText('What insiders and large funds are buying and selling').length).toBeGreaterThan(0);
        expect(screen.getByText('Insider buys and sells (Form 4) · 90 days')).toBeInTheDocument();
        expect(screen.getByText('12 managers')).toBeInTheDocument();
        expect(screen.getByText('Fund A: $50,000 (new position)')).toBeInTheDocument();
        expect(screen.getByRole('link', { name: 'View owners' })).toHaveAttribute('href', '/research/MSFT?view=holders');
        expect(screen.queryByText(/directivos|gestores/)).toBeNull();
    });

    it('panel when the summary failed', () => {
        render(<OwnershipSignalsPanel locale="en" signals={null} ticker="MSFT" />);
        expect(screen.getByText('The insider and 13F summary couldn’t be loaded right now.')).toBeInTheDocument();
    });
});
