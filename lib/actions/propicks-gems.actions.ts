'use server';

import { researchRequest } from '@/lib/research/client';

export interface GemReason {
  key: string;
  value: number;
  source: string;
}

export interface GemItem {
  ticker: string;
  name: string;
  score: number;
  market_cap?: number;
  reasons: GemReason[];
  review_status?: 'reviewed' | 'sin_revision_ia';
  decision?: 'keep' | 'veto' | null;
  thesis?: string | null;
  risks?: string[];
  invalidation?: string | null;
  confidence?: number | null;
  veto_reason?: string | null;
}

/** Joyas deterministas (sin LLM): calidad + valor + insiders + 13F, con fuente y fecha por dato. */
export async function getGems(): Promise<GemItem[] | { error: string }> {
  try {
    return await researchRequest<GemItem[]>('/api/propicks/gems?limit=20', { fast: true });
  } catch (error) {
    console.error('getGems error:', error);
    return { error: 'No se pudieron cargar las joyas.' };
  }
}

/** Revisión del LLM sobre la shortlist (cadena gratuita); si falla, cada pick vuelve como sin_revision_ia. */
export async function reviewGems(): Promise<GemItem[] | { error: string }> {
  try {
    return await researchRequest<GemItem[]>('/api/propicks/review?limit=20', {
      method: 'POST',
      timeoutMs: 55_000,
    });
  } catch (error) {
    console.error('reviewGems error:', error);
    return { error: 'No se pudo completar la revisión.' };
  }
}
