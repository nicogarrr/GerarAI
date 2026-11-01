'use server';

import { revalidatePath } from 'next/cache';

import { normalizeResearchBody, researchIdentityHeaders } from '@/lib/auth/research-identity';
import { RESEARCH_TIMEOUTS, requestSignal } from '@/lib/research/client';
import { ExternalAPIError } from '@/lib/types/errors';

const BACKEND_URL = process.env.FMP_BACKEND_URL ?? 'http://localhost:8000';

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

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  try {
    const normalized = await normalizeResearchBody(init?.body ?? null);
    const identity = await researchIdentityHeaders({
      method: init?.method ?? 'GET',
      path,
      body: normalized.body ?? null,
    });
    const response = await fetch(`${BACKEND_URL}${path}`, {
      ...init,
      body: normalized.body ?? undefined,
      cache: 'no-store',
      // Sin timeout una lectura lenta del engine dejaba la página colgada en
      // silencio; respeta la señal del caller si la hay (mismo patrón que
      // lib/research/client.ts).
      signal: requestSignal(init?.signal, RESEARCH_TIMEOUTS.GLOBAL_MS),
      headers: {
        ...identity,
        ...(normalized.contentType ? { 'Content-Type': normalized.contentType } : {}),
        ...init?.headers,
      },
    });
    if (!response.ok) throw new ExternalAPIError(`Research API ${response.status}: ${path}`, 'research-api');
    return (await response.json()) as T;
  } catch (error) {
    if (error instanceof ExternalAPIError) throw error;
    throw new ExternalAPIError(`Research API request failed: ${path}`, 'research-api', error);
  }
}

export async function getOwnershipManagers(): Promise<{ managers: OwnershipManager[]; limitations: string[] }> {
  return requestJson<{ managers: OwnershipManager[]; limitations: string[] }>('/api/ownership/managers');
}

export async function getManagerHoldings(cik: string): Promise<ManagerHoldings> {
  return requestJson<ManagerHoldings>(`/api/ownership/managers/${encodeURIComponent(cik)}/holdings`);
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
  return requestJson<ManagerChanges>(`/api/ownership/managers/${encodeURIComponent(cik)}/changes`);
}

export interface OwnershipSyncResult {
    results: Array<{ cik: string; manager: string; status: string; reason?: string | null }>;
}

export async function syncOwnershipManagers(): Promise<OwnershipSyncResult> {
    const result = await requestJson<OwnershipSyncResult>('/api/ownership/managers/sync', { method: 'POST' });
    revalidatePath('/ownership');
    return result;
}
