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
        : 'Alerta sin empresa asociada; consulta la regla y la fuente antes de actuar.',
      technical: `${alert.title}\n${alert.message}`,
    };
  }
  const summary = form
    ? `Documento ${form} asociado a ${company}; revisa la fuente antes de cambiar la tesis.`
    : alert.alert_type === 'tracked_news'
      ? `Noticia sobre ${company}; revisa la fuente antes de sacar conclusiones.`
      : alert.alert_type.includes('news')
        ? `Noticia marcada para revisión de la tesis de ${company}; el impacto aún debe verificarse.`
        : alertOwnText(alert, company);
  return { heading: `${company} · ${kind}${suffix}`, summary, technical: `${alert.title}\n${alert.message}` };
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
