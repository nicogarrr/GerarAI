import { describe, expect, it, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';

import { SotpBreakdownView } from '@/components/research/SotpBreakdownSection';
import { createFormatters } from '@/lib/format';
import { createTranslator } from '@/lib/i18n/translate';
import { sotpModelFromForm, type SotpResponse } from '@/lib/research/sotp';
import fixture from './sotp-asts.fixture.json';
import agentsFixture from './sotp-agents-asts.fixture.json';

vi.mock('next/navigation', () => ({ useRouter: () => ({ refresh: vi.fn() }) }));

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

  it('propuesta de los agentes: etiqueta con fecha y precio, versiones, razones y fuentes por parte', () => {
    const agents = agentsFixture as unknown as SotpResponse;
    render(<SotpBreakdownView data={agents} t={createTranslator('es')} fmt={createFormatters('es')} locale="es" ticker="ASTS" />);
    expect(screen.getByTestId('sotp-unvalidated').textContent).toBe('Propuesta de los agentes, no validada contra histórico');
    expect(screen.getByTestId('sotp-agents-label').textContent).toContain('32,33');
    expect(screen.getByTestId('sotp-agents-label').textContent).toContain('2026');
    const nav = screen.getByRole('navigation', { name: 'Versiones del desglose' });
    expect(within(nav).getByText(/Propuesta de los agentes · por defecto/)).toBeTruthy();
    expect(within(nav).getByRole('link', { name: 'Ejemplo pegado por Nico' }).getAttribute('href')).toBe('/research/ASTS?view=valuation&sotp=example#desglose-partes');
    expect(screen.getByTestId('sotp-summary').textContent?.length).toBeGreaterThan(40);
    expect(screen.getAllByText('¿De dónde sale?').length).toBeGreaterThan(3);
    expect(screen.getAllByText(/Caja menos deuda/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/aún no factura/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/CAPM de GerarAI/).length).toBeGreaterThan(0);
    expect(screen.getByRole('button', { name: 'Regenerar solo el desglose' })).toBeTruthy();
    expect(screen.getByTestId('sotp-warnings').textContent).toContain('infravalorado por falta de estimaciones');
    expect(screen.getByTestId('sotp-unvalued').textContent).toContain('financiación o inversión');
    expect(screen.getByTestId('sotp-total').textContent).toContain('4,80');
    expect(screen.queryByTestId('sotp-no-agents')).toBeNull();
    // La tasa base y la sensibilidad siguen siempre al lado.
    expect(screen.getByTestId('sotp-base-rate')).toBeTruthy();
    expect(screen.getByTestId('sotp-sensitivity').textContent).toContain('Múltiplos −30 %');
  });

  it('dos propuestas de los agentes que difieren más de un 30 %: «resultado sensible a supuestos»', () => {
    const agents = { ...(agentsFixture as unknown as SotpResponse), agents_stability: { previous_value_per_share: 6.13, current_value_per_share: 2.81, change: -0.542, unstable: true, threshold: 0.3 } };
    render(<SotpBreakdownView data={agents} t={createTranslator('es')} fmt={createFormatters('es')} locale="es" ticker="ASTS" />);
    expect(screen.getByTestId('sotp-unstable').textContent).toContain('Resultado sensible a supuestos');
    expect(screen.getByTestId('sotp-unstable').textContent).toContain('6,13');
  });

  it('sin valorar, dos lecturas distintas y qué dato lo cambió: todo a la vista', () => {
    const base = agentsFixture as unknown as SotpResponse;
    const agents = { ...base, model: { ...base.model!, unvalued: [{ name: 'Japón (J-LEO)', status: 'beta', reason: 'sin cifra de ingresos en la evidencia' }] }, agents: { ...base.agents, readings_differ: true, readings: [{ value_per_share: 3.1 }, { value_per_share: 4.4 }], changed_by: ['nuevo: 8-K 6-nov-2026'] } } as SotpResponse;
    render(<SotpBreakdownView data={agents} t={createTranslator('es')} fmt={createFormatters('es')} locale="es" ticker="ASTS" />);
    expect(screen.getByTestId('sotp-unvalued').textContent).toContain('Japón (J-LEO) — sin cifra de ingresos en la evidencia');
    expect(screen.getByTestId('sotp-readings').textContent).toContain('se muestra la más conservadora');
    expect(screen.getByTestId('sotp-changed-by').textContent).toBe('Cambió por un dato nuevo: nuevo: 8-K 6-nov-2026');
  });

  it('tesis larga de los expertos y aviso de «casi todo caja» bien visibles', () => {
    const base = agentsFixture as unknown as SotpResponse;
    const agents = { ...base, agents: { ...base.agents, mostly_cash: { cash_per_share: 3.95, value_per_share: 4.8, share: 0.823 }, narrative: { status: 'ok', version: 'sotp-narrative-v1', sections: [{ key: 'resumen', title: 'Resumen', text: 'El desglose da 4,80 $ por acción frente a 32,33 $.' }, { key: 'conclusion', title: 'Conclusión', text: 'Sin estimaciones el negocio principal no se puede valorar.' }] } } } as SotpResponse;
    render(<SotpBreakdownView data={agents} t={createTranslator('es')} fmt={createFormatters('es')} locale="es" ticker="ASTS" />);
    const cash = screen.getByTestId('sotp-mostly-cash').textContent ?? '';
    expect(cash).toContain('3,95');
    expect(cash).toContain('no es un valor razonable');
    const narrative = screen.getByTestId('sotp-narrative');
    expect(within(narrative).getByRole('heading', { name: 'Tesis de los expertos sobre el desglose' })).toBeTruthy();
    expect(within(narrative).getByText('El desglose da 4,80 $ por acción frente a 32,33 $.')).toBeTruthy();
    expect(within(narrative).getByText('Conclusión')).toBeTruthy();
  });

  it('sin propuesta de los agentes lo dice, con el motivo del último intento, y ofrece generarla', () => {
    const withStatus = { ...data, variants: [{ key: 'agents', label: 'Propuesta de los agentes', available: false }, { key: 'example', label: 'Ejemplo pegado por Nico', available: true }], agents_status: { source: 'thesis', run_id: 1, job_status: 'succeeded', status: 'rejected', problems: ['falta el escenario bajista'] } } as unknown as SotpResponse;
    render(<SotpBreakdownView data={withStatus} t={createTranslator('es')} fmt={createFormatters('es')} locale="es" ticker="ASTS" />);
    expect(screen.getByTestId('sotp-no-agents').textContent).toBe('Sin propuesta de los agentes todavía. Último intento: falta el escenario bajista');
    expect(screen.getByRole('button', { name: 'Generar con expertos' })).toBeTruthy();
  });
});
