'use server';

import { jsonBody, researchRequest } from '@/lib/research/client';
import { cachedFetch } from '@/lib/cache/memoryTTL';
import { requestCache } from '@/lib/cache/requestCache';
import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import { AppError, isNextRedirectError, ValidationError } from '@/lib/types/errors';

export type AlertType = 'price_above' | 'price_below' | 'price_change' | 'news' | 'earnings';

export interface Alert {
    _id: string;
    symbol: string;
    type: AlertType;
    condition: {
        operator: '>' | '<' | '>=' | '<=' | '==';
        value: number | string;
    };
    isActive: boolean;
    lastTriggered?: string;
    createdAt: string;
    updatedAt: string;
    /** Estado de evaluacion del motor (job alert_rule_evaluation, cada 5 min). */
    channels: string[];
    triggerCount: number;
    lastEvaluatedAt?: string;
    lastValue?: string | null;
    lastResultStatus?: string;
}

export interface CreateAlertInput {
    symbol: string;
    type: AlertType;
    condition: Alert['condition'];
}

type ResearchAlertRule = {
    id: number;
    active: boolean;
    rule_type: Alert['type'];
    condition: Alert['condition'];
    channels: string[];
    trigger_count: number;
    last_evaluated_at?: string | null;
    last_value?: string | null;
    last_result?: { status?: string } | null;
    last_triggered_at?: string | null;
    created_at: string;
    updated_at: string;
    metadata: {
        ticker?: string;
    };
};

function toAlert(alert: ResearchAlertRule): Alert {
    return {
        _id: String(alert.id),
        symbol: alert.metadata.ticker ?? '',
        type: alert.rule_type,
        condition: alert.condition,
        isActive: alert.active,
        lastTriggered: alert.last_triggered_at ?? undefined,
        createdAt: alert.created_at,
        updatedAt: alert.updated_at,
        channels: alert.channels ?? ['in_app'],
        triggerCount: alert.trigger_count ?? 0,
        lastEvaluatedAt: alert.last_evaluated_at ?? undefined,
        lastValue: alert.last_value ?? null,
        lastResultStatus: alert.last_result?.status,
    };
}

export async function createAlert(input: CreateAlertInput): Promise<Alert> {
    const symbol = input.symbol.trim().toUpperCase();
    if (!/^[A-Z0-9.\-]{1,20}$/.test(symbol)) {
        throw new ValidationError('A valid ticker is required', 'symbol');
    }
    if (input.type === 'price_above' || input.type === 'price_below') {
        const threshold = Number(input.condition.value);
        // Un umbral de precio <= 0 nunca es una regla util y antes se guardaba tal cual (p. ej. -5).
        if (!Number.isFinite(threshold) || threshold <= 0) {
            throw new ValidationError('El precio debe ser mayor que 0', 'value');
        }
    }
    await researchRequest('/api/companies/ensure', {
        method: 'POST',
        body: jsonBody({ ticker: symbol }),
    });
    const alert = await researchRequest<ResearchAlertRule>('/api/alerts', {
        method: 'POST',
        body: jsonBody({
            ticker: symbol,
            alert_type: input.type,
            operator: input.condition.operator,
            value: input.condition.value,
        }),
    });
    const keys = await alertCacheKeys();
    requestCache.invalidate(keys.active);
    requestCache.invalidate(keys.recent(10));
    requestCache.invalidate(keys.recent(20));
    return toAlert(alert);
}

export type CreateAlertResult =
    | { ok: true; alert: Alert }
    | { ok: false; cause: 'validation' | 'duplicate'; message: string };

