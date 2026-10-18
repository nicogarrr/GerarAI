'use server';

import { researchRequest } from '@/lib/research/client';

export interface TrackRecordPick {
  ticker: string;
  name: string;
  currency: string | null;
  entry_month: string;
  entry_price: number | null;
  entry_price_date: string | null;
  status: 'activo' | 'salio';
  exit_month: string | null;
  exit_price: number | null;
  exit_price_date: string | null;
  exit_pct: number | null;
  spy_pct_exit: number | null;
  current_price: number | null;
  current_price_date: string | null;
  current_stale: boolean;
  pct_since_entry: number | null;
  spy_pct_since_entry: number | null;
  horizon_date: string | null;
  pct_90d: number | null;
  spy_pct_90d: number | null;
}

export interface TrackRecordResponse {
  snapshots_count: number;
  history_label: string;
  months: string[];
  stale_threshold_days: number;
  horizon_days: number;
  spy: { available: boolean; source: string; latest_date: string | null };
  picks: TrackRecordPick[];
}

/** Ganadores anteriores: track record vivo desde los snapshots mensuales congelados. */
export async function getTrackRecord(): Promise<TrackRecordResponse | { error: string }> {
  try {
    return await researchRequest<TrackRecordResponse>('/api/propicks/track-record', { fast: true });
  } catch (error) {
    console.error('getTrackRecord error:', error);
    return { error: 'No se pudo cargar el histórico de selecciones.' };
  }
}
