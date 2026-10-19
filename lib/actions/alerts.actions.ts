'use server';

import { jsonBody, researchRequest } from '@/lib/research/client';
import { cachedFetch } from '@/lib/cache/memoryTTL';
import { requestCache } from '@/lib/cache/requestCache';
import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import { ValidationError } from '@/lib/types/errors';

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
