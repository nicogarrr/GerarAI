import { readFileSync } from 'node:fs';
import { render, screen } from '@testing-library/react';
import { beforeAll, describe, expect, it, vi } from 'vitest';

vi.mock('next/headers', () => ({ cookies: async () => ({ get: (name: string) => (name === 'gerarai_locale' ? { value: 'en' } : undefined) }) }));
vi.mock('@/lib/auth/require-user', () => ({ requireAuthenticatedUser: vi.fn(async () => ({ id: 'u1' })) }));
const researchRequest = vi.fn();
vi.mock('@/lib/research/client', () => ({ researchRequest: (...args: unknown[]) => researchRequest(...args) }));

import FilingsYoyPage from '@/app/(root)/research/[ticker]/filings/page';
import { filingsYoyText } from '@/lib/research/filings-yoy-text';

// Frases que mandan filing_yoy_service.py y filing_changes.py en castellano
// (motivos, etiqueta del análisis y nombres de sección). Si cambian allí, este
// test avisa de que la tabla en inglés se ha quedado atrás.
const BACKEND: Array<[string, string]> = [
  ['data-engine/app/services/filing_yoy_service.py', 'Sin informe comparable del mismo periodo del año anterior.'],
  ['data-engine/app/services/filing_yoy_service.py', 'Análisis de texto aún no generado para este informe.'],
  ['data-engine/app/services/filing_changes.py', 'Sin texto identificable en uno o ambos informes.'],
  ['data-engine/app/services/filing_changes.py', 'Sección demasiado extensa para la comparación acotada.'],
  ['data-engine/app/services/filing_changes.py', 'Comparación textual, no materialidad financiera'],
  ['data-engine/app/services/filing_changes.py', 'Factores de riesgo'],
  ['data-engine/app/services/filing_changes.py', 'Perspectivas y guidance'],
  ['data-engine/app/services/filing_changes.py', 'Partes relacionadas'],
];
const SPANISH = /[áéíóúñ]|\b(sin|del|para|informe|año|sección|partes|factores)\b/i;

const side = (value: string) => ({ value, period: '2024', unit: 'USD', source: { url: 'https://www.sec.gov/x', published_at: null } });
const page = async () => render(await FilingsYoyPage({ params: Promise.resolve({ ticker: 'aapl' }), searchParams: Promise.resolve({}) }));

beforeAll(() => {
  window.matchMedia ??= ((query: string) => ({ matches: false, media: query, onchange: null, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {}, dispatchEvent: () => false })) as unknown as typeof window.matchMedia;
});

describe('report vs. prior year: backend texts in English', () => {
  it('the backend still sends these sentences and each has an English version', () => {
    for (const [file, text] of BACKEND) {
      expect(readFileSync(file, 'utf8'), `${file}: ${text}`).toContain(`"${text}"`);
      expect(filingsYoyText(text, 'en'), text).not.toMatch(SPANISH);
      expect(filingsYoyText(text, 'es')).toBe(text);
    }
    expect(readFileSync('data-engine/app/services/filing_yoy_service.py', 'utf8')).toContain('f"Sin {form} oficial de la SEC guardado para esta empresa."');
    expect(filingsYoyText('Sin 10-Q oficial de la SEC guardado para esta empresa.', 'en')).toBe('No official SEC 10-Q stored for this company.');
    expect(filingsYoyText('Texto nuevo.', 'en')).toBe('Texto nuevo.');
    expect(filingsYoyText(undefined, 'en')).toBeUndefined();
  });

  it('no stored report: the reason is in English', async () => {
    researchRequest.mockResolvedValueOnce({ form: '10-K', page: 1, total: 0, status: 'insufficient_data', items: [], reason: 'Sin 10-K oficial de la SEC guardado para esta empresa.' });
    await page();
    expect(screen.getByRole('status')).toHaveTextContent('No official SEC 10-K stored for this company.');
  });

  it('a real backend payload shows section names, reasons, label and missing figures in English', async () => {
    researchRequest.mockResolvedValueOnce({
      status: 'ready', form: '10-K', page: 1, total: 2,
      current: { url: 'https://www.sec.gov/a', published_at: null, reported_period: '2024-12-31' },
      previous: { url: 'https://www.sec.gov/b', published_at: null, reported_period: '2023-12-31' },
      figures: [{ metric: 'revenue', unit: 'USD', current: side('1500000000'), previous: null, label: 'Ingresos', change_pct: null, highlight: false }],
      text: { status: 'partial', method: 'derived_text_diff', label: 'Comparación textual, no materialidad financiera', sections: [
        { section: 'risk_factors', label: 'Factores de riesgo', status: 'insufficient_data', changes: [], reason: 'Sin texto identificable en uno o ambos informes.' },
        { section: 'guidance', label: 'Perspectivas y guidance', status: 'insufficient_data', changes: [], reason: 'Sección demasiado extensa para la comparación acotada.' },
        { section: 'related_parties', label: 'Partes relacionadas', status: 'unchanged', changes: [], change_count: 0, truncated: false },
      ] },
    });
    const { container } = await page();
    expect(screen.getByText('Risk factors')).toBeTruthy();
    expect(screen.getByText('Outlook and guidance')).toBeTruthy();
    expect(screen.getByText('Related parties')).toBeTruthy();
    expect(screen.getByText('Text comparison, not financial materiality')).toBeTruthy();
    expect(screen.getByText('No identifiable text in one or both reports.')).toBeTruthy();
    expect(screen.getByText('Section too long for the bounded comparison.')).toBeTruthy();
    expect(container.textContent).not.toMatch(/N\/D|Factores|Perspectivas|Partes|Comparación|Sin texto|Sección/);
  });

  it('text analysis not generated yet: the reason is in English', async () => {
    researchRequest.mockResolvedValueOnce({
      status: 'ready', form: '10-K', page: 1, total: 2, figures: [], text: null,
      current: { url: null, published_at: null, reported_period: '2024-12-31' },
      previous: { url: null, published_at: null, reported_period: '2023-12-31' },
      text_reason: 'Análisis de texto aún no generado para este informe.',
    });
    await page();
    expect(screen.getByText('Text analysis not generated yet for this report.')).toBeTruthy();
  });
});
