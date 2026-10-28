import { describe, expect, it } from 'vitest';
import { buildChangeEvents, directionOf, paginate } from '@/lib/research/change-events';
import type { ResearchThesisChange } from '@/lib/actions/research.actions';

const change = (id: number, over: Partial<ResearchThesisChange> = {}): ResearchThesisChange => ({
  id, company_id: 1, from_version_id: null, to_version_id: null, change_type: 'news_material_update',
  impact_direction: 'neutral', materiality_score: 50, summary: `cambio ${id}`, affected_claim_ids: [], affected_metrics: [],
  requires_review: false, created_at: `2026-10-${10 + id}T10:00:00Z`, updated_at: '', ...over,
});
const review = (id: number, over: Partial<{ thesis_change_id: number | null; news_event_id: number | null; status: string }> = {}) => ({
  id, title: `rev ${id}`, summary: '', status: 'open', thesis_change_id: null, news_event_id: null, created_at: `2026-10-${10 + id}T11:00:00Z`, ...over,
});
const alert = (id: number, review_id: number | null) => ({ id, review_id, severity: 'high', message: `alerta ${id}`, created_at: '2026-10-20T00:00:00Z', source_url: null });

describe('buildChangeEvents', () => {
  it('une cambio, revisión y alerta solo por vínculos persistidos y no pierde registros', () => {
    const events = buildChangeEvents({ changes: [change(1), change(2)], reviews: [review(1, { thesis_change_id: 1 })], alerts: [alert(1, 1)] });
    expect(events).toHaveLength(2);
    const joined = events.find((e) => e.changes[0].id === 1)!;
    expect(joined.reviews.map((r) => r.id)).toEqual([1]);
    expect(joined.alerts.map((a) => a.id)).toEqual([1]);
  });
  it('dos cambios con revisiones del mismo news_event_id forman un suceso con ambos originales', () => {
    const events = buildChangeEvents({
      changes: [change(1), change(2)],
      reviews: [review(1, { thesis_change_id: 1, news_event_id: 9 }), review(2, { thesis_change_id: 2, news_event_id: 9 })],
      alerts: [],
    });
    expect(events).toHaveLength(1);
    expect(events[0].changes.map((c) => c.id).sort()).toEqual([1, 2]);
  });
  it('NO agrupa por texto parecido: sin vínculo cada registro es un suceso', () => {
    const events = buildChangeEvents({ changes: [change(1, { summary: 'Brasil aprueba ASTS' }), change(2, { summary: 'Brasil aprueba ASTS' })], reviews: [review(5), review(6)], alerts: [alert(7, null)] });
    expect(events).toHaveLength(5);
  });
  it('una revisión que apunta a un cambio ausente no se descarta ni se fusiona', () => {
    const events = buildChangeEvents({ changes: [change(1)], reviews: [review(3, { thesis_change_id: 99 })], alerts: [] });
    expect(events).toHaveLength(2);
    expect(events.flatMap((e) => e.reviews).map((r) => r.id)).toEqual([3]);
  });
  it('ordena por fecha más reciente y marca revisión abierta solo con estado abierto', () => {
    const events = buildChangeEvents({ changes: [change(1), change(5)], reviews: [review(1, { thesis_change_id: 1, status: 'resolved' })], alerts: [] });
    expect(events[0].changes[0].id).toBe(5);
    expect(events.find((e) => e.changes[0].id === 1)!.hasOpenReview).toBe(false);
  });
});

describe('directionOf / paginate', () => {
  it('positivo+negativo es mixto; neutral es sin conclusión', () => {
    expect(directionOf([change(1, { impact_direction: 'positive' }), change(2, { impact_direction: 'negative' })])).toBe('mixed');
    expect(directionOf([change(1)])).toBe('none');
    expect(directionOf([change(1, { impact_direction: 'positive' })])).toBe('improves');
  });
  it('pagina de 10 en 10 y acota la página', () => {
    const items = Array.from({ length: 23 }, (_, i) => i);
    expect(paginate(items, 1, 10).items).toHaveLength(10);
    expect(paginate(items, 3, 10).items).toEqual([20, 21, 22]);
    expect(paginate(items, 99, 10).page).toBe(3);
    expect(paginate([], 1, 10).pages).toBe(1);
  });
});
