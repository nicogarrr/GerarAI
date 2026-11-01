import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ChangesFeed } from '@/components/research/ChangesFeed';
import { DocumentsList } from '@/components/research/DocumentsList';
import { LocaleProvider } from '@/lib/i18n/client';
import { changeTypeLabel } from '@/lib/research/change-copy';

beforeEach(() => {
  vi.stubGlobal('matchMedia', () => ({ matches: false, addEventListener() {}, removeEventListener() {} }));
});

const mk = (id: number) => ({
  id, company_id: 1, from_version_id: null, to_version_id: null, change_type: 'claim_stale', impact_direction: 'positive',
  materiality_score: 60, summary: `Event ${id}`, affected_claim_ids: [1, 2], affected_metrics: [], requires_review: true,
  created_at: `2026-10-${String(id % 28 + 1).padStart(2, '0')}T10:00:00Z`, updated_at: '',
});

describe('«Qué ha cambiado» y documentos en inglés', () => {
  it('el feed de cambios no deja español con English elegido', () => {
    const { container } = render(
      <LocaleProvider locale="en">
        <ChangesFeed alerts={[]} changes={Array.from({ length: 12 }, (_, i) => mk(i + 1))} reviews={[]} ticker="ASTS" />
      </LocaleProvider>,
    );
    expect(screen.getByText('What has changed')).toBeTruthy();
    expect(screen.getByRole('group', { name: 'Filter events' })).toBeTruthy();
    expect(screen.getAllByText('outdated claim').length).toBeGreaterThan(0);
    expect(screen.getAllByText('review pending').length).toBeGreaterThan(0);
    expect(container.textContent).toContain('2 thesis claims');
    expect(container.textContent).toContain('12 events');
    expect(container.textContent).not.toMatch(/sucesos|Qué ha cambiado|revisión|afirmaci|Ver la tesis|Fecha desconocida/);
  });

  it('en español el feed se ve igual', () => {
    const { container } = render(<ChangesFeed alerts={[]} changes={Array.from({ length: 12 }, (_, i) => mk(i + 1))} reviews={[]} ticker="ASTS" />);
    expect(screen.getByText('Qué ha cambiado')).toBeTruthy();
    expect(container.textContent).toContain('2 afirmaciones de la tesis');
    expect(container.textContent).toContain('12 sucesos');
    expect(changeTypeLabel('claim_stale')).toBe('afirmación desactualizada');
    expect(changeTypeLabel(null, 'en')).toBe('—');
  });

  it('el buscador y el paginador de documentos salen en inglés', () => {
    const docs = Array.from({ length: 12 }, (_, i) => ({ id: i + 1, title: `Doc ${i + 1}`, type: '10-K', tier: 'T1', tierRank: 1, published: '2026', publishedTs: `2026-01-${String(i + 1).padStart(2, '0')}`, url: null }));
    const { container } = render(<LocaleProvider locale="en"><DocumentsList documents={docs as never} /></LocaleProvider>);
    expect(screen.getByRole('searchbox', { name: 'Search documents' })).toBeTruthy();
    expect(container.textContent).toContain('12 documents');
    expect(container.textContent).not.toContain('documentos');
  });
});
