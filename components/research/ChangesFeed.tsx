'use client';

import { useMemo, useState } from 'react';
import { Badge } from '@/components/ui/badge';
import { Panel } from '@/components/ui/panel';
import { formatUserDateTime } from '@/lib/format';
import { metricLabel } from '@/lib/research/metric-labels';
import { changeSummaryText, changeTypeLabel } from '@/lib/research/change-copy';
import { groupReviews } from '@/lib/research/review-groups';
import { safeAssistantSourceUrl } from '@/lib/research/assistant-contract';
import { buildChangeEvents, isOpenReview, paginate, type ChangeDirection, type ChangeEvent, type EventAlert, type EventReview } from '@/lib/research/change-events';
import type { ResearchThesisChange } from '@/lib/actions/research.actions';
import { Pager } from './Pager';

export const CHANGES_PAGE_SIZE = 10;
type Filter = 'all' | 'reviews' | 'alerts';

const DIRECTION_LABEL: Record<ChangeDirection, string> = {
  improves: 'Mejora',
  worsens: 'Empeora',
  mixed: 'Mixto',
  none: 'Sin conclusión',
};
const DIRECTION_CLASS: Record<ChangeDirection, string> = {
  improves: 'bg-emerald-500/10 text-emerald-300',
  worsens: 'bg-red-500/10 text-red-300',
  mixed: 'bg-amber-500/10 text-amber-200',
  none: 'bg-gray-800 text-gray-300',
};

function hostOf(url: string): string {
  try { return new URL(url).hostname.replace(/^www\./, ''); } catch { return url; }
}

function EventCard({ event, ticker }: { event: ChangeEvent; ticker: string }) {
  const lead = event.changes[0];
  const openReview = event.reviews.find((r) => isOpenReview(r.status));
  const title = lead ? changeSummaryText(lead.summary) : (openReview?.title ?? event.alerts[0]?.message ?? 'Registro sin resumen');
  const sources = event.sourceUrls.map((u) => ({ url: safeAssistantSourceUrl(u), host: hostOf(u) })).filter((s): s is { url: string; host: string } => !!s.url);
  const records = event.changes.length + event.reviews.length + event.alerts.length;
  const touches = [
    ...event.metrics.map((metric) => metricLabel(metric)),
    ...(event.claimCount ? [`${event.claimCount} ${event.claimCount === 1 ? 'afirmación' : 'afirmaciones'} de la tesis`] : []),
  ];
  return (
    <li className="rounded-lg border border-gray-800 p-4" data-testid="change-event">
      <div className="flex flex-wrap items-center gap-2">
        <span className={`inline-flex rounded-full px-2.5 py-0.5 text-xs font-medium ${DIRECTION_CLASS[event.direction]}`}>{DIRECTION_LABEL[event.direction]}</span>
        {lead ? <Badge variant="outline">{changeTypeLabel(lead.change_type)}</Badge> : null}
        {event.hasOpenReview || event.requiresReview ? <Badge>revisión pendiente</Badge> : <Badge variant="outline">sin revisión abierta</Badge>}
        {event.alerts.length ? <Badge variant="outline">{event.alerts.length === 1 ? '1 alerta' : `${event.alerts.length} alertas`}</Badge> : null}
      </div>
      <p className="mt-3 break-words text-sm text-gray-300">{title}</p>
      <p className="mt-2 text-xs text-gray-500">{event.latest ? `${formatUserDateTime(event.latest)} (Madrid)` : 'Fecha desconocida'}</p>
      {touches.length ? <p className="mt-1 text-xs text-gray-500">Supuesto afectado: {touches.join(' · ')}</p> : null}
      {sources.length ? (
        <p className="mt-1 break-words text-xs text-gray-500">
          Fuentes:{' '}
          {sources.map((s, i) => (
            <span key={s.url}>{i ? ' · ' : ''}<a className="text-teal-300 underline decoration-gray-700 underline-offset-4 hover:text-teal-200" href={s.url} rel="noopener noreferrer" target="_blank">{s.host}</a></span>
          ))}
        </p>
      ) : null}
      <div className="mt-3 flex flex-wrap items-center gap-2">
        {openReview ? (
          <button
            className="min-h-11 rounded-lg border border-teal-700 px-3 text-sm text-teal-300 transition hover:border-teal-500 hover:text-teal-200"
            onClick={() => window.dispatchEvent(new CustomEvent('gerarai:open-brain', { detail: { ticker, review_id: openReview.id } }))}
            type="button"
          >
            Abrir en el Cerebro
          </button>
        ) : null}
        <a className="text-xs text-teal-300 underline decoration-gray-700 underline-offset-4 hover:text-teal-200" href={`/research/${encodeURIComponent(ticker)}?view=thesis`}>Ver la tesis</a>
      </div>
      {records > 1 || event.reviews.length || event.alerts.length ? (
        <details className="mt-3 text-sm text-gray-400">
          <summary className="min-h-11 cursor-pointer text-xs text-gray-400 sm:min-h-0">Ver los {records} registros originales</summary>
          <div className="mt-2 space-y-2">
            {event.changes.map((c: ResearchThesisChange) => (
              <p className="rounded border border-gray-800 p-2 text-xs" key={`c${c.id}`}><span className="text-gray-500">Cambio · {formatUserDateTime(c.created_at)} · materialidad {c.materiality_score}</span><br />{changeSummaryText(c.summary)}</p>
            ))}
            {groupReviews(event.reviews.map((r) => ({ id: r.id, title: r.title, created_at: r.created_at }))).map((g) => (
              <p className="rounded border border-gray-800 p-2 text-xs" key={`r${g.ids[0]}`}><span className="text-gray-500">Revisión{g.count > 1 ? ` ×${g.count}` : ''}{g.latest ? ` · ${formatUserDateTime(g.latest)}` : ''}</span><br />{g.title}</p>
            ))}
            {event.alerts.map((a) => (
              <p className="rounded border border-gray-800 p-2 text-xs" key={`a${a.id}`}><span className="text-gray-500">Alerta ({a.severity}) · {formatUserDateTime(a.created_at)}</span><br />{a.message}</p>
            ))}
          </div>
        </details>
      ) : null}
    </li>
  );
}

