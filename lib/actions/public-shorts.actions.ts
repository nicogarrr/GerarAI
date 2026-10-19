'use server';

import { revalidatePath } from 'next/cache';
import { researchRequest } from '@/lib/research/client';

export type PublicShorts = {
  ticker: string; status: string; fetched_at: string | null; reason: string | null;
  data: null | {
    source: string; source_url: string; note: string; date?: string;
    short_volume?: number; total_volume?: number; short_volume_ratio?: number | null;
    public_total_percent?: number;
    positions?: { holder: string; percent: number; position_date: string }[];
  };
};
export async function getPublicShorts(ticker: string): Promise<PublicShorts> {
  return researchRequest<PublicShorts>(`/api/data-health/shorts/${encodeURIComponent(ticker)}`, { fast: true });
}
export async function refreshPublicShorts(ticker: string): Promise<void> {
  const result = await researchRequest<PublicShorts>(`/api/data-health/shorts/${encodeURIComponent(ticker)}/refresh`, { method: 'POST', timeoutMs: 65_000 });
  revalidatePath(`/research/${ticker}/shorts`);
  if (result.status === 'degraded') throw new Error(result.reason ?? 'La fuente no devuelve datos verificables.');
}