/**
 * Alta de alerta con los rechazos de negocio como RESULTADO, no como throw.
 *
 * Bug (suite E2E de flujos, 28-oct-2026): un símbolo con formato válido pero
 * inexistente (ZZZQX) llega al backend, que responde 422 «Símbolo no
 * reconocido: ZZZQX. Comprueba que exista en bolsa.». Lanzado desde la server
 * action salía como POST /alerts 500 y, en producción, Next enmascara el
 * mensaje («An error occurred in the Server Components render…»): el
 * cliente lo clasificaba como motor caído y pedía «reintenta en unos
 * segundos» para un símbolo que nunca va a existir. Un 4xx de negocio viaja
 * ahora como dato serializable con su mensaje en español; lo demás (motor
 * caído, sesión) sigue lanzando.
 */
export async function createAlertResult(input: CreateAlertInput): Promise<CreateAlertResult> {
    try {
        return { ok: true, alert: await createAlert(input) };
    } catch (error) {
        if (isNextRedirectError(error)) throw error;
        if (error instanceof AppError) {
            if (error.code === 'VALIDATION_ERROR') {
                return { ok: false, cause: 'validation', message: error.message };
            }
            if (error.code === 'RESEARCH_API_ERROR' && error.statusCode === 409) {
                return { ok: false, cause: 'duplicate', message: 'Ya tienes esta alerta configurada.' };
            }
            if (error.code === 'RESEARCH_API_ERROR' && [400, 404, 422].includes(error.statusCode)) {
                const message = error.statusCode === 404
                    ? `Símbolo no reconocido: ${input.symbol.trim().toUpperCase()}. Comprueba que exista en bolsa.`
                    : error.message;
                return { ok: false, cause: 'validation', message };
            }
        }
        throw error;
    }
}

/**
 * Claves de caché con alcance de usuario: la caché vive en memoria del
 * servidor Next, así que una clave global ("alerts:user:active") podría
 * devolver las alertas de OTRO usuario en el mismo proceso.
 */
async function alertCacheKeys(): Promise<{ user: string; active: string; recent: (limit: number) => string; telegram: string }> {
    const { id } = await requireAuthenticatedUser();
    return {
        user: id,
        active: `alerts:user:${id}:active`,
        recent: (limit: number) => `alerts:user:${id}:recent:${limit}`,
        telegram: `alerts:user:${id}:telegram-status`,
    };
}

// User alerts are a short-lived read: mutations explicitly invalidate the keys.
export async function getUserAlerts(): Promise<Alert[]> {
    const keys = await alertCacheKeys();
    const alerts = await cachedFetch(keys.active, () => researchRequest<ResearchAlertRule[]>('/api/alerts/rules?active=true'), 15);
    return alerts.map(toAlert);
}

export type AlertsLoadCause = 'session' | 'forbidden' | 'rate' | 'offline' | 'unknown';
export type UserAlertsResult =
    | { ok: true; alerts: Alert[] }
    | { ok: false; cause: AlertsLoadCause };

/**
 * Variante con causa explícita para la vista: el AppError pierde su
 * statusCode al cruzar la frontera de la server action, así que la causa se
 * resuelve aquí, en servidor, donde el código de estado es real. Nunca se
 * inventa: solo una sesión local ausente/expirada (AuthenticationError,
 * code AUTH_ERROR, lanzada antes de llamar al backend) prueba 'session' y
 * justifica el enlace de re-login. Un 401 del backend (RESEARCH_API_ERROR)
 * NO prueba sesión caducada — también lo produce una firma de servidor
 * errónea — así que queda 'unknown' con mensaje neutro: nunca se induce al
 * usuario a re-entrar por un fallo del servidor. 403 -> forbidden (permiso
 * denegado, sin re-login), 429 -> rate, AppError 5xx / fallo de red ->
 * offline, cualquier otra cosa -> unknown.
 */
export async function getUserAlertsResult(): Promise<UserAlertsResult> {
    try {
        return { ok: true, alerts: await getUserAlerts() };
    } catch (error) {
        if (isNextRedirectError(error)) throw error;
        let cause: AlertsLoadCause = 'unknown';
        if (error instanceof AppError) {
            if (error.code === 'AUTH_ERROR') cause = 'session';
            else if (error.statusCode === 403) cause = 'forbidden';
            else if (error.statusCode === 429) cause = 'rate';
            else if (error.statusCode >= 500) cause = 'offline';
        } else if (error instanceof Error && /fetch|network|econn|timeout|abort/i.test(error.message)) {
            cause = 'offline';
        }
        return { ok: false, cause };
    }
}

