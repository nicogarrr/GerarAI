import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';

import { AnalystReportView } from '@/components/research/AnalystReportView';
import { createFormatters } from '@/lib/format';
import { createTranslator } from '@/lib/i18n/translate';
import type { ReportInputs } from '@/lib/research/analyst-report';
import fixture from './analyst-report-asts.fixture.json';

// r5-front3: sin consulta guardada, el motivo del backend dice «Usa Actualizar para consultar la fuente
// pública», pero el Informe no tiene botón Actualizar (está en /research/T/shorts). El Informe dice el
// hecho y enlaza a la página de cortos.
const base = fixture as unknown as ReportInputs;
const view = (patch: Partial<ReportInputs> = {}, locale: 'es' | 'en' = 'es') =>
  render(<AnalystReportView data={{ ...base, ...patch }} t={createTranslator(locale)} fmt={createFormatters(locale)} locale={locale} />);
const EMPTY = { ticker: 'ASTS', status: 'empty', fetched_at: null, reason: 'No hay consulta almacenada. Usa Actualizar para consultar la fuente pública.', data: null };

describe('Informe: volumen en corto sin consulta guardada', () => {
  it('no manda a un botón «Actualizar» que aquí no existe; enlaza a la página de cortos', () => {
    view({ shorts: EMPTY });
    const cell = screen.getByTestId('informe-short-volume');
    expect(cell.textContent).toContain('No hay consulta almacenada');
    expect(cell.textContent).not.toMatch(/Usa Actualizar/);
    const link = screen.getByTestId('informe-short-volume-link');
    expect(link.getAttribute('href')).toBe(`/research/${encodeURIComponent(base.ticker)}/shorts`);
    expect(link.textContent).toContain('Cortos públicos');
  });
  it('dato desfasado: conserva el motivo de la fuente y ofrece el mismo enlace', () => {
    view({ shorts: { ...EMPTY, status: 'stale', reason: 'Consulta o fecha de negociación fuera del límite de 4 días.', data: { source: 'FINRA', source_url: 'https://x', note: '' } } as ReportInputs['shorts'] });
    expect(screen.getByTestId('informe-short-volume').textContent).toContain('fuera del límite de 4 días');
    expect(screen.getByTestId('informe-short-volume-link')).toBeTruthy();
  });
  it('en inglés el motivo sale traducido y sin «Use Refresh»', () => {
    view({ shorts: EMPTY }, 'en');
    const cell = screen.getByTestId('informe-short-volume');
    expect(cell.textContent).toContain('No stored lookup');
    expect(cell.textContent).not.toMatch(/Usa Actualizar|Use Refresh/);
  });
  it('con cifra o sin lectura no hay enlace de consulta', () => {
    view({ shorts: null });
    expect(screen.queryByTestId('informe-short-volume-link')).toBeNull();
  });
});
