'use server';

import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import { cachedFetch } from '@/lib/cache/memoryTTL';
import { researchRequest } from '@/lib/research/client';
import type { PoliticiansList, PoliticianTickerTrades } from '@/lib/research/insiders-politicians';

export interface PoliticiansQuery {
  chamber?: 'all' | 'house' | 'senate' | 'executive';
  party?: 'D' | 'R' | 'I' | null;
  sort?: 'trades' | 'late' | 'recent' | 'on_time';
  q?: string | null;
  limit?: number;
  offset?: number;
}

/** GET /api/politicians — una ficha por político (PTR de la Cámara, STOCK Act). */
export async function getPoliticians(query: PoliticiansQuery = {}): Promise<PoliticiansList> {
  const { id: userId } = await requireAuthenticatedUser();
  const params = new URLSearchParams();
  params.set('chamber', query.chamber ?? 'all');
  params.set('sort', query.sort ?? 'trades');
  if (query.party) params.set('party', query.party);
  if (query.q) params.set('q', query.q);
  params.set('limit', String(query.limit ?? 60));
  params.set('offset', String(query.offset ?? 0));
  const qs = params.toString();
  return cachedFetch(`politicians:user:${userId}:list:${qs}`, () => researchRequest<PoliticiansList>(`/api/politicians?${qs}`, { fast: true }), 120);
}

/** GET /api/politicians/ticker/{ticker} — quién operó el ticker. */
export async function getPoliticianTickerTrades(ticker: string): Promise<PoliticianTickerTrades> {
  const { id: userId } = await requireAuthenticatedUser();
  const clean = ticker.trim().toUpperCase();
  return cachedFetch(
    `politicians:user:${userId}:ticker:${clean}`,
    () => researchRequest<PoliticianTickerTrades>(`/api/politicians/ticker/${encodeURIComponent(clean)}`, { fast: true }),
    120,
  );
}
