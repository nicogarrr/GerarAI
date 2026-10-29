import type { TriggeredAlertDelivery } from '@/lib/actions/alerts.actions';

/** No prose is inferred from a model score or an external headline. */
export function alertCardCopy(alert: TriggeredAlertDelivery): { heading: string; summary: string; technical: string } {
  const company = alert.companyName?.trim() || alert.ticker || null;
  const form = /^(?:10-K|10-Q|8-K|20-F|6-K)$/.test(alert.eventForm ?? '') ? alert.eventForm : null;
  const kind = form ?? (alert.alert_type === 'tracked_news' ? 'Noticia' : alert.alert_type === 'news_material_update' ? 'Noticia material' : 'Alerta');
  // The event date is only shown when the API has a source-backed date.
  // GDELT's first-seen is labeled instead of passing as publication.
  const parsedDate = alert.eventDate ? new Date(alert.eventDate) : null;
  const eventDate = parsedDate && !Number.isNaN(parsedDate.getTime())
    ? new Intl.DateTimeFormat('es-ES', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'Europe/Madrid' }).format(parsedDate)
    : null;
  const date = eventDate && eventDate !== 'N/D' ? eventDate : null;
  const suffix = date ? ` · ${alert.eventDateSource === 'gdelt_first_seen' ? 'detectada ' : ''}${date}` : '';
  if (!company) {
    // Portfolio-level alerts (daily digest) and unlinked ones have no company:
    // never print a placeholder company, show the alert's own title.
    const title = alert.title?.trim() || kind;
    return {
      heading: `${title}${suffix}`,
      summary: alert.alert_type === 'daily_digest'
        ? 'Resumen diario de tu cartera; abre el detalle para ver la cobertura de datos.'
        : alert.alert_type === 'macro_event'
          ? 'Recordatorio del calendario macro oficial; el detalle indica la fuente y la hora.'
          : 'Alerta sin empresa asociada.',
      technical: `${alert.title}\n${alert.message}`,
    };
  }
  const headline = alert.eventHeadline?.trim() || null;
  const summary = form
    ? `Documento ${form} asociado a ${company}.`
    : alert.alert_type === 'tracked_news'
      ? trackedNewsSummary(alert, company)
      : alert.alert_type.includes('news')
        // El titular viene de la noticia de origen (news_events.title). Sin él no se rellena con frases genéricas.
        ? (headline ?? `Noticia sobre ${company}; el aviso no trae titular verificable.`)
        : alertOwnText(alert, company);
  return { heading: `${company} · ${kind}${suffix}`, summary, technical: `${alert.title}\n${alert.message}` };
}

/** Las tarjetas pintan el resumen como titular enlazado a la fuente (tracked_news, o noticia con titular de origen). */
export function alertSummaryIsSourceHeadline(alert: Pick<TriggeredAlertDelivery, 'alert_type' | 'eventHeadline'>): boolean {
  return alert.alert_type === 'tracked_news' || (alert.alert_type.includes('news') && Boolean(alert.eventHeadline?.trim()));
}

/** El titular de la noticia viaja en el título de la alerta ("Noticia sobre TICKER: titular",
 *  tracked_news_alerts.py): se muestra tal cual viene de la fuente. Si la alerta es antigua y
 *  no trae titular, se mantiene la frase genérica (nunca se inventa contenido). */
function trackedNewsSummary(alert: TriggeredAlertDelivery, company: string): string {
  const title = alert.title.trim();
  const headline = title.replace(/^Noticia sobre [^:]+:\s*/i, '').trim();
  return headline && headline !== title ? headline : `Noticia sobre ${company}.`;
}

/** Texto propio de la alerta (regla, posiciones cortas, cribado) en vez de una frase genérica. */
function alertOwnText(alert: TriggeredAlertDelivery, company: string): string {
  const message = (alert.message ?? '').replace(/\s+/g, ' ').trim();
  if (/rule matched: observed=/i.test(message)) {
    return `Se cumplió la regla «${alert.title.trim()}» para ${company}.`;
  }
  if (message && message.length <= 280 && !/^[\w.-]+: [A-Z][a-z]+ .*\b(found|classified|requires)\b/.test(message)) {
    return message;
  }
  return `Alerta de ${company}: ${alert.title.trim() || 'sin detalle disponible'}.`;
}
