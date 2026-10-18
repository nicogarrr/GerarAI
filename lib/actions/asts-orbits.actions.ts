'use server';

import { researchRequest } from '@/lib/research/client';

export type AstOrbitSample = {
  epoch: string;
  sma_km: number;
  bstar: number | null;
  mean_motion_dot: number | null;
};
export type AstOrbitSignal = {
  status: string;
  delta_sma_km: number | null;
  hours: number | null;
};
export type AstOrbitObject = {
  norad_cat_id: number;
  object_name: string;
  epoch: string;
  sma_km: number | null;
  signal: AstOrbitSignal;
  history: AstOrbitSample[];
};
export type AstOrbitOverview = {
  status: 'disponible' | 'sin datos';
  source: string;
  source_url: string;
  cadence_hours: number;
  fetched_at: string | null;
  objects: AstOrbitObject[];
  usage_note: string;
  supgp: {
    status: 'disponible' | 'sin datos';
    source: string;
    source_url: string;
    fetched_at: string | null;
    objects: AstOrbitObject[];
  };
};

export async function getAstOrbitOverview(): Promise<AstOrbitOverview> {
  return researchRequest<AstOrbitOverview>('/api/market/asts/orbits', { cache: 'no-store', fast: true });
}

export type AstsAnalysis = {
  status: 'disponible' | 'sin datos';
  mode: 'determinista' | 'llm' | null;
  generated_at: string;
  source: { name: string; url: string; fetched_at: string | null };
  analysis: {
    summary: string;
    observations: { text: string }[];
    llm_interpretation: { summary: string; observations: { text: string }[] } | null;
  } | null;
};

export async function getAstsAnalysis(): Promise<AstsAnalysis | null> {
  try {
    return await researchRequest<AstsAnalysis>('/api/market/asts/llm-analysis', { cache: 'no-store', timeoutMs: 12_000 });
  } catch {
    return null;
  }
}
