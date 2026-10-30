import type { TriggeredAlertDelivery } from '@/lib/actions/alerts.actions';
import type { Locale } from '@/lib/i18n/locale';
import type { TranslateFn } from '@/lib/i18n/translate';

export type AlertCardCopy = {
    heading: string;
    summary: string;
    technical: string;
    /** Sufijo de fecha realmente usado en el heading (con su « · »), para que
     *  quien renderiza pueda quitarlo cuando repite la fecha de entrega. */
    dateSuffix: string | null;
};

function eventDateLabel(alert: TriggeredAlertDelivery, locale: Locale): string | null {
    // The event date is only shown when the API has a source-backed date.
    // GDELT's first-seen is labeled instead of passing as publication.
    const parsedDate = alert.eventDate ? new Date(alert.eventDate) : null;
    const eventDate = parsedDate && !Number.isNaN(parsedDate.getTime())
        ? new Intl.DateTimeFormat(locale === 'en' ? 'en-GB' : 'es-ES', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'Europe/Madrid' }).format(parsedDate)
        : null;
    return eventDate && eventDate !== 'N/D' ? eventDate : null;
}

/** No prose is inferred from a model score or an external headline. */
export function alertCardCopy(alert: TriggeredAlertDelivery, t: TranslateFn, locale: Locale): AlertCardCopy {
    const company = alert.companyName?.trim() || alert.ticker || null;
    const form = /^(?:10-K|10-Q|8-K|20-F|6-K)$/.test(alert.eventForm ?? '') ? alert.eventForm : null;
    const kind = form ?? (alert.alert_type === 'tracked_news' ? t('alerts.card.kindNews') : alert.alert_type === 'news_material_update' ? t('alerts.card.kindMaterialNews') : t('alerts.card.kindAlert'));
    const date = eventDateLabel(alert, locale);
    const dateSuffix = date ? ` · ${alert.eventDateSource === 'gdelt_first_seen' ? t('alerts.card.dateDetected', { date }) : date}` : null;
    const suffix = dateSuffix ?? '';
    if (!company) {
        // Portfolio-level alerts (daily digest) and unlinked ones have no company:
        // never print a placeholder company, show the alert's own title.
        const title = alert.title?.trim() || kind;
        return {
            heading: `${title}${suffix}`,
            summary: alert.alert_type === 'daily_digest'
                ? t('alerts.card.summaryDailyDigest')
                : alert.alert_type === 'macro_event'
                    ? t('alerts.card.summaryMacroEvent')
                    : t('alerts.card.summaryUnlinked'),
            technical: `${alert.title}\n${alert.message}`,
            dateSuffix,
        };
    }
    const headline = alert.eventHeadline?.trim() || null;
    const summary = form
        ? t('alerts.card.formSummary', { form, company })
        : alert.alert_type === 'tracked_news'
            ? trackedNewsSummary(alert, company, t)
            : alert.alert_type.includes('news')
                // El titular viene de la noticia de origen (news_events.title). Sin él no se rellena con frases genéricas.
                ? (headline ?? t('alerts.card.newsNoHeadline', { company }))
                : alertOwnText(alert, company, t);
    return { heading: `${company} · ${kind}${suffix}`, summary, technical: `${alert.title}\n${alert.message}`, dateSuffix };
}

/** Las tarjetas pintan el resumen como titular enlazado a la fuente (tracked_news, o noticia con titular de origen). */
export function alertSummaryIsSourceHeadline(alert: Pick<TriggeredAlertDelivery, 'alert_type' | 'eventHeadline'>): boolean {
    return alert.alert_type === 'tracked_news' || (alert.alert_type.includes('news') && Boolean(alert.eventHeadline?.trim()));
}

/** El titular de la noticia viaja en el título de la alerta ("Noticia sobre TICKER: titular",
 *  tracked_news_alerts.py): se muestra tal cual viene de la fuente (el prefijo es dato del
 *  backend, no copy de UI). Si la alerta es antigua y no trae titular, se mantiene la frase
 *  genérica (nunca se inventa contenido). */
function trackedNewsSummary(alert: TriggeredAlertDelivery, company: string, t: TranslateFn): string {
    const title = alert.title.trim();
    const headline = title.replace(/^Noticia sobre [^:]+:\s*/i, '').trim();
    return headline && headline !== title ? headline : t('alerts.card.trackedNewsFallback', { company });
}

/** Texto propio de la alerta (regla, posiciones cortas, cribado) en vez de una frase genérica. */
function alertOwnText(alert: TriggeredAlertDelivery, company: string, t: TranslateFn): string {
    const message = (alert.message ?? '').replace(/\s+/g, ' ').trim();
    if (/rule matched: observed=/i.test(message)) {
        return t('alerts.card.ruleMatched', { title: alert.title.trim(), company });
    }
  if (message && message.length <= 280 && !/^[\w.-]+: [A-Z][a-z]+ .*\b(found|classified|requires)\b/.test(message)) {
    return message;
  }
  return t('alerts.card.fallback', { company, title: alert.title.trim() || t('alerts.card.fallbackNoDetail') });
}
