import { AlertTriangle } from 'lucide-react';
import Link from 'next/link';
import { EmptyLink, EmptyState } from '@/components/ui/empty-state';
import { TickerContextBadges } from '@/components/common/TickerContextBadges';
import type { ResearchNewsEvent } from '@/lib/actions/research.actions';
import type { NewsLane } from '@/lib/news-paging';
import { formatPercent, formatUserDateTime, NA } from '@/lib/format';
import { NewsHeadline } from '@/components/research/NewsHeadline';
import { NewsSecondOrder } from '@/components/research/NewsSecondOrder';
import { etiquetaDireccionImpacto, etiquetaTemaMacro, etiquetaTierFuente, etiquetaTipoEvento } from "@/lib/labels";

const CARRILES = [
  { key: null, label: 'Todas' },
  { key: 'empresa', label: 'Empresas' },
  { key: 'macro', label: 'Macro' },
] as const;

function carrilHref(lane: NewsLane, ticker?: string | null): string {
  const query = new URLSearchParams();
  if (lane) query.set('lane', lane);
  if (ticker) query.set('ticker', ticker);
  const text = query.toString();
  return text ? `/research/news?${text}` : '/research/news';
}

const PAGER_LINK = 'rounded-lg border border-gray-800 px-3 py-1.5 text-sm text-gray-300 hover:border-gray-700';
const PAGER_OFF = 'rounded-lg border border-gray-900 px-3 py-1.5 text-sm text-gray-700';

function newsPageHref(lane: NewsLane, page: number, ticker?: string | null): string {
  const query = new URLSearchParams();
  if (lane) query.set('lane', lane);
  if (ticker) query.set('ticker', ticker);
  if (page > 1) query.set('pagina', String(page));
  const text = query.toString();
  return text ? `/research/news?${text}` : '/research/news';
}

function NewsPager({label,lane,page,hasMore,ticker}:{label:string;lane:NewsLane;page:number;hasMore:boolean;ticker?:string|null}){
 return (
        <nav aria-label={label} className="mt-4 flex items-center justify-between gap-4">
          {page > 1 ? (
            <Link className={PAGER_LINK} href={newsPageHref(lane, page - 1, ticker)} rel="prev">Anterior</Link>
          ) : (
            <span aria-disabled="true" className={PAGER_OFF}>Anterior</span>
          )}
          <span className="text-sm text-gray-500">Página {page}</span>
          {hasMore ? (
            <Link className={PAGER_LINK} href={newsPageHref(lane, page + 1, ticker)} rel="next">Siguiente</Link>
          ) : (
            <span aria-disabled="true" className={PAGER_OFF}>Siguiente</span>
          )}
        </nav>
 );
}

/**
 * Flujo de eventos paginado dentro de la página (sin scroll infinito): el
 * servidor entrega la página `?pagina=N` de NEWS_PAGE_SIZE eventos y los
 * enlaces Anterior/Siguiente la cambian. El carril se filtra en la API (no
 * sobre una ventana fija), así que "Macro" y "Empresas" recorren todo el histórico.
 */
/** Fecha del evento; con hora solo si la fuente trae una hora real (no medianoche UTC por defecto). */
function eventDateText(value: string): string {
  const day = value.split('T')[0];
  const match = /T(\d{2}:\d{2})/.exec(value);
  if (!match || match[1] === '00:00') return day;
  const formatted = formatUserDateTime(value);
  return formatted === NA ? day : formatted;
}