export async function deleteAlert(alertId: string): Promise<void> {
    if (!/^\d+$/.test(alertId)) throw new ValidationError('Invalid alert id', 'alertId');
    await researchRequest(`/api/alerts/rules/${alertId}`, {
        method: 'DELETE',
    });
    const keys = await alertCacheKeys();
    requestCache.invalidate(keys.active);
    requestCache.invalidate(keys.recent(10));
    requestCache.invalidate(keys.recent(20));
}

export interface TelegramStatus {
    enabled: boolean;
    has_bot_token: boolean;
    has_chat_id: boolean;
    configured: boolean;
}

/** GET /api/alerts/telegram-status — presencia de config Telegram (sin secretos). */
// Telegram configuration changes rarely; cache 30s to avoid a request on every render.
export async function getTelegramStatus(): Promise<TelegramStatus> {
    const keys = await alertCacheKeys();
    return cachedFetch(keys.telegram, () => researchRequest<TelegramStatus>('/api/alerts/telegram-status'), 30);
}

export interface TriggeredAlertDelivery {
    id: number;
    title: string;
    message: string;
    severity: string;
    status: string;
    alert_type: string;
    channels: string[];
    deliveries: Record<string, { status: string; attempted_at?: string; error?: string | null }>;
    ticker: string | null;
    /** Hora del ultimo disparo real; null en filas anteriores a la migracion 0036 (se desconoce). */
    triggeredAt: string | null;
    /** URL del documento fuente (filing/noticia/Form 4) cuando el backend la conoce; null si no consta. */
    sourceUrl: string | null;
    companyName: string | null;
    eventDate: string | null;
    eventDateSource: string | null;
    eventForm: string | null;
    /** Titular de la noticia de origen; null si no consta. */
    eventHeadline?: string | null;
    createdAt: string;
}

type ResearchAlertRow = {
    id: number;
    title: string;
    message: string;
    severity: string;
    status: string;
    alert_type: string;
    channels: string[];
    metadata: { deliveries?: TriggeredAlertDelivery['deliveries'] };
    ticker: string | null;
    last_triggered_at: string | null;
    source_url: string | null;
    company_name?: string | null;
    event_date?: string | null;
    event_date_source?: string | null;
    event_form?: string | null;
    event_headline?: string | null;
    created_at: string;
};

/** GET /api/alerts — ultimas alertas disparadas con su estado de entrega por canal. */
export async function getRecentTriggeredAlerts(limit = 20): Promise<TriggeredAlertDelivery[]> {
    const keys = await alertCacheKeys();
    const rows = await cachedFetch(keys.recent(limit), () => researchRequest<ResearchAlertRow[]>(`/api/alerts?limit=${limit}`), 15);
    return (rows ?? []).map((row) => ({
        id: row.id,
        title: row.title,
        message: row.message,
        severity: row.severity,
        status: row.status,
        alert_type: row.alert_type,
        channels: row.channels ?? [],
        deliveries: row.metadata?.deliveries ?? {},
        ticker: row.ticker ?? null,
        // Sin fallback silencioso: en filas antiguas se desconoce la hora del
        // ultimo disparo y la UI etiqueta created_at como «Creada», no como disparo.
        triggeredAt: row.last_triggered_at ?? null,
        sourceUrl: row.source_url ?? null,
        companyName: row.company_name ?? null,
        eventDate: row.event_date ?? null,
        eventDateSource: row.event_date_source ?? null,
        eventForm: row.event_form ?? null,
        eventHeadline: row.event_headline ?? null,
        createdAt: row.created_at,
    }));
}
