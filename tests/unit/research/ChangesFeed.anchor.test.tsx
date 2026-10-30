import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ChangesFeed } from '@/components/research/ChangesFeed';

beforeEach(() => {
  vi.stubGlobal('matchMedia', () => ({ matches: false, addEventListener() {}, removeEventListener() {} }));
  window.location.hash = '';
});

// Mismo generador que ChangesFeed.test.tsx: created_at crece con el id, así
// que los sucesos salen ordenados de id mayor a menor (25, 24, ..., 1).
const mk = (id: number) => ({
  id, company_id: 1, from_version_id: null, to_version_id: null, change_type: 'news_material_update', impact_direction: 'positive',
  materiality_score: 60, summary: `Suceso ${id}`, affected_claim_ids: [], affected_metrics: [], requires_review: false,
  created_at: `2026-10-${String(id % 28 + 1).padStart(2, '0')}T10:00:00Z`, updated_at: '',
});

describe('ChangesFeed · anclas de Inicio (#thesis-change-N)', () => {
  it('cada tarjeta lleva el ancla de su cambio líder', () => {
    render(<ChangesFeed alerts={[]} changes={[mk(1)]} reviews={[]} ticker="ASTS" />);
    expect(document.getElementById('thesis-change-1')).toBeTruthy();
  });
  it('con ancla a un suceso de otra página, abre directamente esa página', () => {
    // 25 sucesos, 10 por página: el cambio 1 es el último (página 3).
    window.location.hash = '#thesis-change-1';
    render(<ChangesFeed alerts={[]} changes={Array.from({ length: 25 }, (_, i) => mk(i + 1))} reviews={[]} ticker="ASTS" />);
    expect(screen.getByText(/Página 3 de 3/)).toBeTruthy();
    expect(document.getElementById('thesis-change-1')).toBeTruthy();
  });
  it('ancla a un cambio no líder: despliega los registros originales del suceso', () => {
    // Dos cambios unidos al mismo suceso por news_event_id compartido.
    const reviews = [
      { id: 7, title: 'R1', summary: '', status: 'open', thesis_change_id: 1, news_event_id: 5, created_at: '2026-10-02T00:00:00Z' },
      { id: 8, title: 'R2', summary: '', status: 'open', thesis_change_id: 2, news_event_id: 5, created_at: '2026-10-03T00:00:00Z' },
    ];
    window.location.hash = '#thesis-change-1';
    render(<ChangesFeed alerts={[]} changes={[mk(1), mk(2)]} reviews={reviews} ticker="ASTS" />);
    // El líder del suceso es el cambio más reciente (2): la tarjeta lleva su ancla.
    const card = document.getElementById('thesis-change-2');
    expect(card).toBeTruthy();
    // El detalle queda desplegado para que el ancla del cambio 1 sea visible.
    expect(card?.querySelector('details')?.open).toBe(true);
    expect(document.getElementById('thesis-change-1')).toBeTruthy();
  });
  it('ancla desconocida: render normal, sin romper', () => {
    window.location.hash = '#thesis-change-999';
    render(<ChangesFeed alerts={[]} changes={[mk(1)]} reviews={[]} ticker="ASTS" />);
    expect(screen.getByText('Suceso 1')).toBeTruthy();
    expect(document.getElementById('thesis-change-1')).toBeTruthy();
  });
});
