import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('@/lib/actions/research.actions', () => ({ refreshCompanyFinancialsSEC: vi.fn() }));

import { FinancialTerminalSection, type FinancialTerminalData } from '@/components/research/sections/FinancialTerminalSection';

const terminal = {
    coverage: { percent: 62, available: 5, requested: 8 },
    periodicity: 'annual',
    metrics: [],
} as unknown as FinancialTerminalData;

describe('terminal financiero: cabecera explicada', () => {
    it('explica qué miden la cobertura y las métricas disponibles', () => {
        render(<FinancialTerminalSection periodicity="annual" terminal={terminal} years={10} />);
        const note = screen.getByTestId('terminal-coverage-explainer');
        expect(note).toHaveTextContent('porcentaje de las métricas pedidas que tienen datos');
        expect(note).toHaveTextContent('con datos de las pedidas');
    });
    it('lo explica también en inglés', () => {
        render(<FinancialTerminalSection locale="en" periodicity="annual" terminal={terminal} years={10} />);
        const note = screen.getByTestId('terminal-coverage-explainer');
        expect(note).toHaveTextContent('share of the requested metrics that have data');
        expect(note).not.toHaveTextContent('Cobertura');
    });
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
    expect(screen.getByTestId('terminal-coverage-explainer')).toBeInTheDocument();
    expect(screen.getAllByTestId('terminal-annual-summary')).toHaveLength(2);
    expect(document.body.textContent).toContain('no aplica a ratios');
    expect(document.body.textContent).toContain('no se calcula');
});

it('renders unknown statuses, unavailable values and ratio or negative annual summaries', () => {
    const point = {id:1,period:'FY2024',value:1,unit:'USD',status:'',segment:'consolidated',confidence:1,source:{title:null,type:'sec'}};
    const metric = {metric:'custom_metric',status:'custom_state',definition:'',canonical_formula:'a + b',periods:2,segments:[],missing_reason:null,series:[point]};
    const fixtures = [
        {...metric,series:[{...point,value:null},{...point,id:2,value:'bad'},{...point,id:3,value:1,unit:''}]},
        {...metric,series:[{...point,value:-1},{...point,id:2,period:'FY2025',value:2}]},
        {...metric,series:[{...point,unit:'ratio'},{...point,id:2,period:'FY2025',unit:'ratio',value:2}]},
        {...metric,missing_reason:'Missing input',series:[{...point,period:'unknown',value:null}]},
    ];
    render(<FinancialTerminalSection terminal={{...terminal,periodicity:'custom_period',metrics:fixtures.map((item,index)=>({...item,metric:'custom_'+index}))} as unknown as FinancialTerminalData} years={10} periodicity="annual"/>);
    expect(screen.getAllByText('custom state')).toHaveLength(4);
    expect(screen.getByText('Missing input')).toBeInTheDocument();
    expect(screen.getAllByTestId('terminal-annual-summary')).toHaveLength(2);
});
