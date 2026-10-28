import { render, screen } from '@testing-library/react';
import { expect, it } from 'vitest';
import BlockedValuation from '@/components/research/BlockedValuation';
import type { ResearchValuation } from '@/lib/actions/research.actions';
const valuation: ResearchValuation = { ticker: 'ASTS', model_type: 'standard_dcf', status: 'insufficient_data', current_price: null, bear_value: null, base_value: null, bull_value: null, expected_value: null, margin_of_safety: null, reverse_dcf: {}, sensitivity: {}, trace: {} };
it('explica el margen negativo, conserva periodo/procedencia y ofrece salidas sin inventar un precio', () => {
    const input = { ...valuation, missing_inputs: ['non_negative_fcf_margin'], trace: { input_source: 'financial_facts', periods: { fcf_margin: '2025-FY' }, fact_ids: { fcf_margin: 123 } } };
    const before = JSON.stringify(input);
    render(<BlockedValuation valuation={input} ticker="ASTS" />);
    expect(screen.getByText(/no fuerces un margen positivo/)).toBeInTheDocument();
    expect(screen.getByText(/2025-FY/)).toHaveTextContent('#123');
    expect(screen.getByRole('link', { name: 'Revisar datos y fuentes' })).toHaveAttribute('href', '/research/ASTS?view=financials');
    expect(screen.getByRole('link', { name: 'Revisar supuestos' })).toHaveAttribute('href', '/research/ASTS?view=supuestos');
    expect(screen.getByRole('link', { name: 'Ver modelo a largo plazo' })).toHaveAttribute('href', '/research/ASTS?view=model');
    expect(JSON.stringify(input)).toBe(before);
});
it('no presenta insufficient_data como una fuente y no inventa periodos', () => {
    render(<BlockedValuation valuation={{ ...valuation, trace: { input_source: 'insufficient_data' } }} ticker="A/B" />);
    expect(screen.getByText(/Fuente de las entradas/)).toHaveTextContent('no especificada');
    expect(screen.getByText(/Periodos:/)).toHaveTextContent('no registrados');
    expect(screen.getByRole('link', { name: 'Revisar datos y fuentes' })).toHaveAttribute('href', '/research/A%2FB?view=financials');
});
