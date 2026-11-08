'use server';

import { revalidatePath } from 'next/cache';

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