/**
 * Seguir: UNA tarjeta por suceso (cambio + revisiones + alertas vinculados),
 * 10 por página. «Revisiones abiertas» y «Alertas» son filtros de la misma
 * lista, no listas aparte. Nada se borra: los registros originales de cada
 * suceso siguen visibles dentro de «Ver los registros originales».
 */
export function ChangesFeed({ ticker, changes, reviews, alerts }: {
  ticker: string;
  changes: ResearchThesisChange[];
  reviews: EventReview[];
  alerts: EventAlert[];
}) {
  const [filter, setFilter] = useState<Filter>('all');
  const [page, setPage] = useState(1);
  const events = useMemo(() => buildChangeEvents({ changes, reviews, alerts }), [changes, reviews, alerts]);
  const filtered = useMemo(() => events.filter((e) => filter === 'all' ? true : filter === 'reviews' ? e.hasOpenReview || e.requiresReview : e.alerts.length > 0), [events, filter]);
  const view = paginate(filtered, page, CHANGES_PAGE_SIZE);
  const counts = { all: events.length, reviews: events.filter((e) => e.hasOpenReview || e.requiresReview).length, alerts: events.filter((e) => e.alerts.length > 0).length };
  const chip = (id: Filter, text: string) => (
    <button
      aria-pressed={filter === id}
      className={`min-h-11 shrink-0 rounded-full border px-3 text-sm transition sm:min-h-9 ${filter === id ? 'border-teal-500 bg-teal-500/10 text-teal-200' : 'border-gray-700 text-gray-300 hover:border-gray-500'}`}
      key={id}
      onClick={() => { setFilter(id); setPage(1); }}
      type="button"
    >{text} ({counts[id]})</button>
  );
  return (
    <Panel title="Qué ha cambiado">
      <div className="mb-3 flex gap-2 overflow-x-auto pb-1" role="group" aria-label="Filtrar sucesos">
        {chip('all', 'Todos')}{chip('reviews', 'Revisiones abiertas')}{chip('alerts', 'Alertas')}
      </div>
      {view.items.length ? (
        <ul className="space-y-3">{view.items.map((event) => <EventCard event={event} key={event.key} ticker={ticker} />)}</ul>
      ) : (
        <p className="text-sm text-gray-500">{events.length ? 'Ningún suceso coincide con este filtro.' : 'Sin cambios materiales registrados.'}</p>
      )}
      <Pager label="sucesos" onPage={setPage} page={view.page} pages={view.pages} total={filtered.length} />
    </Panel>
  );
}
