import type { ResearchThesisChange } from '@/lib/actions/research.actions';

/**
 * Agrupa por suceso los registros de «Seguir» (cambios, revisiones, alertas)
 * usando SOLO vínculos persistidos:
 *  - revisión.thesis_change_id -> cambio
 *  - revisión.news_event_id comun -> mismo suceso de noticia
 *  - alerta.review_id -> revisión
 * Sin vínculo no se agrupa nada (no se infiere identidad por texto): cada
 * registro suelto es su propio suceso. Todos los originales quedan dentro del
 * suceso; esta función no descarta ninguno.
 */
export type EventReview = {
  id: number;
  title: string;
  summary: string;
  status: string;
  thesis_change_id: number | null;
  news_event_id: number | null;
  created_at: string;
};
export type EventAlert = {
  id: number;
  review_id: number | null;
  severity: string;
  message: string;
  created_at: string;
  source_url?: string | null;
};
export type ChangeDirection = 'improves' | 'worsens' | 'mixed' | 'none';
export type ChangeEvent = {
  key: string;
  changes: ResearchThesisChange[];
  reviews: EventReview[];
  alerts: EventAlert[];
  direction: ChangeDirection;
  latest: string;
  metrics: string[];
  claimCount: number;
  hasOpenReview: boolean;
  requiresReview: boolean;
  sourceUrls: string[];
};

const CLOSED = new Set(['approved', 'closed', 'resolved', 'dismissed', 'done', 'cerrada', 'cerrado']);
export function isOpenReview(status: string): boolean {
  return !CLOSED.has(status.trim().toLowerCase());
}

export function directionOf(changes: ResearchThesisChange[]): ChangeDirection {
  const dirs = new Set(changes.map((change) => change.impact_direction));
  const pos = dirs.has('positive');
  const neg = dirs.has('negative');
  if (dirs.has('mixed') || (pos && neg)) return 'mixed';
  if (pos) return 'improves';
  if (neg) return 'worsens';
  return 'none';
}

export function buildChangeEvents(input: {
  changes: ResearchThesisChange[];
  reviews: EventReview[];
  alerts: EventAlert[];
}): ChangeEvent[] {
  // Union-find sobre nodos tipados: c:<id>, r:<id>, a:<id>, n:<news_event_id>.
  const parent = new Map<string, string>();
  const find = (x: string): string => {
    let root = x;
    while ((parent.get(root) ?? root) !== root) root = parent.get(root)!;
    parent.set(x, root);
    return root;
  };
  const add = (x: string) => { if (!parent.has(x)) parent.set(x, x); };
  const union = (a: string, b: string) => { add(a); add(b); parent.set(find(a), find(b)); };

  const changeIds = new Set(input.changes.map((change) => change.id));
  const reviewIds = new Set(input.reviews.map((review) => review.id));
  for (const change of input.changes) add(`c:${change.id}`);
  for (const review of input.reviews) {
    add(`r:${review.id}`);
    if (review.thesis_change_id != null && changeIds.has(review.thesis_change_id)) union(`r:${review.id}`, `c:${review.thesis_change_id}`);
    if (review.news_event_id != null) union(`r:${review.id}`, `n:${review.news_event_id}`);
  }
  for (const alert of input.alerts) {
    add(`a:${alert.id}`);
    if (alert.review_id != null && reviewIds.has(alert.review_id)) union(`a:${alert.id}`, `r:${alert.review_id}`);
  }

  const buckets = new Map<string, { changes: ResearchThesisChange[]; reviews: EventReview[]; alerts: EventAlert[] }>();
  const bucket = (node: string) => {
    const root = find(node);
    let b = buckets.get(root);
    if (!b) { b = { changes: [], reviews: [], alerts: [] }; buckets.set(root, b); }
    return b;
  };
  for (const change of input.changes) bucket(`c:${change.id}`).changes.push(change);
  for (const review of input.reviews) bucket(`r:${review.id}`).reviews.push(review);
  for (const alert of input.alerts) bucket(`a:${alert.id}`).alerts.push(alert);

  const events: ChangeEvent[] = [];
  for (const [key, b] of buckets) {
    const dates = [...b.changes.map((x) => x.created_at), ...b.reviews.map((x) => x.created_at), ...b.alerts.map((x) => x.created_at)].filter(Boolean);
    const urls = [...new Set(b.alerts.map((a) => a.source_url).filter((u): u is string => !!u))];
    const claims = new Set(b.changes.flatMap((x) => x.affected_claim_ids));
    events.push({
      key,
      changes: b.changes.sort((x, y) => y.created_at.localeCompare(x.created_at)),
      reviews: b.reviews,
      alerts: b.alerts,
      direction: directionOf(b.changes),
      latest: dates.sort().at(-1) ?? '',
      metrics: [...new Set(b.changes.flatMap((x) => x.affected_metrics))],
      claimCount: claims.size,
      hasOpenReview: b.reviews.some((r) => isOpenReview(r.status)),
      requiresReview: b.changes.some((x) => x.requires_review),
      sourceUrls: urls,
    });
  }
  return events.sort((a, b) => b.latest.localeCompare(a.latest));
}

export function paginate<T>(items: T[], page: number, size: number): { items: T[]; page: number; pages: number } {
  const pages = Math.max(1, Math.ceil(items.length / size));
  const current = Math.min(Math.max(1, page), pages);
  return { items: items.slice((current - 1) * size, current * size), page: current, pages };
}
