import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { ChangesFeed } from '@/components/research/ChangesFeed';
import { ExpectationsList, type ExpectationRow } from '@/components/research/ExpectationsList';
import { DocumentsList } from '@/components/research/DocumentsList';

beforeEach(() => {
  vi.stubGlobal('matchMedia', () => ({ matches: false, addEventListener() {}, removeEventListener() {} }));
});

const mk = (id: number) => ({
  id, company_id: 1, from_version_id: null, to_version_id: null, change_type: 'news_material_update', impact_direction: 'positive',
  materiality_score: 60, summary: `Suceso ${id}`, affected_claim_ids: [], affected_metrics: [], requires_review: false,
  created_at: `2026-10-${String(id % 28 + 1).padStart(2, '0')}T10:00:00Z`, updated_at: '',
});

describe('ChangesFeed', () => {
  it('muestra 10 sucesos por página y permite avanzar', () => {
    render(<ChangesFeed alerts={[]} changes={Array.from({ length: 25 }, (_, i) => mk(i + 1))} reviews={[]} ticker="ASTS" />);
    expect(screen.getAllByTestId('change-event')).toHaveLength(10);
    fireEvent.click(screen.getByRole('button', { name: 'Siguiente' }));
    expect(screen.getByText(/Página 2 de 3/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Siguiente' }));
    expect(screen.getAllByTestId('change-event')).toHaveLength(5);
  });
  it('«Revisiones abiertas» es un filtro y conserva el registro original dentro', () => {
    const reviews = [{ id: 7, title: 'Revisar guía', summary: '', status: 'open', thesis_change_id: 1, news_event_id: null, created_at: '2026-10-02T00:00:00Z' }];
    render(<ChangesFeed alerts={[]} changes={[mk(1), mk(2)]} reviews={reviews} ticker="ASTS" />);
    fireEvent.click(screen.getByRole('button', { name: /Revisiones abiertas \(1\)/ }));
    const cards = screen.getAllByTestId('change-event');
    expect(cards).toHaveLength(1);
    expect(within(cards[0]).getByText('Revisar guía')).toBeTruthy();
    expect(within(cards[0]).getByRole('button', { name: 'Abrir en el Cerebro' })).toBeTruthy();
  });
});

describe('ExpectationsList / DocumentsList', () => {
  const row = (id: number, year: number, pending: boolean): ExpectationRow => ({ id, year, metric: 'Ingresos', expected: '1B', actual: pending ? 'N/D' : '2B', status: pending ? 'Sin comparación: falta dato' : 'Cumplida', pending });
  it('las previsiones futuras van plegadas por año y no en la lista principal', () => {
    render(<ExpectationsList rows={[row(1, 2025, false), ...Array.from({ length: 12 }, (_, i) => row(10 + i, 2030, true))]} />);
    expect(screen.getByText(/Pendientes de vencimiento \(12\)/)).toBeTruthy();
    expect(screen.getByText('2030: 12')).toBeTruthy();
  });
  it('pagina y filtra documentos', () => {
    const docs = Array.from({ length: 25 }, (_, i) => ({ id: i, title: i === 3 ? 'Informe 10-K especial' : `Doc ${i}`, url: null, tier: 'Oficial', type: 'sec filing', published: '2026' }));
    render(<DocumentsList documents={docs} />);
    expect(screen.getAllByText(/^(Doc|Informe)/)).toHaveLength(10);
    fireEvent.change(screen.getByLabelText('Buscar documentos'), { target: { value: 'especial' } });
    expect(screen.getAllByText(/^(Doc|Informe)/)).toHaveLength(1);
  });
});
