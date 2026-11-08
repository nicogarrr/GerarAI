import { describe, expect, it } from 'vitest';
import { render, screen, within } from '@testing-library/react';

import { SotpBreakdownView } from '@/components/research/SotpBreakdownSection';
import { createFormatters } from '@/lib/format';
import { createTranslator } from '@/lib/i18n/translate';
import { sotpModelFromForm, type SotpResponse } from '@/lib/research/sotp';
import fixture from './sotp-asts.fixture.json';

const data = fixture as unknown as SotpResponse;
const es = createTranslator('es');
const tr = (key: string, vars?: Record<string, string | number>) => es(key as Parameters<typeof es>[0], vars);

function getter(values: Record<string, string>) {
  return (key: string) => values[key] ?? '';
}

describe('sotpModelFromForm', () => {
  it('convierte el formulario en el modelo (tasas y probabilidades en %, filas vacías fuera)', () => {
    const out = sotpModelFromForm(getter({
      base_year: '2026', valuation_year: '2030', discount_rate: '12,5', shares_current: '389,1',
      dil_label_0: 'Firefly', dil_shares_0: '12',
      part_name_0: 'EE. UU.', part_kind_0: 'operating', part_revenue_0: '1.350', part_ebitda_0: '1.188', part_multiple_0: '18',
      part_name_1: 'Espectro', part_kind_1: 'asset', part_value_1: '3.500', part_probability_1: '50',
      sc_label_0: 'Tasa 15 %', sc_discount_rate_0: '15', sc_stated_value_per_share_0: '142,5',
    }), { parts: 3, dilution: 2, scenarios: 2 }, tr);
    expect(out.ok).toBe(true);
    if (!out.ok) return;
    expect(out.model.discount_rate).toBeCloseTo(0.125);
    expect(out.model.parts).toHaveLength(2);
    expect(out.model.parts[0]).toMatchObject({ revenue: 1350, ebitda: 1188, multiple: 18, kind: 'operating' });
    expect(out.model.parts[1]).toMatchObject({ kind: 'asset', value: 3500, probability: 0.5, discounted: true });
    expect(out.model.dilution).toEqual([{ label: 'Firefly', shares: 12 }]);
    expect(out.model.scenarios[0]).toMatchObject({ label: 'Tasa 15 %', discount_rate: 0.15, stated_value_per_share: 142.5 });
  });

  it('dice qué falta en vez de guardar una parte incompleta', () => {
    const out = sotpModelFromForm(getter({ base_year: '2026', valuation_year: '2030', discount_rate: '10', shares_current: '10', part_name_0: 'X', part_ebitda_0: '5' }), { parts: 1, dilution: 0, scenarios: 0 }, tr);
    expect(out).toMatchObject({ ok: false, field: 'part_multiple_0', message: 'X: falta el múltiplo.' });
    const none = sotpModelFromForm(getter({ base_year: '2026', valuation_year: '2030', discount_rate: '10', shares_current: '10' }), { parts: 2, dilution: 0, scenarios: 0 }, tr);
    expect(none).toMatchObject({ ok: false, field: 'part_name_0' });
  });
});

describe('SotpBreakdownView', () => {
  it('muestra la tabla con su aritmética, el total y, al lado, la etiqueta y la tasa base', () => {
    render(<SotpBreakdownView data={data} t={createTranslator('es')} fmt={createFormatters('es')} locale="es" ticker="ASTS" />);
    expect(screen.getByTestId('sotp-unvalidated').textContent).toBe('Supuestos del usuario, no validados contra histórico');
    expect(screen.getByTestId('sotp-base-rate').textContent).toContain('quema caja');
    expect(screen.getByTestId('sotp-total').textContent).toContain('155,82');
    const table = screen.getByRole('table');
    expect(within(table).getByText('AST Defense (radar, DoD, OTAN)')).toBeTruthy();
    expect(table.textContent).toContain('× 18x = 21.384 M en 2030');
    expect(table.textContent).toContain('41,48');
    expect(screen.getByText(/Borrador de ejemplo con los supuestos de Nico/)).toBeTruthy();
    const sens = screen.getByTestId('sotp-sensitivity');
    expect(sens.textContent).toContain('Múltiplos −30 %');
    expect(sens.textContent).toContain('111,00');
    expect(screen.getByText('Sin parámetros: no calculado')).toBeTruthy();
  });

  it('en inglés usa los textos en inglés', () => {
    render(<SotpBreakdownView data={data} t={createTranslator('en')} fmt={createFormatters('en')} locale="en" ticker="ASTS" />);
    expect(screen.getByTestId('sotp-unvalidated').textContent).toBe('User assumptions, not validated against history');
    expect(screen.getByTestId('sotp-base-rate').textContent).toContain('burns cash');
  });
});
