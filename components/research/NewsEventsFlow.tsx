import { AlertTriangle } from 'lucide-react';
import Link from 'next/link';
import { EmptyLink, EmptyState } from '@/components/ui/empty-state';
import { TickerContextBadges } from '@/components/common/TickerContextBadges';
import type { ResearchNewsEvent } from '@/lib/actions/research.actions';
import type { NewsLane } from '@/lib/news-paging';
import { formatPercent, formatTimeAgo, formatUserDate, formatUserDateTime, NA } from '@/lib/format';
import { NewsHeadline } from '@/components/research/NewsHeadline';
import { NewsSummary } from './NewsSummary';
import { NewsSecondOrder } from '@/components/research/NewsSecondOrder';
import { etiquetaDireccionImpacto, etiquetaTemaMacro, etiquetaTierFuente, etiquetaTipoEvento } from "@/lib/labels";

const CARRILES = [
  { key: null, label: 'Todas' },
  { key: 'para-ti', label: 'Para ti' },
  { key: 'empresa', label: 'Empresas' },
  { key: 'gobierno', label: 'Gobierno' },
  { key: 'macro', label: 'Macro' },
] as const;

function carrilHref(lane: NewsLane, ticker?: string | null): string {
  const query = new URLSearchParams();
  if (lane) query.set('lane', lane);
  if (ticker) query.set('ticker', ticker);
  const text = query.toString();
  return text ? `/research/news?${text}` : '/research/news';
}

/** Paginación dentro de la ficha de empresa: las noticias son una sección
 *  del Resumen (/research/T?pagina=N#noticias); el usuario no sale del
 *  contexto de la acción. */
function fichaNewsPageHref(ticker: string, page: number): string {
  const query = new URLSearchParams();
  if (page > 1) query.set('pagina', String(page));
  const text = query.toString();
  return `/research/${encodeURIComponent(ticker)}${text ? `?${text}` : ''}#noticias`;
}

const PAGER_LINK = 'inline-flex min-h-11 min-w-11 items-center rounded-lg border border-gray-700 bg-black/30 px-4 py-2 text-sm font-medium text-gray-200 hover:border-teal-600 hover:text-teal-200';
const PAGER_OFF = 'inline-flex min-h-11 min-w-11 items-center rounded-lg border border-gray-900 px-4 py-2 text-sm text-gray-700';

function newsPageHref(lane: NewsLane, page: number, ticker?: string | null): string {
  const query = new URLSearchParams();
  if (lane) query.set('lane', lane);
  if (ticker) query.set('ticker', ticker);
  if (page > 1) query.set('pagina', String(page));
  const text = query.toString();
  return text ? `/research/news?${text}` : '/research/news';
}

