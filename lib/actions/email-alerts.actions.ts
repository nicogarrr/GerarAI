'use server';

import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import { jsonBody, researchRequest } from '@/lib/research/client';

import { PUSH_EVENT_TYPES, type PushEventType } from '@/lib/alerts/push-event-types';

export type EmailAlertStatus = {
    /** Direccion propia firmada por la sesion (null si el backend aun no la registro). */
    email: string | null;
    /** SMTP listo en el servidor para enviar a direcciones propias. */
    smtp: boolean;
    preferences: { event_type: PushEventType; enabled: boolean }[];
};

/** GET /api/alerts/email-preferences: direccion propia y tipos activados. */
export async function getEmailAlertStatus(): Promise<EmailAlertStatus> {
    await requireAuthenticatedUser();
    return researchRequest<EmailAlertStatus>('/api/alerts/email-preferences');
}

/** PUT /api/alerts/email-preferences/{tipo}: activa o apaga un tipo de aviso. */
export async function setEmailAlertPreference(eventType: PushEventType, enabled: boolean): Promise<void> {
    await requireAuthenticatedUser();
    // Una server action recibe argumentos arbitrarios del cliente: sin esta
    // lista, «../../x» compondria otra ruta del backend con la identidad del
    // usuario (mismo criterio que setPushPreference).
    if (!(PUSH_EVENT_TYPES as readonly string[]).includes(eventType)) {
        throw new Error('Tipo de aviso no válido');
    }
    await researchRequest(`/api/alerts/email-preferences/${encodeURIComponent(eventType)}`, {
        method: 'PUT',
        body: jsonBody({ enabled }),
    });
}
