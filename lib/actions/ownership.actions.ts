'use server';

import { revalidatePath } from 'next/cache';

import { researchRequest } from '@/lib/research/client';

export type OwnershipManager = {
  cik: string;
  name: string;
};

export type OwnershipProvenance = {
  source: string;
  source_kind: string;
  source_url: string | null;
  fetched_at: string;
  coverage: string;
  note?: string | null;
};

// La via snapshot (sin sync en vivo) deja en null lo que el snapshot no tiene:
// accession, filing_url y los campos que el filing no parseo. Nunca asumir string.
export type ManagerHoldingRow = {
  accession_number: string | null;
  is_amendment: boolean;
  name_of_issuer: string | null;
  name_of_issuer_filed?: string | null;
  title_of_class: string | null;
  cusip: string | null;
  value_usd_thousands: number | null;
  shares: number | null;
  share_type: string | null;
  put_call: string | null;
  investment_discretion: string | null;
  filing_url: string | null;
};

/** «ok» solo si los totales cuadran con el resumen del propio 13F (Auditoría A). */
// «snapshot»: servido del snapshot edgartools sin contrastar totales (nunca es «ok»).
export type ManagerHoldingsStatus = 'ok' | 'mismatch' | 'unverified' | 'partial' | 'unavailable' | 'snapshot';

export type ManagerHoldings = {
  cik: string;
  manager?: string | null;
  status: ManagerHoldingsStatus;
  verification?: 'verified' | 'mismatch' | 'unverified' | 'partial' | 'unavailable' | 'snapshot_unverified' | null;
  report_date?: string | null;
  coverage?: string | null;
  holdings: ManagerHoldingRow[];
  errors?: unknown[] | null;
  limitations?: string[] | null;
  transport?: string | null;
  snapshot_synced_at?: string | null;
  provenance?: OwnershipProvenance | null;
};

export async function getOwnershipManagers(): Promise<{ managers: OwnershipManager[]; limitations: string[] }> {
  return researchRequest<{ managers: OwnershipManager[]; limitations: string[] }>('/api/ownership/managers');
}

export async function getManagerHoldings(cik: string): Promise<ManagerHoldings> {
  return researchRequest<ManagerHoldings>(`/api/ownership/managers/${encodeURIComponent(cik)}/holdings`);
}

export type ManagerChangeRow = {
  change: 'new' | 'closed' | 'increased' | 'decreased' | 'unchanged';
  name_of_issuer: string;
  title_of_class: string;
  cusip: string;
  put_call: string | null;
  shares_latest: number | null;
  shares_previous: number | null;
  value_usd_thousands_latest: number | null;
  value_usd_thousands_previous: number | null;
};

export type ManagerChanges = {
  cik: string;
  manager?: string | null;
  status: 'ok' | 'insufficient_history' | 'unavailable';
  detail?: string | null;
  latest_report?: string | null;
  previous_report?: string | null;
  compared_accessions?: { latest: string; previous: string; rule: string } | null;
  changes: ManagerChangeRow[];
  limitations?: string[] | null;
  provenance?: OwnershipProvenance | null;
};

export async function getManagerChanges(cik: string): Promise<ManagerChanges> {
  return researchRequest<ManagerChanges>(`/api/ownership/managers/${encodeURIComponent(cik)}/changes`);
}

export interface OwnershipSyncResult {
    results: Array<{ cik: string; manager: string; status: string; reason?: string | null }>;
}

export async function syncOwnershipManagers(): Promise<OwnershipSyncResult> {
    const result = await researchRequest<OwnershipSyncResult>('/api/ownership/managers/sync', { method: 'POST' });
    revalidatePath('/ownership');
    return result;
}
