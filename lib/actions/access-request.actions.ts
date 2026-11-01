'use server';

import { headers } from 'next/headers';
import { connectToDatabase } from '@/database/mongoose';
import { AccessRequest } from '@/database/models/access-request.model';
import { ACCESS_REQUEST_LIMITS, parseAccessRequest } from '@/lib/access-request';
import { clientIp, hashIp } from '@/lib/access-request-ip';
import { notifyAccessRequest } from '@/lib/access-request-notify';
import { requestLocale } from '@/lib/research/backend-error-locale';
import { createTranslator } from '@/lib/i18n/translate';

export type AccessRequestResult =
    | { ok: true; message: string }
    | { ok: false; message: string; field?: 'name' | 'email' | 'note' };

const INVALID_KEYS = {
    nameMissing: 'auth.accessRequest.errors.nameMissing',
    nameTooLong: 'auth.accessRequest.errors.nameTooLong',
    emailInvalid: 'auth.accessRequest.errors.emailInvalid',
    noteTooLong: 'auth.accessRequest.errors.noteTooLong',
} as const;

/**
 * Guarda una solicitud de acceso. Orden deliberado: validar, limitar, GUARDAR y
 * solo despues avisar; si el aviso falla la solicitud ya esta guardada.
 * Un bot (campo trampa relleno) recibe la misma respuesta y no se guarda nada.
 */
export async function requestAccess(raw: unknown): Promise<AccessRequestResult> {
    // Copia en el idioma de la petición (Ajustes → Idioma); en español, las frases de siempre.
    const t = createTranslator(await requestLocale());
    const RECEIVED = t('auth.accessRequest.received');
    const parsed = parseAccessRequest(raw);
    if (!parsed.ok) {
        if (parsed.reason === 'spam') return { ok: true, message: RECEIVED };
        return { ok: false, message: t(INVALID_KEYS[parsed.code], { max: ACCESS_REQUEST_LIMITS.noteMax }), field: parsed.field };
    }
    const { name, email, note } = parsed.value;

    try {
        await connectToDatabase();
        const h = await headers();
        const ipHash = hashIp(
            clientIp(h.get('x-forwarded-for'), h.get('x-real-ip')),
            process.env.BETTER_AUTH_SECRET ?? ''
        );

        const existing = await AccessRequest.findOne({ email });
        if (existing) {
            // Mismo email: no se crea otra fila ni se vuelve a avisar.
            await AccessRequest.updateOne({ email }, { $inc: { submissions: 1 } });
            return { ok: true, message: RECEIVED };
        }

        const since = new Date(Date.now() - ACCESS_REQUEST_LIMITS.windowMs);
        const recent = await AccessRequest.countDocuments({ ipHash, createdAt: { $gte: since } });
        if (recent >= ACCESS_REQUEST_LIMITS.perIpPerHour) {
            return { ok: false, message: t('auth.accessRequest.errors.tooManyRequests') };
        }

        const doc = await AccessRequest.create({ email, name, note, ipHash });
        const total = await AccessRequest.countDocuments({});
        const sent = await notifyAccessRequest({ name, email, note }, total);
        if (sent) await AccessRequest.updateOne({ _id: doc._id }, { $set: { notifiedAt: new Date() } });
        return { ok: true, message: RECEIVED };
    } catch (error) {
        // Carrera entre dos envios del mismo email: el unique ya la guardo.
        if ((error as { code?: number })?.code === 11000) return { ok: true, message: RECEIVED };
        console.error('Access request failed:', error);
        return {
            ok: false,
            message: t('auth.accessRequest.errors.saveFailed'),
        };
    }
}
