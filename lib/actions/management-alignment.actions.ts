'use server';

import { researchRequest } from '@/lib/research/client';
import type { ManagementAlignment } from '@/lib/research/management-alignment';

export async function getManagementAlignment(ticker: string): Promise<ManagementAlignment> {
  return researchRequest<ManagementAlignment>(`/api/companies/${encodeURIComponent(ticker)}/management-alignment`, { fast: true });
}
