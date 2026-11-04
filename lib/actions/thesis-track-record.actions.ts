'use server';

import { researchRequest } from '@/lib/research/client';
import type { components } from '@/lib/research/openapi.generated';

export type ThesisTrackRecord = components['schemas']['CompanyTrackRecordOut'];

/** «Nuestro acierto» de una empresa; null si el backend no responde (la tesis no cae por ello). */
export async function getThesisTrackRecord(ticker: string): Promise<ThesisTrackRecord | null> {
  try {
    return await researchRequest<ThesisTrackRecord>(
      `/api/companies/${encodeURIComponent(ticker)}/track-record`,
      { timeoutMs: 8_000 },
    );
  } catch {
    return null;
  }
}
