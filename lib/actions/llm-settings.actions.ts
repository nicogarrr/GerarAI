'use server';

import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import { researchRequest } from '@/lib/research/client';

export type LlmProviderOption = {
    id: string;
    label: string;
    base_url: string;
    default_model: string;
    requires_custom_url: boolean;
};

export type LlmSettings = {
    source: 'platform' | 'tenant';
    status: 'platform' | 'tenant' | 'missing_key' | 'disabled';
    provider: string;
    base_url: string | null;
    model: string | null;
    fallback_model: string | null;
    reasoning_effort: string | null;
    enabled: boolean;
    configured: boolean;
    api_key_configured: boolean;
    api_key_last4: string | null;
    key_version: number | null;
    billing_scope: string;
    encryption_available: boolean;
    message: string;
    error?: string | null;
    providers: LlmProviderOption[];
};

export type LlmSettingsInput = {
    provider: string;
    model: string;
    base_url?: string | null;
    fallback_model?: string | null;
    reasoning_effort?: string | null;
    api_key?: string;
    clear_api_key?: boolean;
    enabled: boolean;
};

export type LlmTestInput = {
    provider: string;
    model: string;
    base_url?: string | null;
    api_key?: string;
};

export type LlmTestResult = {
    ok: boolean;
    status_code: number | null;
    provider: string;
    base_url: string;
    model: string;
    message: string;
};

/** GET /api/settings/llm: la clave nunca viaja al navegador. */
export async function getLlmSettings(): Promise<LlmSettings> {
    await requireAuthenticatedUser();
    return researchRequest<LlmSettings>('/api/settings/llm', { cache: 'no-store' });
}

/** PUT /api/settings/llm: configuracion y clave cifrada del tenant. */
export async function saveLlmSettings(input: LlmSettingsInput): Promise<LlmSettings> {
    await requireAuthenticatedUser();
    return researchRequest<LlmSettings>('/api/settings/llm', {
        method: 'PUT',
        body: JSON.stringify(input),
    });
}

/** POST /api/settings/llm/test: GET /models con 5 s en el backend. */
export async function testLlmConnection(input: LlmTestInput): Promise<LlmTestResult> {
    await requireAuthenticatedUser();
    return researchRequest<LlmTestResult>('/api/settings/llm/test', {
        method: 'POST',
        body: JSON.stringify(input),
        timeoutMs: 15_000,
    });
}

export type LlmUsageLeg = {
    id: string;
    label: string;
    provider: string;
    model: string | null;
    active: boolean;
    state: 'ok' | 'limited' | 'off';
    /** true = contadores propios (el proveedor no expone su cuota); false = dato real de la API del proveedor. */
    estimated: boolean;
    limited_until: string | null;
    quota?: {
        rolling?: { percent?: number } & Record<string, unknown>;
        weekly?: { status?: string; percent?: number; resetsAt?: string } & Record<string, unknown>;
        monthly?: { percent?: number; resetsAt?: string } & Record<string, unknown>;
    } | null;
    today?: { date: string; calls: number; tokens: number } | null;
    published_limits?: Record<string, { rpm?: number; rpd?: number; tpm?: number }> | null;
};

export type LlmUsage = {
    source: 'platform' | 'tenant';
    generated_at: string;
    legs: LlmUsageLeg[];
    message?: string | null;
};

/** GET /api/settings/llm/usage: cuota real de Go y contadores propios estimados. */
export async function getLlmUsage(): Promise<LlmUsage> {
    await requireAuthenticatedUser();
    return researchRequest<LlmUsage>('/api/settings/llm/usage', { cache: 'no-store' });
}