export function NewsEventsFlow({
  events,
  hasMore,
  lane,
  page,
  ticker,
  portfolioTickers,
  watchlistTickers,
}: {
  events: ResearchNewsEvent[];
  hasMore: boolean;
  lane: NewsLane;
  page: number;
  ticker?: string | null;
  portfolioTickers: string[];
  watchlistTickers: string[];
}) {
  const portfolioSet = new Set(portfolioTickers);
  const watchlistSet = new Set(watchlistTickers);
  return (
    <section className="rounded-lg border border-gray-800 bg-surface-1 p-5">
        <div className="mb-4 flex items-center gap-2">
          <AlertTriangle aria-hidden="true" className="h-5 w-5 text-teal-300" />
          <h2 className="text-lg font-semibold text-gray-100">Flujo de eventos</h2>
        </div>
        <NewsPager label="Paginación" lane={lane} page={page} hasMore={hasMore} ticker={ticker} />
        <nav aria-label="Filtrar por carril" className="mb-4 flex flex-wrap items-center gap-2 text-xs">
          {CARRILES.map((option) => {
            const active = lane === option.key;
            return (
              <Link
                aria-current={active ? 'page' : undefined}
                className={`rounded-full border px-3 py-1 ${
                  active
                    ? 'border-teal-500 bg-teal-950/60 font-semibold text-teal-300'
                    : 'border-gray-800 text-gray-400 hover:text-gray-200'
                }`}
                href={carrilHref(option.key, ticker)}
                key={option.label}
              >
                {option.label}
              </Link>
            );
          })}
          <span className="text-gray-500">
            {events.length} {events.length === 1 ? 'evento' : 'eventos'} en la página {page}
          </span>
        </nav>
        {/* F176: sin contain, Chrome propaga el overflow horizontal de la
            tabla al documento entero (zoom-out y recorte en movil) aunque la
            region ya scrolla por dentro; layout+paint lo contiene aqui. */}
        {/* Movil: una tarjeta por noticia (titular completo, fecha, fuente). La
            tabla de 5 columnas solo se usa desde md; en pantallas estrechas
            cortaba titulares y partia el layout. */}
        <ul aria-label="Eventos de noticias" className="flex flex-col gap-3 md:hidden">
          {events.map((event) => {
            const materialityColor =
              event.materiality_score >= 7
                ? 'text-red-400'
                : event.materiality_score >= 4
                  ? 'text-amber-400'
                  : 'text-gray-500';
            return (
              <li className="rounded-lg border border-gray-800 bg-black/20 p-3" key={`card-${event.id}`}>
                <div className="flex flex-wrap items-center gap-2 text-xs text-gray-400">
                  {event.ticker ? (
                    <Link className="inline-flex min-h-11 items-center font-semibold text-teal-300 hover:text-teal-200" href={`/research/${event.ticker}`}>
                      {event.ticker}
                    </Link>
                  ) : null}
                  {event.ticker ? (
                    <TickerContextBadges
                      portfolioTickers={portfolioSet}
                      ticker={event.ticker}
                      watchlistTickers={watchlistSet}
                    />
                  ) : null}
                  {event.news_lane === 'macro' ? (
                    <span className="rounded-full bg-indigo-950/60 px-2 py-0.5 font-semibold text-indigo-300">
                      macro{event.macro_theme ? ` · ${etiquetaTemaMacro(event.macro_theme)}` : ''}
                    </span>
                  ) : null}
                  <span>{eventDateText(event.date)}</span>
                  {event.date_source === 'gdelt_first_seen' ? (
                    <span className="rounded-full bg-gray-900 px-2 py-0.5 text-gray-400" title="Fecha de primera detección en GDELT, no de publicación">vía GDELT</span>
                  ) : null}
                  {event.date_source === 'ingested_at_fallback' ? (
                    <span className="rounded-full bg-gray-900 px-2 py-0.5 text-gray-400">fecha de ingesta</span>
                  ) : null}
                  <span className={`ml-auto font-semibold ${materialityColor}`}>{event.materiality_score}</span>
                </div>
                <div className="mt-2 text-sm text-gray-200"><NewsHeadline event={event} /></div>
                <NewsSecondOrder eventId={event.id} />
                <div className="mt-2 flex items-center justify-between gap-2 text-xs text-gray-500">
                  <span className="min-w-0 break-words">{event.source || NA}</span>
                  {event.requires_update ? (
                    <span className="shrink-0 rounded-full bg-amber-950/60 px-2 py-0.5 text-amber-300">Revisar</span>
                  ) : null}
                </div>
              </li>
            );
          })}
        </ul>
        <div aria-label="Flujo de eventos de noticias" className="scroll-affordance-x overflow-x-auto [contain:layout_paint] hidden md:block" role="region" tabIndex={0}>
          <table className="w-full min-w-[650px] text-left text-sm">
            <caption className="sr-only">Eventos de noticias con materialidad y detalles de la fuente por fila</caption>
            <thead className="text-xs uppercase text-gray-500">
              <tr>
                <th className="border-b border-gray-800 py-2" scope="col">Ticker</th>
                <th className="border-b border-gray-800 px-3 py-2" scope="col">Fecha</th>
                <th className="border-b border-gray-800 px-3 py-2" scope="col">Titular</th>
                <th className="border-b border-gray-800 px-3 py-2 text-center" scope="col">Materialidad</th>
                <th className="border-b border-gray-800 px-3 py-2" scope="col">Estado y detalle</th>
              </tr>
            </thead>
            <tbody>
              {events.map((event) => {
                const materialityColor =
                  event.materiality_score >= 7
                    ? 'text-red-400'
                    : event.materiality_score >= 4
                      ? 'text-amber-400'
                      : 'text-gray-500';

                return (
                  <tr key={event.id} className="border-b border-gray-900 last:border-0">
                    <th className="py-3 text-left text-sm font-semibold" scope="row">
                      {event.ticker ? (
                        <Link
                          className="inline-flex min-h-11 items-center text-teal-300 hover:text-teal-200"
                          href={`/research/${event.ticker}`}
                        >
                          {event.ticker}
                        </Link>
                      ) : (
                        <span className="text-gray-500">—</span>
                      )}
                      {event.ticker ? (
                        <TickerContextBadges
                          portfolioTickers={portfolioSet}
                          ticker={event.ticker}
                          watchlistTickers={watchlistSet}
                        />
                      ) : null}
                      {event.news_lane === 'macro' ? (
                        <div className="mt-1">
                          <span className="rounded-full bg-indigo-950/60 px-2 py-0.5 text-xs font-semibold text-indigo-300">
                            macro{event.macro_theme ? ` · ${etiquetaTemaMacro(event.macro_theme)}` : ''}
                          </span>
                        </div>
                      ) : null}
                    </th>
                    <td className="min-w-[150px] px-3 py-3 text-gray-400">
                      <div>{eventDateText(event.date)}</div>
                      {event.date_source === 'ingested_at_fallback' ? (
                        <div className="mt-1 text-xs text-gray-500">fecha de ingesta · la fuente no da fecha</div>
                      ) : null}
                      {event.date_source === 'gdelt_first_seen' ? (
                        <div className="mt-1 text-xs text-gray-500" title="Fecha de primera detección en GDELT, no de publicación">vía GDELT</div>
                      ) : null}
                    </td>
                    <td className="max-w-[360px] px-3 py-3 text-gray-300">
                      <NewsHeadline event={event} />
                    </td>
                    <td className="py-3 text-center">
                      <span className={`font-semibold ${materialityColor}`}>{event.materiality_score}</span>
                    </td>
                    <td className="py-3 text-gray-300">
                      {event.requires_update ? <span className="rounded-full bg-amber-950/60 px-2 py-0.5 text-xs text-amber-300">Revisar</span> : <span className="rounded-full bg-gray-900 px-2 py-0.5 text-xs text-gray-400">Sin revisión pendiente</span>}
                      <details className="mt-2 max-w-xs text-xs text-gray-400">
                        <summary className="min-h-10 cursor-pointer py-2 text-teal-300">Ver contexto</summary>
                        <dl className="mt-1 space-y-1 break-words rounded-md border border-gray-800 p-2">
                          <div><dt className="inline font-medium">Fuente: </dt><dd className="inline">{event.source || NA}</dd></div>
                          <div><dt className="inline font-medium">Tipo: </dt><dd className="inline">{etiquetaTipoEvento(event.event_type)}</dd></div>
                          {/* Datos decisionales reubicados (SERIE 1, auditoria): nunca crudos, nulos etiquetados "sin datos". */}
                          <div><dt className="inline font-medium">Tier de fuente: </dt><dd className="inline">{event.source_tier ? etiquetaTierFuente(event.source_tier) : NA}</dd></div>
                          <div><dt className="inline font-medium">Impacto: </dt><dd className="inline">{event.impact_direction ? etiquetaDireccionImpacto(event.impact_direction) : NA}</dd></div>
                          <div><dt className="inline font-medium">Peso en cartera: </dt><dd className="inline">{event.portfolio_weight != null ? formatPercent(event.portfolio_weight, { digits: 1 }) : NA}</dd></div>
                          {event.news_lane === 'macro' && event.macro_theme ? <div><dt className="inline font-medium">Tema: </dt><dd className="inline">{etiquetaTemaMacro(event.macro_theme)}</dd></div> : null}
                        </dl>
                      </details>
                      <NewsSecondOrder eventId={event.id} />
                    </td>
                  </tr>
                );
              })}
              {!events.length ? (
                <tr>
                  <td className="p-0" colSpan={5}>
                    <EmptyState
                      action={<EmptyLink href="/research/sources">Importa una fuente o analiza una noticia manual</EmptyLink>}
                      className="rounded-none border-0 p-6"
                      title="Sin eventos de noticias todavía."
                    />
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
        <NewsPager label="Paginación inferior" lane={lane} page={page} hasMore={hasMore} />
      </section>
  );
}
