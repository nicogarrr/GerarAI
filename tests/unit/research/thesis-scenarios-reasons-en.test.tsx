import { readFileSync } from 'node:fs';
import { render } from '@testing-library/react';
import { beforeAll, describe, expect, it } from 'vitest';

import { ThesisScenariosPanel } from '@/components/research/ThesisScenariosPanel';
import type { ThesisScenarios } from '@/lib/actions/thesis-scenarios.actions';
import { scenarioReasonText } from '@/lib/research/thesis-scenarios-text';

// Motivos de celda N/D que thesis_scenario_service.py (_view y _lineage_reason)
// manda en castellano; el panel los pinta como title y texto para lector de
// pantalla. Las frases se leen del .py: si cambian allí, este test avisa.
const SERVICE = readFileSync('data-engine/app/services/thesis_scenario_service.py', 'utf8');
const REASONS = [...SERVICE.matchAll(/(?:row_reason|blocked) = "([^"]+)"|return "([^"]+)"/g)].map((m) => m[1] ?? m[2]);

beforeAll(() => {
  window.matchMedia ??= ((query: string) => ({ matches: false, media: query, onchange: null, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {}, dispatchEvent: () => false })) as unknown as typeof window.matchMedia;
});

const SPANISH = /\b(Falta|Faltan|Fila|cadena|ejercicio|linaje|cifra|traza|etiquetada|ancla|anclas|fecha de corte|acreditado|ingresos|acciones)\b/;

describe('thesis scenarios: N/D cell reasons in English', () => {
  it('reads every cell reason the backend sends', () => {
    expect(REASONS.length).toBe(13);
    expect(REASONS).toContain('Falta la fecha de corte.');
    expect(REASONS).toContain('La cifra anual no coincide con la traza de esta versión.');
  });

  it('each backend reason has an English version and stays as is in Spanish', () => {
    for (const reason of REASONS) {
      const en = scenarioReasonText(reason, 'en');
      expect(en, reason).not.toBe(reason);
      expect(en, reason).not.toMatch(SPANISH);
      expect(scenarioReasonText(reason, 'es')).toBe(reason);
    }
    expect(scenarioReasonText('otro motivo', 'en')).toBe('otro motivo');
  });

  it('the panel shows a blocked cell in English: N/A, not «N/D», and the reason in English', () => {
    const blocked = (motivo: string) => ({ valor: null, etiqueta: 'N/D', motivo });
    const ok = { valor: 100, etiqueta: 'INFERIDO', motivo: null };
    const row = (motivo: string) => ({ ejercicio: 2027, ingresos: ok, fcf: blocked(motivo), bps: blocked('Faltan resultado neto o acciones OFICIALES con fuente y fecha.') });
    const data = {
      ticker: 'AAPL', estado: 'persistido', motivo: null,
      fuente: { tabla: 'thesis_projection_years', valuation_model_id: 1, version: 3, modelo: 'thesis-5y', fecha: '2026-10-01' },
      escenarios: {
        bear: { nombre: 'Pesimista', motivo: null, proyecciones: [row('Falta el ancla FCF OFICIAL con fuente y fecha.')] },
        base: { nombre: 'Central', motivo: null, proyecciones: [row('Las anclas de FCF e ingresos no corresponden al mismo ejercicio.')] },
        bull: { nombre: 'Optimista', motivo: null, proyecciones: [row('Margen FCF ausente o sin linaje determinista acreditado (puede incluir inputs LLM).')] },
      },
      aviso_coherencia: null,
    } as unknown as ThesisScenarios;
    const { container } = render(<ThesisScenariosPanel adrRatio={null} currency="USD" data={data} locale="en" />);
    expect(container.textContent).not.toContain('N/D');
    expect(container.textContent).not.toMatch(SPANISH);
    expect(container.textContent).toContain('The OFFICIAL FCF anchor with source and date is missing.');
    const titles = [...container.querySelectorAll('td[title]')].map((cell) => cell.getAttribute('title') ?? '');
    expect(titles).toContain('OFFICIAL net income or shares with source and date are missing.');
    expect(titles.join(' ')).not.toMatch(SPANISH);
  });

  it('in Spanish the blocked cell keeps the backend text', () => {
    const blocked = { valor: null, etiqueta: 'N/D', motivo: 'Falta la fecha de corte.' };
    const data = {
      ticker: 'AAPL', estado: 'persistido', motivo: null, fuente: { modelo: 'thesis-5y', version: 1, fecha: '2026-10-01' },
      escenarios: Object.fromEntries((['bear', 'base', 'bull'] as const).map((key) => [key, { nombre: 'Central', motivo: null, proyecciones: [{ ejercicio: 2027, ingresos: blocked, fcf: blocked, bps: blocked }] }])),
      aviso_coherencia: null,
    } as unknown as ThesisScenarios;
    const { container } = render(<ThesisScenariosPanel adrRatio={null} currency="USD" data={data} />);
    expect(container.textContent).toContain('Falta la fecha de corte.');
  });
});
