/**
 * Insider: la lista de filings pintaba el formulario SEC a pelo («4») mientras
 * las señales ya lo rotulan con formBadge («Form 4»). Regresión: la lista usa
 * el mismo rotulo; la enmienda no se duplica (badge «Form 4/A» + badge
 * «Enmienda», nunca «Enmienda 4/A» + «Enmienda»).
 */
import { readFileSync } from 'node:fs';
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn(), refresh: vi.fn(), replace: vi.fn() }) }));
vi.mock('@/lib/actions/insider.actions', () => ({ loadMoreInsiderFilings: vi.fn() }));
vi.mock('@/components/search/TickerSearchInput', () => ({ TickerSearchInput: () => <div /> }));

import InsiderSignalsView from '@/components/insider/InsiderSignalsView';
import type { InsiderFilingEntry, InsiderFilingsResult, InsiderSignalsResult } from '@/lib/actions/insider.actions';

const signals = (): InsiderSignalsResult => ({
    ticker: 'ASTS', status: 'ok', filings_scanned: 1, filings_parsed: 1, filings_failed: 0, buy_count: 0,
    sell_count: 0, net_buyers_90d: 0, buys: [], sells: [], top_buyers: [], top_sellers: [], transactions: [],
} as unknown as InsiderSignalsResult);

const filing = (over: Partial<InsiderFilingEntry> = {}): InsiderFilingEntry => ({
    accession_number: 'acc-1', form: '4', is_amendment: false, filing_date: '2026-10-01', source_url: 'https://sec.gov/x', transactions: [], ...over,
} as unknown as InsiderFilingEntry);

const filings = (list: InsiderFilingEntry[]): InsiderFilingsResult =>
    ({ ticker: 'ASTS', status: 'ok', count: list.length, total: list.length, filings: list }) as unknown as InsiderFilingsResult;

describe('filings insider: formulario rotulado como en las señales', () => {
    it('«4» se lee «Form 4», nunca el dígito a pelo', () => {
        render(<InsiderSignalsView initialTicker="ASTS" initialResult={signals()} initialFilings={filings([filing()])} />);
        expect(screen.getByText('Form 4')).toBeInTheDocument();
    });
    it('enmienda: «Form 4/A» más el badge de enmienda, sin duplicar el texto', () => {
        render(<InsiderSignalsView initialTicker="ASTS" initialResult={signals()} initialFilings={filings([filing({ form: '4/A', is_amendment: true })])} />);
        expect(screen.getByText('Form 4/A')).toBeInTheDocument();
        expect(screen.queryByText(/Enmienda 4\/A/)).toBeNull();
    });
    it('la lista deja de pintar {filing.form} en crudo', () => {
        const source = readFileSync('components/insider/InsiderSignalsView.tsx', 'utf8');
        expect(source).not.toContain('<Badge variant="outline">{filing.form}</Badge>');
    });
});
