/**
 * Eventos guardados del gráfico «Precio y eventos». El backend
 * (company_events_service.stored_timeline_events) escribe en castellano el
 * título y el detalle de resultados, ex-dividendos y compras/ventas de
 * directivos. En inglés se reescriben con el catálogo; los titulares de
 * noticias y filings son contenido de la fuente y no se tocan. En castellano,
 * o con un texto que no se reconoce, el evento pasa tal cual.
 */
import type { PriceEvent } from '@/lib/market/price-events';
import type { Locale } from '@/lib/i18n/locale';
import { createTranslator, type TranslateFn } from '@/lib/i18n/translate';

const RESULTS_LABEL = /^Resultados (.+)$/;
const DIVIDEND_DETAIL = /^(\S+) (\S+) por acción$/;
const INSIDER_TITLE = /^(.+) (compra|vende) acciones$/;
const INSIDER_DETAIL = /^Operación de (\d{1,3}(?:\.\d{3})*) \$ \(formulario (.+)\)$/;

function resultsText(event: PriceEvent, t: TranslateFn): PriceEvent {
  const label = RESULTS_LABEL.exec(event.title);
  const title = event.title === 'Resultados'
    ? t('research.chart.storedEvent.resultsTitle')
    : label ? t('research.chart.storedEvent.resultsTitleLabel', { label: label[1] }) : event.title;
  const detail = event.detail === 'Fecha confirmada por la fuente' ? t('research.chart.storedEvent.resultsConfirmed') : event.detail;
  return { ...event, title, detail };
}

function dividendText(event: PriceEvent, t: TranslateFn): PriceEvent {
  const title = event.title === 'Ex-dividendo' ? t('research.chart.storedEvent.exDividendTitle') : event.title;
  const amount = event.detail ? DIVIDEND_DETAIL.exec(event.detail) : null;
  const detail = amount ? t('research.chart.storedEvent.exDividendDetail', { amount: amount[1], currency: amount[2] }) : event.detail;
  return { ...event, title, detail };
}

function insiderText(event: PriceEvent, t: TranslateFn): PriceEvent {
  const who = INSIDER_TITLE.exec(event.title);
  let title = event.title;
  if (who) {
    const name = who[1] === 'Un directivo' ? t('research.chart.storedEvent.insiderSomeone') : who[1];
    title = who[2] === 'compra' ? t('research.chart.storedEvent.insiderBuys', { name }) : t('research.chart.storedEvent.insiderSells', { name });
  }
  const trade = event.detail ? INSIDER_DETAIL.exec(event.detail) : null;
  const detail = trade ? t('research.chart.storedEvent.insiderDetail', { value: trade[1].replace(/\./g, ','), form: trade[2] }) : event.detail;
  return { ...event, title, detail };
}

export function storedEventText(event: PriceEvent, locale: Locale): PriceEvent {
  if (locale !== 'en') return event;
  const t = createTranslator(locale);
  if (event.kind === 'results') return resultsText(event, t);
  if (event.kind === 'ex_dividend') return dividendText(event, t);
  if (event.kind === 'insider') return insiderText(event, t);
  return event;
}
