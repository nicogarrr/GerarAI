import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('next/headers', () => ({ cookies: async () => ({ get: (name: string) => (name === 'gerarai_locale' ? { value: 'en' } : undefined) }) }));
vi.mock('@/lib/auth/require-user', () => ({ requireAuthenticatedUser: vi.fn(async () => ({ id: 'u1' })) }));
const side = (value: string) => ({ value, period: '2024', unit: 'USD', source: { url: 'https://www.sec.gov/x', published_at: null } });
vi.mock('@/lib/research/client', () => ({
  researchRequest: vi.fn(async () => ({
    status: 'ready', form: '10-K', page: 1, total: 3,
    current: { url: 'https://www.sec.gov/a', published_at: null, reported_period: '2024-12-31' },
    previous: { url: 'https://www.sec.gov/b', published_at: null, reported_period: '2023-12-31' },
    figures: [{ metric: 'revenue', unit: 'USD', current: side('1500000000'), previous: side('1000000000'), label: 'Revenue', change_pct: '50.0', highlight: true }],
    text: { label: 'Item 1A', sections: [{ section: 'risk', label: 'Risk factors', status: 'changed', change_count: 1, changes: [{ kind: 'added', before: [], after: [{ text: 'New risk' }] }] }] },
  })),
}));

import FilingsYoyPage from '@/app/(root)/research/[ticker]/filings/page';

describe('SEC report vs. prior year in English', () => {
  it('shows headings, table, changes and paging in English', async () => {
    window.matchMedia ??= ((query: string) => ({ matches: false, media: query, onchange: null, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {}, dispatchEvent: () => false })) as unknown as typeof window.matchMedia;
    render(await FilingsYoyPage({ params: Promise.resolve({ ticker: 'aapl' }), searchParams: Promise.resolve({}) }));
    expect(screen.getByText('Report vs. prior year · AAPL')).toBeTruthy();
    expect(screen.getByText('Key figures')).toBeTruthy();
    expect(screen.getByText('Prior year')).toBeTruthy();
    expect(screen.getByText('+50%')).toBeTruthy();
    expect(screen.getByText('Text changes')).toBeTruthy();
    expect(screen.getByText('Added')).toBeTruthy();
    expect(screen.getByText('Now: “New risk”')).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Older' })).toBeTruthy();
    expect(screen.queryByText(/Cifras clave|Año anterior|Añadido/)).toBeNull();
  });
});
