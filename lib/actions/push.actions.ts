'use server';

import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import { jsonBody, researchRequest } from '@/lib/research/client';

import { PUSH_EVENT_TYPES, type PushEventType } from '@/lib/alerts/push-event-types';
export type { PushEventType } from '@/lib/alerts/push-event-types';

export type PushStatus = {
    enabled: boolean;
    public_key: string | null;
    devices: number;
    preferences: { event_type: PushEventType; enabled: boolean }[];
};

export type PushDeviceInput = {
    endpoint: string;
    keys: { p256dh: string; auth: string };
    user_agent?: string;
};

/** GET /api/alerts/push/status: servidor listo, dispositivos y tipos activados. */
export async function getPushStatus(): Promise<PushStatus> {
    await requireAuthenticatedUser();
    return researchRequest<PushStatus>('/api/alerts/push/status');
}

/** POST /api/alerts/push/subscriptions: registra este dispositivo (Web Push). */
export async function registerPushDevice(input: PushDeviceInput): Promise<void> {
    await requireAuthenticatedUser();
    await researchRequest('/api/alerts/push/subscriptions', { method: 'POST', body: jsonBody(input) });
}

/** POST /api/alerts/push/subscriptions/remove: olvida este dispositivo. */
export async function removePushDevice(endpoint: string): Promise<void> {
    await requireAuthenticatedUser();
    await researchRequest('/api/alerts/push/subscriptions/remove', {
        method: 'POST',
        body: jsonBody({ endpoint }),
    });
}

/** PUT /api/alerts/push/preferences/{tipo}: activa o apaga un tipo de aviso. */
export async function setPushPreference(eventType: PushEventType, enabled: boolean): Promise<void> {
    await requireAuthenticatedUser();
    // Una server action recibe argumentos arbitrarios del cliente: el tipo de
    // TypeScript no protege en runtime. Sin esta lista, «../../x» componía otra
    // ruta del backend (fetch resuelve los «..») con la identidad del usuario.
    if (!(PUSH_EVENT_TYPES as readonly string[]).includes(eventType)) {
        throw new Error('Tipo de aviso no válido');
    }
    await researchRequest(`/api/alerts/push/preferences/${encodeURIComponent(eventType)}`, {
        method: 'PUT',
        body: jsonBody({ enabled }),
    });
}
