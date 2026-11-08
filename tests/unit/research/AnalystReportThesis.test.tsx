import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { AnalystReportThesis } from '@/components/research/AnalystReportThesis';
import { translateMessage } from '@/lib/i18n/translate';
import { hasRows, safeLink, thesisParagraphs, type ThesisV2 } from '@/lib/research/thesis-v2';

const t = ((key: string, vars?: Record<string, string | number>) => translateMessage('es', key, vars)) as Parameters<typeof AnalystReportThesis>[0]['t'];

const thesis: ThesisV2 = {
  status: 'ok', ticker: 'ERF.PA', company: 'Eurofins Scientific SE', version: 'thesis-v2-1', as_of: '2026-11-08',
  fingerprint: 'f'.repeat(64), probability_choice: 'simetrico', probability_reason: 'colas por igual', llm_calls: 2,
  headline: { price: '88,64 €', tir5: '5,5 %', tir10: '5,9 %', base_tir10: '4,9 %', multiple: '15,8x', peers_median: 'N/D', cost_of_equity: '8,1 %' },
  sections: [
    { key: 'introduccion', title: '1. Introducción', text: 'Primer párrafo.\n\nSegundo párrafo.', tables: [
      { title: 'Punto de partida normalizado', head: ['Concepto', 'Valor', 'Fuente'], rows: [['Precio', '88,64 €', 'Cierre'], ['Acciones', '194,0 M', '10-K 2025']],
        links: [null, 'https://www.sec.gov/Archives/edgar/data/1/000000000026000001/'] },
      { title: '', head: [], rows: [] },
    ] },
    { key: 'conclusion', title: '15. Conclusión', text: 'Cierre.', tables: [] },
  ],
  warnings: ['acciones: derivadas de beneficio / BPA'], sources: ['Eurofins Scientific Annual Report 2025'],
};

describe('AnalystReportThesis', () => {
  it('pinta cabecera, secciones con párrafos, tablas del código, avisos y fuentes', () => {
    render(<AnalystReportThesis thesis={thesis} t={t} />);
    const root = screen.getByTestId('informe-tesis-v2');
    expect(root.className).toContain('print-document');
    expect(within(screen.getByTestId('tesis-v2-headline')).getByText('5,9 %')).toBeTruthy();
    expect(screen.getByRole('heading', { name: '1. Introducción' })).toBeTruthy();
    expect(screen.getByText('Segundo párrafo.')).toBeTruthy();
    expect(screen.getByRole('table', { name: 'Punto de partida normalizado' })).toBeTruthy();
    expect(screen.getAllByRole('table')).toHaveLength(1);
    expect(screen.getByRole('link', { name: '10-K 2025' }).getAttribute('href')).toBe('https://www.sec.gov/Archives/edgar/data/1/000000000026000001/');
    expect(screen.queryByRole('link', { name: 'Cierre' })).toBeNull();
    expect(screen.getByText('acciones: derivadas de beneficio / BPA')).toBeTruthy();
    expect(screen.getByText(/Eurofins Scientific Annual Report 2025/)).toBeTruthy();
  });

  it('sin tesis no pinta nada', () => {
    const { container } = render(<AnalystReportThesis thesis={null} t={t} />);
    expect(container.innerHTML).toBe('');
  });

  it('helpers puros', () => {
    expect(thesisParagraphs('a\n\n  b  c \n\n\n')).toEqual(['a', 'b c']);
    expect(hasRows({ title: 'x', head: ['a'], rows: [] })).toBe(false);
    expect(safeLink('javascript:alert(1)')).toBeNull();
    expect(safeLink('https://x.y/')).toBe('https://x.y/');
  });
});
