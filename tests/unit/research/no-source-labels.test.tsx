import { renderToStaticMarkup } from 'react-dom/server';
import fs from 'node:fs';
import { FinancialTerminalSection, type FinancialTerminalData } from '@/components/research/sections/FinancialTerminalSection';
import { expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import type { ResearchFact } from '@/lib/actions/research.actions';
import { FactSource } from '@/components/research/FactSource';
import { isUnofficialSource } from '@/lib/research/source-quality';
it('removes provider branding but preserves evidence links and unofficial warning', () => {
 const fact = {source_type:'YAHOO_FUNDAMENTALS',source_title:'Annual report',source_url:'https://example.com/report',source_published_at:'2026-01-01'} as ResearchFact;
 render(<FactSource fact={fact} locale="en"/>);
 if (process.env.SOURCE_VISUAL_HTML) fs.writeFileSync(process.env.SOURCE_VISUAL_HTML, renderToStaticMarkup(<FactSource fact={fact} locale="en"/>));
 expect(document.body.textContent).not.toMatch(/Yahoo|YAHOO|Source:/);
 expect(screen.getByText(/Includes unofficial figures/)).toBeTruthy();
 expect(screen.getByRole('link',{name:'Annual report'})).toHaveAttribute('href',fact.source_url);
});
it('does not invent unofficial status for unknown or missing sources', () => {
 for(const value of [null,undefined,'','sec','unknown','constructor']) expect(isUnofficialSource(value)).toBe(false);
 expect(isUnofficialSource(' YAHOO_FUNDAMENTALS ')).toBe(true);
});

it('keeps unknown statuses, missing values and partial history honest', () => {
    const point = (id: number, period: string, value: number | null, unit: string, status: string | null = 'new_status') => ({ id, period, value, unit, status, segment: 'consolidated', confidence: null, source: { title: null, type: 'sec' } });
    const metric = (metric: string, series: unknown[], extra = {}) => ({ metric, status: 'missing', definition: '', canonical_formula: 'revenue - capex', periods: series.length, segments: [], series, ...extra });
    const input = { coverage: { percent: 0, available: 0, requested: 5 }, periodicity: '', metrics: [
        metric('revenue', [point(1, 'FY2020', -5, 'USD'), point(2, 'FY2025', 10, 'USD')]),
        metric('margin', [point(3, 'FY2020', 0.2, 'decimal'), point(4, 'FY2025', 0.3, 'decimal')]),
        metric('fcf', [point(5, 'unknown', null, 'USD'), point(6, 'FY2025', 2, '', null)]),
        metric('cash', [], { missing_reason: 'Pending filing' }),
    ] } as unknown as FinancialTerminalData;
    render(<FinancialTerminalSection terminal={input} periodicity="all" years={5} />);
    expect(screen.getByText('Pending filing')).toBeInTheDocument();
    expect(screen.getAllByText('new status').length).toBeGreaterThan(0);
    expect(screen.getAllByTestId('terminal-annual-summary')).toHaveLength(2);
    expect(document.body.textContent).toContain('no aplica a ratios');
    expect(document.body.textContent).toContain('no se calcula');
});

it('removes the terminal source column without losing the unofficial-data warning', () => {
 const terminal = { coverage:{percent:100,available:1,requested:1},periodicity:'annual',metrics:[{metric:'revenue',status:'available',definition:'Revenue',canonical_formula:null,periods:1,segments:[],series:[{id:1,period:'FY2025',value:100,unit:'USD',status:'reported',segment:'consolidated',confidence:1,source:{type:'YAHOO_FUNDAMENTALS',title:'Provider brand'}}]}]} as unknown as FinancialTerminalData;
 render(<FinancialTerminalSection terminal={terminal} years={5} periodicity="annual" locale="en"/>);
 expect(screen.queryByRole('columnheader',{name:'Source'})).toBeNull();
 expect(document.body.textContent).not.toMatch(/Provider brand|YAHOO_FUNDAMENTALS/);
 expect(screen.getByText(/Includes unofficial figures/)).toBeTruthy();
});