function NewsPager({label,lane,page,hasMore,ticker,inFicha}:{label:string;lane:NewsLane;page:number;hasMore:boolean;ticker?:string|null;inFicha?:boolean}){
 const href = (target: number) =>
   inFicha && ticker ? fichaNewsPageHref(ticker, target) : newsPageHref(lane, target, ticker);
 return (
        <nav aria-label={label} className="mt-4 flex items-center justify-between gap-4">
          {page > 1 ? (
            <Link className={PAGER_LINK} href={href(page - 1)} rel="prev">← Anterior</Link>
          ) : (
            <span aria-disabled="true" className={PAGER_OFF}>← Anterior</span>
          )}
          <span className="text-sm font-medium text-gray-400">Página {page}</span>
          {hasMore ? (
            <Link className={PAGER_LINK} href={href(page + 1)} rel="next">Siguiente →</Link>
          ) : (
            <span aria-disabled="true" className={PAGER_OFF}>Siguiente →</span>
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
/** Fecha del evento; con hora solo si la fuente trae una hora real (no medianoche UTC por defecto).
 *  El día sin hora se pinta en es-ES con formatUserDate (día de calendario literal, sin
 *  desplazamiento por zona); antes se devolvía el ISO crudo («2026-10-27»). */
export function eventDateText(value: string): string {
  const day = value.split('T')[0];
  const match = /T(\d{2}:\d{2})/.exec(value);
  if (!match || match[1] === '00:00') return formatUserDate(day);
  const formatted = formatUserDateTime(value);
  return formatted === NA ? formatUserDate(day) : formatted;
}

/** Materialidad como indicador visual: barra proporcional + número, color por impacto. */
function MaterialityIndicator({ score }: { score: number }) {
  const clamped = Math.min(10, Math.max(0, score));
  const color =
    clamped >= 7 ? 'bg-red-400' : clamped >= 4 ? 'bg-amber-400' : 'bg-gray-600';
  const text =
    clamped >= 7 ? 'text-red-400' : clamped >= 4 ? 'text-amber-400' : 'text-gray-500';
  return (
    <span
      className="inline-flex items-center justify-center gap-2"
      title={`Materialidad ${score} de 10: ${clamped >= 7 ? 'alta' : clamped >= 4 ? 'media' : 'baja'}`}
      aria-label={`Materialidad ${score} de 10: ${clamped >= 7 ? 'alta' : clamped >= 4 ? 'media' : 'baja'}`}
    >
      <span aria-hidden="true" className="h-1.5 w-10 overflow-hidden rounded-full bg-gray-800">
        <span className={`block h-full ${color}`} style={{ width: `${clamped * 10}%` }} />
      </span>
      <span className={`font-semibold ${text}`}>{score}</span>
    </span>
  );
}

/** Buena/mala al lado de cada noticia: lectura automática por reglas del
 *  titular (MaterialityService, determinista), NO un dato de la fuente ni una
 *  recomendación. Se declara como lectura automática en title/aria. */
const IMPACTO_ESTILO: Record<string, string> = {
  positive: 'bg-teal-950/60 text-teal-300',
  negative: 'bg-red-950/60 text-red-300',
  neutral: 'bg-gray-800/60 text-gray-400',
  mixed: 'bg-amber-950/60 text-amber-300',
};

export function ImpactBadge({
  direction,
  eventType,
}: {
  direction?: string | null;
  eventType?: string | null;
}) {
  if (!direction) return null;
  const estilo = IMPACTO_ESTILO[direction] ?? 'bg-gray-800/60 text-gray-400';
  const nota = 'Lectura automática del titular por reglas; no es un dato de la fuente.';
  // Motivo en una línea: el tipo de evento casado por las reglas (dilución,
  // resultados…). «Noticia general» y «Desconocido» no explican nada: se
  // omiten en vez de añadir relleno.
  const motivo =
    eventType && eventType !== 'general_news' && eventType !== 'unknown'
      ? etiquetaTipoEvento(eventType)
      : null;
  return (
    <span
      aria-label={`Impacto ${etiquetaDireccionImpacto(direction)}${motivo ? `, motivo: ${motivo}` : ''}. ${nota}`}
      className={`rounded-full px-2 py-0.5 text-xs font-semibold ${estilo}`}
      title={nota}
    >
      {etiquetaDireccionImpacto(direction)}
      {motivo ? ` · ${motivo}` : ''}
    </span>
  );
}

/** «N fuentes»: la misma historia la cubrieron varios medios y la portada la
 *  agrupa en una fila (PR story clusters). El detalle lista las fuentes. */
function CoverageChip({ event }: { event: ResearchNewsEvent }) {
  if (!event.coverage_count || event.coverage_count < 2) return null;
  return (
    <span
      className="rounded-full bg-teal-950/60 px-2 py-0.5 text-xs font-semibold text-teal-300"
      title="La misma historia publicada por varios medios, agrupada"
    >
      {event.coverage_count} fuentes
    </span>
  );
}

/** Fuentes absorbidas por la agrupación de historia, dentro del detalle. */
function CoverageDetail({ event }: { event: ResearchNewsEvent }) {
  if (!event.coverage?.length) return null;
  return (
    <div className="mt-1 max-w-xs space-y-1 break-words rounded-md border border-gray-800 p-2">
      <div className="font-medium">También lo cubrieron:</div>
      <div className="space-y-0.5">
        {event.coverage.map((item, idx) => (
          <div key={`${item.url ?? item.source}-${idx}`}>
            {item.url ? (
              <a className="text-teal-300 hover:text-teal-200" href={item.url} rel="noreferrer" target="_blank">
                {item.source || 'Fuente sin nombre'}
              </a>
            ) : (
              <span>{item.source || 'Fuente sin nombre'}</span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function MacroChip({ event }: { event: ResearchNewsEvent }) {
  if (event.news_lane !== 'macro') return null;
  return (
    <span className="rounded-full bg-indigo-950/60 px-2 py-0.5 text-xs font-semibold text-indigo-300">
      macro{event.macro_theme ? ` · ${etiquetaTemaMacro(event.macro_theme)}` : ''}
    </span>
  );
}

function GobiernoChip({ event }: { event: ResearchNewsEvent }) {
  if (event.news_lane !== 'gobierno') return null;
  return (
    <span className="rounded-full bg-sky-950/60 px-2 py-0.5 text-xs font-semibold text-sky-300">
      gobierno · oficial
    </span>
  );
}

function DateNotes({ event, inline = false }: { event: ResearchNewsEvent; inline?: boolean }) {
  const className = inline ? 'text-gray-500' : 'mt-1 text-xs text-gray-500';
  const Tag = inline ? 'span' : 'div';
  const prefix = inline ? '· ' : '';
  return (
    <>
      {event.date_source === 'ingested_at_fallback' ? (
        <Tag className={className}>{prefix}fecha de ingesta · la fuente no da fecha</Tag>
      ) : null}
      {event.date_source === 'gdelt_first_seen' ? (
        <Tag className={className} title="Fecha de primera detección en GDELT, no de publicación">{prefix}vía GDELT</Tag>
      ) : null}
    </>
  );
}

/** Detalle de contexto de la fila; va dentro del único desplegable (NewsSecondOrder). */
function ContextDetail({ event }: { event: ResearchNewsEvent }) {
  return (
    <dl className="mt-1 max-w-xs space-y-1 break-words rounded-md border border-gray-800 p-2">
      <div><dt className="inline font-medium">Fuente: </dt><dd className="inline">{event.source || NA}</dd></div>
      <div><dt className="inline font-medium">Tipo: </dt><dd className="inline">{etiquetaTipoEvento(event.event_type)}</dd></div>
      {/* Datos decisionales reubicados (SERIE 1, auditoria): nunca crudos, nulos etiquetados "sin datos". */}
      <div><dt className="inline font-medium">Tier de fuente: </dt><dd className="inline">{event.source_tier ? etiquetaTierFuente(event.source_tier) : NA}</dd></div>
      <div><dt className="inline font-medium">Impacto: </dt><dd className="inline">{event.impact_direction ? etiquetaDireccionImpacto(event.impact_direction) : NA}</dd></div>
      <div><dt className="inline font-medium">Peso en cartera: </dt><dd className="inline">{event.portfolio_weight != null ? formatPercent(event.portfolio_weight, { digits: 1 }) : NA}</dd></div>
      {event.news_lane === 'macro' && event.macro_theme ? <div><dt className="inline font-medium">Tema: </dt><dd className="inline">{etiquetaTemaMacro(event.macro_theme)}</dd></div> : null}
    </dl>
  );
}

function ContextAndCoverage({ event }: { event: ResearchNewsEvent }) {
  return (
    <>
      <ContextDetail event={event} />
      <CoverageDetail event={event} />
    </>
  );
}

export function NewsEventsFlow({
  events,
  hasMore,
  lane,
  page,
  ticker,
  portfolioTickers,
  watchlistTickers,
  inFicha = false,
}: {
  events: ResearchNewsEvent[];
  hasMore: boolean;
  lane: NewsLane;
  page: number;
  ticker?: string | null;
  portfolioTickers: string[];
  watchlistTickers: string[];
  /** true dentro de la ficha de empresa: sin filtro de carriles (es una sola
   *  empresa) y la paginación apunta a ?view=noticias, no a /research/news. */
  inFicha?: boolean;
}) {
  const portfolioSet = new Set(portfolioTickers);
  const watchlistSet = new Set(watchlistTickers);
  // Carril macro sin frescura: la API sirve el archivo reciente (fuente
  // caída). Se anuncia con la fecha real del evento más reciente; nunca se
  // finge frescura (medido en prod 30-oct-2026: GDELT >72h sin responder).
  const macroArchive = lane === 'macro' && events.length > 0 && events.every((event) => event.archive);
  const macroArchiveDate = macroArchive && events[0] ? eventDateText(events[0].date) : null;
  return (
    <section className="rounded-lg border border-gray-800 bg-surface-1 p-5">
        <div className="mb-4 flex items-center gap-2">
          <AlertTriangle aria-hidden="true" className="h-5 w-5 text-teal-300" />
          <h2 className="text-lg font-semibold text-gray-100">Flujo de eventos</h2>
        </div>
        <NewsPager label="Paginación" lane={lane} page={page} hasMore={hasMore} ticker={ticker} inFicha={inFicha} />
        {inFicha ? (
          <p className="mb-4 mt-3 text-sm text-gray-500">
            {events.length} {events.length === 1 ? 'evento' : 'eventos'} en la página {page}
          </p>
        ) : (
        <nav aria-label="Filtrar por carril" className="mb-4 mt-3 flex flex-wrap items-center gap-2">
          {CARRILES.map((option) => {
            const active = lane === option.key;
            return (
              <Link
                aria-current={active ? 'page' : undefined}
                className={`inline-flex min-h-11 min-w-11 items-center rounded-full border px-4 py-1.5 text-sm ${
                  active
                    ? 'border-teal-500 bg-teal-950/60 font-semibold text-teal-300'
                    : 'border-gray-700 text-gray-300 hover:border-gray-500 hover:text-gray-100'
                }`}
                href={carrilHref(option.key, ticker)}
                key={option.label}
              >
                {option.label}
              </Link>
            );
          })}
          <span className="text-sm text-gray-500">
            {events.length} {events.length === 1 ? 'evento' : 'eventos'} en la página {page}
          </span>
        </nav>
        )}
        {macroArchive ? (
          <p className="mb-4 rounded-lg border border-amber-900/60 bg-amber-950/40 p-3 text-sm text-amber-200">
            La fuente macro no aporta datos nuevos desde el {macroArchiveDate}; la ingesta sigue
            reintentándose. Mostrando el archivo reciente con su fecha real.
          </p>
        ) : null}
        {/* F176: sin contain, Chrome propaga el overflow horizontal de la
            tabla al documento entero (zoom-out y recorte en movil) aunque la
            region ya scrolla por dentro; layout+paint lo contiene aqui. */}
        {/* Movil: una tarjeta por noticia (titular completo, fecha, fuente). La
            tabla de 5 columnas solo se usa desde md; en pantallas estrechas
            cortaba titulares y partia el layout. */}
        {events.length === 0 ? <div className="rounded-lg border border-gray-800 p-4 md:hidden">
          <EmptyState title={lane === 'macro' ? 'Sin eventos macro disponibles.' : 'Sin eventos de noticias todavía.'} description={lane === 'macro' ? 'La fuente macro no aporta datos nuevos ahora mismo; la ingesta sigue reintentándose.' : 'Este carril todavía no tiene noticias disponibles.'} action={<EmptyLink href="/research/sources">Importa una fuente o analiza una noticia manual</EmptyLink>} />
        </div> : null}
        <ul aria-label="Eventos de noticias" className="flex flex-col gap-3 md:hidden">
          {events.map((event) => (
            <li className="rounded-lg border border-gray-800 bg-black/20 p-3" key={`card-${event.id}`}>
              <div className="flex flex-wrap items-center gap-2 text-xs text-gray-400">
                {event.ticker ? (
                  <Link className="inline-flex min-h-11 min-w-11 items-center font-semibold text-teal-300 hover:text-teal-200" href={`/research/${event.ticker}`}>
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
                <MacroChip event={event} />
                <GobiernoChip event={event} />

                <CoverageChip event={event} />
                <ImpactBadge direction={event.impact_direction} eventType={event.event_type} />
                {event.requires_update ? (
                  <span className="rounded-full bg-amber-950/60 px-2 py-0.5 text-amber-300">Revisar</span>
                ) : null}
                <span className="ml-auto"><MaterialityIndicator score={event.materiality_score} /></span>
              </div>
              <div className="mt-2 text-sm text-gray-200"><NewsHeadline event={event} /></div>
              <NewsSummary event={event} />
              <div className="mt-1 flex flex-wrap items-center gap-x-2 text-xs text-gray-500">
                <span className="min-w-0 break-words">{event.source || NA}</span>
                <span aria-hidden="true">·</span>
                <span>{formatTimeAgo(event.date)}</span>
                <DateNotes event={event} inline />
              </div>
              <NewsSecondOrder eventId={event.id} subjectTicker={event.ticker} summary="Ver contexto">
                <ContextAndCoverage event={event} />
              </NewsSecondOrder>
            </li>
          ))}
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
              {events.map((event) => (
                <tr key={event.id} className="border-b border-gray-900 align-top last:border-0">
                  <th className="py-2.5 text-left text-sm font-semibold" scope="row">
                    {event.ticker ? (
                      <Link
                        className="inline-flex min-h-11 min-w-11 items-center text-teal-300 hover:text-teal-200"
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
                    {event.news_lane === 'macro' || event.news_lane === 'gobierno' ? (
                      <div className="mt-1">
                        <MacroChip event={event} />
                        <GobiernoChip event={event} />

                      </div>
                    ) : null}
                    <div className="mt-1">
                      <CoverageChip event={event} />
                    </div>
                  </th>
                  <td className="min-w-[120px] px-3 py-2.5 text-gray-400">
                    <div>{formatTimeAgo(event.date)}</div>
                    <div className="mt-0.5 text-xs text-gray-500">{eventDateText(event.date)}</div>
                    <DateNotes event={event} />
                  </td>
                  <td className="max-w-[420px] px-3 py-2.5 text-gray-300">
                    <NewsHeadline event={event} />
                    <NewsSummary event={event} />
                    <div className="mt-1 text-xs text-gray-500">{event.source || NA}</div>
                  </td>
                  <td className="px-3 py-2.5 text-center">
                    <MaterialityIndicator score={event.materiality_score} />
                    <div className="mt-1">
                      <ImpactBadge direction={event.impact_direction} eventType={event.event_type} />
                    </div>
                  </td>
                  <td className="py-2.5 text-gray-300">
                    {event.requires_update ? <span className="rounded-full bg-amber-950/60 px-2 py-0.5 text-xs text-amber-300">Revisar</span> : null}
                    <NewsSecondOrder eventId={event.id} subjectTicker={event.ticker} summary="Ver contexto">
                      <ContextAndCoverage event={event} />
                    </NewsSecondOrder>
                  </td>
                </tr>
              ))}
              {!events.length ? (
                <tr>
                  <td className="p-0" colSpan={5}>
                    <EmptyState
                      action={<EmptyLink href="/research/sources">Importa una fuente o analiza una noticia manual</EmptyLink>}
                      className="rounded-none border-0 p-6"
                      description={lane === 'macro' ? 'La fuente macro no aporta datos nuevos ahora mismo; la ingesta sigue reintentándose.' : undefined}
                      title={
                        lane === 'para-ti' && !portfolioTickers.length && !watchlistTickers.length
                          ? 'Sin empresas en tu cartera ni watchlist.'
                          : lane === 'macro'
                            ? 'Sin eventos macro disponibles.'
                            : 'Sin eventos de noticias todavía.'
                      }
                    />
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
        <NewsPager label="Paginación inferior" lane={lane} page={page} hasMore={hasMore} ticker={ticker} inFicha={inFicha} />
      </section>
  );
}
