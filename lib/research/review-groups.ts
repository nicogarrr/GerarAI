export type ReviewLike = { id: number; title: string; created_at?: string | null };
export type ReviewGroup = { title: string; count: number; latest: string | null; ids: number[] };

/** Agrupa revisiones con el mismo título (misma causa repetida): un renglón con contador y fecha de la última. */
export function groupReviews(reviews: ReviewLike[]): ReviewGroup[] {
  const groups = new Map<string, ReviewGroup>();
  for (const review of reviews) {
    const key = review.title.trim().replace(/\s+/g, ' ').toLowerCase();
    const current = groups.get(key);
    const created = review.created_at ?? null;
    if (!current) {
      groups.set(key, { title: review.title.trim(), count: 1, latest: created, ids: [review.id] });
      continue;
    }
    current.count += 1;
    current.ids.push(review.id);
    if (created && (!current.latest || created > current.latest)) current.latest = created;
  }
  return [...groups.values()].sort((a, b) => (b.latest ?? '').localeCompare(a.latest ?? ''));
}
