// @ts-expect-error TS5097: node --test (--experimental-strip-types) necesita la extensión.
import { t as esT, type TranslationKey, type TranslationVars } from '../i18n/t.ts';

/** Traductor del idioma elegido; por defecto el español de referencia. */
type TiFn = (key: TranslationKey, vars?: TranslationVars) => string;

/**
 * Etiquetas ES de canal y estado de entrega de una alerta. El valor interno
 * (in_app, delivered...) no se enseña tal cual; uno desconocido se muestra
 * crudo (visible y honesto, nunca inventado). «sin registro» = el motor no
 * guardó entrega para ese canal: no se disfraza de pendiente ni de entregada.
 */
const CANALES: Record<string, TranslationKey> = {
    in_app: 'alerts.deliveryLabels.channel.inApp',
    email: 'alerts.deliveryLabels.channel.email',
    telegram: 'alerts.deliveryLabels.channel.telegram',
    push: 'alerts.deliveryLabels.channel.push',
};

const ESTADOS_ENTREGA: Record<string, TranslationKey> = {
    delivered: 'alerts.deliveryLabels.status.delivered',
    failed: 'alerts.deliveryLabels.status.failed',
    pending: 'alerts.deliveryLabels.status.pending',
    skipped: 'alerts.deliveryLabels.status.skipped',
    'sin registro': 'alerts.deliveryLabels.status.none',
};

export function etiquetaCanal(value: string, ti: TiFn = esT): string {
    const key = Object.hasOwn(CANALES, value) ? CANALES[value] : undefined;
    return key ? ti(key) : value;
}

export function etiquetaEstadoEntrega(value: string, ti: TiFn = esT): string {
    const key = Object.hasOwn(ESTADOS_ENTREGA, value) ? ESTADOS_ENTREGA[value] : undefined;
    return key ? ti(key) : value;
}
