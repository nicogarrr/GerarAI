'use server';

import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import { researchRequest } from '@/lib/research/client';
import type { ValuationSummary } from '@/lib/research/valuation-summary';

export async function getValuationSummaries(symbols: string[]): Promise<Record<string, ValuationSummary>> {
  await requireAuthenticatedUser();
  const wanted = [...new Set(symbols.map(s => s.trim().toUpperCase()).filter(Boolean))].slice(0, 60);
  if (!wanted.length) return {};
  const data = await researchRequest<{ items: Record<string, ValuationSummary> }>(`/api/valuation/summary?tickers=${encodeURIComponent(wanted.join(','))}`, { cache: 'no-store' });
  return data.items;
}
