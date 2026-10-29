'use server';

import { redirect } from 'next/navigation';

import { normalizeResearchBody, researchIdentityHeaders } from '@/lib/auth/research-identity';
import { RESEARCH_TIMEOUTS, requestSignal } from '@/lib/research/client';

const BACKEND_URL = process.env.FMP_BACKEND_URL ?? 'http://localhost:8000';

export type CompanyIdentityVerification = {
    ticker: string;
    verified: boolean;
    already_in_master: boolean;
    reasons: string[];
    sec: { cik: string; ticker: string; name: string } | null;
    provider: { ticker: string; name: string; exchange: string; country: string; currency: string } | null;
    company: { ticker: string; name: string } | null;
};

async function signedFetch(path: string, init: { method: string; body?: string }): Promise<Response | null> {
    const normalized = await normalizeResearchBody(init.body ?? null);
    const identity = await researchIdentityHeaders({ method: init.method, path, body: normalized.body ?? null });
    try {
        return await fetch(`${BACKEND_URL}${path}`, {
            method: init.method,
            body: normalized.body ?? undefined,
            cache: 'no-store',
            signal: requestSignal(undefined, RESEARCH_TIMEOUTS.GLOBAL_MS),
            headers: {
                ...identity,
                ...(normalized.contentType
                    ? { 'Content-Type': normalized.contentType }
                    : normalized.body != null
                      ? { 'Content-Type': 'application/json' }
                      : {}),
            },
        });
    } catch {
        return null;
    }
}

/**
 * Veredicto de identidad por doble coincidencia SEC + proveedor. SOLO
 * LECTURA: el render de /research/<ticker> lo usa para saber si puede
 * ofrecer el CTA; nunca crea la ficha. null = no se pudo comprobar.
 */
export async function checkCompanyIdentity(ticker: string): Promise<CompanyIdentityVerification | null> {
    const path = `/api/companies/identity-verification?ticker=${encodeURIComponent(ticker.trim().toUpperCase())}`;
    const response = await signedFetch(path, { method: 'GET' });
    if (!response?.ok) return null;
    return (await response.json()) as CompanyIdentityVerification;
}

/**
 * CTA explícito «Abrir ficha»: pide al backend la creación del stub, que
 * repite la doble comprobación completa y solo crea si sigue verificada.
 * Tras crearla, redirige a la ficha; si ya no verifica, vuelve al estado
 * honesto (la misma URL renderiza el bloqueo con el motivo).
 */
export async function openVerifiedFicha(ticker: string): Promise<void> {
    const symbol = ticker.trim().toUpperCase();
    await signedFetch('/api/companies/verify-identity', {
        method: 'POST',
        body: JSON.stringify({ ticker: symbol }),
    });
    // La ficha se renderiza si el backend la creó; si ya no verifica, la misma
    // URL muestra el estado honesto con el motivo.
    redirect(`/research/${encodeURIComponent(symbol)}`);
}
