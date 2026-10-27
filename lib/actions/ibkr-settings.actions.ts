'use server';

import { revalidatePath } from 'next/cache';
import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import { researchRequest } from '@/lib/research/client';

export type IBKRConnection = {
  connected: boolean; account_id: string | null; query_id: string | null;
  status: string; message: string; complete_query: boolean;
  last_attempt_at: string | null; last_success_at: string | null; statement_date: string | null;
};
export type IBKRConnectInput = { token: string; query_id: string; account_id: string; complete_query: boolean };
export type IBKRResult = { ok: true; connection: IBKRConnection } | { ok: false; message: string };

export async function getIBKRConnection(): Promise<IBKRConnection> {
  await requireAuthenticatedUser();
  return researchRequest<IBKRConnection>('/api/settings/ibkr', { cache: 'no-store' });
}

export async function connectIBKR(input: IBKRConnectInput): Promise<IBKRResult> {
  await requireAuthenticatedUser();
  try {
    const connection = await researchRequest<IBKRConnection>('/api/settings/ibkr', {
      method: 'PUT', body: JSON.stringify(input), timeoutMs: 120_000,
    });
    return { ok: true, connection };
  } catch {
    return { ok: false, message: 'No se pudo verificar la conexión. Revisa token, Query ID y cuenta. La consulta debe incluir posiciones y caja del mismo cierre, en XML; IBKR puede tardar en prepararla.' };
  }
}

export async function syncIBKR(): Promise<IBKRResult> {
  await requireAuthenticatedUser();
  try {
    const connection = await researchRequest<IBKRConnection>('/api/settings/ibkr/sync', {
      method: 'POST', timeoutMs: 120_000,
    });
    revalidatePath('/portfolio');
    revalidatePath('/inicio');
    return { ok: true, connection };
  } catch {
    return { ok: false, message: 'No se pudo sincronizar. Conservamos los datos anteriores. Revisa la consulta o vuelve a intentarlo cuando IBKR termine el informe.' };
  }
}

export async function disconnectIBKR(): Promise<IBKRResult> {
  await requireAuthenticatedUser();
  try {
    const connection = await researchRequest<IBKRConnection>('/api/settings/ibkr', { method: 'DELETE' });
    return { ok: true, connection };
  } catch {
    return { ok: false, message: 'No se pudo desconectar. Vuelve a intentarlo; la conexión puede seguir activa.' };
  }
}
