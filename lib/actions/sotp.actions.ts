'use server';

import { revalidatePath } from 'next/cache';

import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import { getT } from '@/lib/i18n/server';
import { researchRequest } from '@/lib/research/client';
import { sotpModelFromForm } from '@/lib/research/sotp';
import { AppError, isNextRedirectError } from '@/lib/types/errors';

export type SotpMutationResult = { ok: true } | { ok: false; cause: 'validation'; message: string };

/** Guarda una versión nueva del desglose por partes (la anterior queda en el histórico). */
export async function saveSotpResult(ticker: string, counts: { parts: number; dilution: number; scenarios: number }, formData: FormData): Promise<SotpMutationResult> {
  const symbol = ticker.toUpperCase();
  const t = await getT();
  const tr = (key: string, vars?: Record<string, string | number>) => t(key as Parameters<typeof t>[0], vars);
  const parsed = sotpModelFromForm((key) => String(formData.get(key) ?? ''), counts, tr);
  if (!parsed.ok) return { ok: false, cause: 'validation', message: parsed.message };
  try {
    await researchRequest(`/api/valuation/${encodeURIComponent(symbol)}/sotp`, { method: 'PUT', body: JSON.stringify(parsed.model) });
  } catch (error) {
    if (isNextRedirectError(error)) throw error;
    if (error instanceof AppError && error.statusCode === 422) return { ok: false, cause: 'validation', message: error.message };
    throw error;
  }
  revalidatePath(`/research/${symbol}`);
  return { ok: true };
}

/** Borra el desglose guardado (vuelve el borrador de ejemplo, si lo hay). */
export async function deleteSotpResult(ticker: string): Promise<SotpMutationResult> {
  const symbol = ticker.toUpperCase();
  await researchRequest(`/api/valuation/${encodeURIComponent(symbol)}/sotp`, { method: 'DELETE' });
  revalidatePath(`/research/${symbol}`);
  return { ok: true };
}

/** Estado honesto del «Generar con expertos» (sin ETA). */
export type SotpAgentsJob = {
  id: number;
  status: 'queued' | 'running' | 'succeeded' | 'failed' | string;
  ticker?: string | null;
  result?: { status?: string | null; value_per_share?: number | null; problems?: string[] | null } | null;
  finished_at?: string | null;
};

function cleanTicker(ticker: string): string {
  const clean = ticker.trim().toUpperCase();
  if (!/^[A-Z0-9.\-]{1,20}$/.test(clean)) throw new Error('Ticker no válido');
  return clean;
}

/** POST /api/valuation/{t}/sotp/generate — encola el valorador SOTP del equipo de expertos. */
export async function startSotpAgentsJob(ticker: string): Promise<SotpAgentsJob | null> {
  await requireAuthenticatedUser();
  const response = await researchRequest<{ job: SotpAgentsJob | null }>(`/api/valuation/${encodeURIComponent(cleanTicker(ticker))}/sotp/generate`, { method: 'POST' });
  return response.job;
}

/** GET /api/valuation/{t}/sotp/jobs/latest; al terminar bien, refresca la ficha. */
export async function getLatestSotpAgentsJob(ticker: string): Promise<SotpAgentsJob | null> {
  await requireAuthenticatedUser();
  const symbol = cleanTicker(ticker);
  const response = await researchRequest<{ job: SotpAgentsJob | null }>(`/api/valuation/${encodeURIComponent(symbol)}/sotp/jobs/latest`);
  if (response.job?.status === 'succeeded') revalidatePath(`/research/${symbol}`);
  return response.job;
}
