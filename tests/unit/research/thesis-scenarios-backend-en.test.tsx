import { readFileSync } from 'node:fs';
import { render, screen } from '@testing-library/react';
import { beforeAll, describe, expect, it } from 'vitest';

import { ThesisScenariosPanel } from '@/components/research/ThesisScenariosPanel';
import type { ThesisScenarios } from '@/lib/actions/thesis-scenarios.actions';
import { scenarioCoherenceText, scenarioNameText } from '@/lib/research/thesis-scenarios-text';

// thesis_scenario_service.py manda los nombres de escenario en castellano
// (TITLES) y thesis_projection_service.py el aviso de coherencia. Si cambian
// allí, este test avisa de que la versión inglesa se ha quedado atrás.
const WARNING = (problems: string) => `los escenarios no quedan ordenados bear <= base <= bull en ${problems}; se muestran los valores calculados, sin reordenar`;

beforeAll(() => {
  window.matchMedia ??= ((query: string) => ({ matches: false, media: query, onchange: null, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {}, dispatchEvent: () => false })) as unknown as typeof window.matchMedia;
});

describe('thesis scenarios: backend texts in English', () => {
  it('the backend still sends these texts', () => {
    expect(readFileSync('data-engine/app/services/thesis_scenario_service.py', 'utf8')).toContain('TITLES = {"bear": "Pesimista", "base": "Central", "bull": "Optimista"}');
    const projection = readFileSync('data-engine/app/services/thesis_projection_service.py', 'utf8').replace(/"\s*\n\s*f"/g, '');
    expect(projection).toContain(`f"${WARNING("{' y '.join(problems)}")}"`);
    expect(projection).toContain('problems.append("precio objetivo")');
    expect(projection).toContain('problems.append("ingresos proyectados")');
  });

  it('names and coherence warning are translated in English and kept in Spanish', () => {
    expect(scenarioNameText('Pesimista', 'en')).toBe('Bear');
    expect(scenarioNameText('Central', 'en')).toBe('Base');
    expect(scenarioNameText('Optimista', 'en')).toBe('Bull');
    expect(scenarioNameText('Optimista', 'es')).toBe('Optimista');
    expect(scenarioCoherenceText(WARNING('precio objetivo y ingresos proyectados'), 'en'))
      .toBe('scenarios are not ordered bear <= base <= bull in target price and projected revenue; the computed values are shown, not reordered');
    expect(scenarioCoherenceText(WARNING('precio objetivo'), 'es')).toBe(WARNING('precio objetivo'));
    expect(scenarioCoherenceText('otro aviso', 'en')).toBe('otro aviso');
  });

  it('the panel shows a real backend payload in English', () => {
    const cell = (value: number | null) => ({ valor: value, unidad: 'USD', estado: value === null ? 'N/D' : 'calculado' });
    const data = {
      ticker: 'AAPL', estado: 'persistido', motivo: null, fuente: { modelo: 'thesis-5y', version: 'v1', fecha: '2026-10-01' },
      escenarios: {
        bear: { nombre: 'Pesimista', proyecciones: [{ ejercicio: 2027, ingresos: cell(300), fcf: cell(null), bps: cell(null) }] },
        base: { nombre: 'Central', proyecciones: [{ ejercicio: 2027, ingresos: cell(200), fcf: cell(null), bps: cell(null) }] },
        bull: { nombre: 'Optimista', proyecciones: [{ ejercicio: 2027, ingresos: cell(100), fcf: cell(null), bps: cell(null) }] },
      },
      aviso_coherencia: WARNING('ingresos proyectados'),
      disclaimer: 'x',
    } as unknown as ThesisScenarios;
    const { container } = render(<ThesisScenariosPanel adrRatio={null} currency="USD" data={data} locale="en" />);
    expect(screen.getAllByRole('columnheader', { name: 'Bear' }).length).toBeGreaterThan(0);
    expect(screen.getAllByRole('columnheader', { name: 'Bull' }).length).toBeGreaterThan(0);
    expect(screen.getByText(/in projected revenue; the computed values are shown/)).toBeTruthy();
    expect(container.textContent).not.toMatch(/Pesimista|Optimista|escenarios no quedan|ingresos proyectados/);
  });
});
