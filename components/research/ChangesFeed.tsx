'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { Badge } from '@/components/ui/badge';
import { Panel } from '@/components/ui/panel';
import { formatUserDateTime } from '@/lib/format';
import { useLocale, useT } from '@/lib/i18n/client';
import type { TranslationKey } from '@/lib/i18n/t';
import { metricLabel } from '@/lib/research/metric-labels';
import { changeHeadlineCopy, changeSummaryText, changeTypeLabel } from '@/lib/research/change-copy';
import { groupReviews } from '@/lib/research/review-groups';
import { buildChangeEvents, isOpenReview, paginate, type ChangeDirection, type ChangeEvent, type EventAlert, type EventReview } from '@/lib/research/change-events';
import type { ResearchThesisChange } from '@/lib/actions/research.actions';
import { Pager } from './Pager';

export const CHANGES_PAGE_SIZE = 10;
type Filter = 'all' | 'reviews' | 'alerts';

const DIRECTION_KEY: Record<ChangeDirection, TranslationKey> = {
  improves: 'research.changesFeed.directionImproves',
  worsens: 'research.changesFeed.directionWorsens',
  mixed: 'research.changesFeed.directionMixed',
  none: 'research.changesFeed.directionNone',
};
const DIRECTION_CLASS: Record<ChangeDirection, string> = {
  improves: 'bg-emerald-500/10 text-emerald-300',
  worsens: 'bg-red-500/10 text-red-300',
  mixed: 'bg-amber-500/10 text-amber-200',
  none: 'bg-gray-800 text-gray-300',
};


function EventCard({ event, ticker, open, onToggle }: { event: ChangeEvent; ticker: string; open?: boolean; onToggle?: (open: boolean) => void }) {
  const t = useT();
  const locale = useLocale();
  const dateTime = (value: string | null | undefined) => formatUserDateTime(value, undefined, undefined, locale);
  const lead = event.changes[0];
  const openReview = event.reviews.find((r) => isOpenReview(r.status));
  const title = changeHeadlineCopy(lead?.summary ?? openReview?.title ?? event.alerts[0]?.message ?? t('research.changesFeed.noSummary'));
  const records = event.changes.length + event.reviews.length + event.alerts.length;
  const touches = [
    ...event.metrics.map((metric) => metricLabel(metric, locale)),
    ...(event.claimCount ? [t(event.claimCount === 1 ? 'research.changesFeed.claimsOne' : 'research.changesFeed.claimsMany', { count: event.claimCount })] : []),
  ];
  return (
    <li className="scroll-mt-24 rounded-lg border border-gray-800 p-4" data-testid="change-event" id={lead ? `thesis-change-${lead.id}` : undefined}>
      <div className="flex flex-wrap items-center gap-2">
        <span className={`inline-flex rounded-full px-2.5 py-0.5 text-xs font-medium ${DIRECTION_CLASS[event.direction]}`}>{t(DIRECTION_KEY[event.direction])}</span>
        {lead ? <Badge variant="outline">{changeTypeLabel(lead.change_type, locale)}</Badge> : null}
        {event.hasOpenReview || event.requiresReview ? <Badge>{t('research.changesFeed.reviewPending')}</Badge> : <Badge variant="outline">{t('research.changesFeed.noOpenReview')}</Badge>}
        {event.alerts.length ? <Badge variant="outline">{event.alerts.length === 1 ? t('research.changesFeed.alertsOne') : t('research.changesFeed.alertsMany', { count: event.alerts.length })}</Badge> : null}
      </div>
      <p className="mt-3 break-words text-sm text-gray-300">{title.text}</p>
      {title.note ? <p className="mt-2 text-xs text-amber-300">{title.note}</p> : null}
      <p className="mt-2 text-xs text-gray-500">{event.latest ? t('research.changesFeed.dateMadrid', { date: dateTime(event.latest) }) : t('research.changesFeed.unknownDate')}</p>
      {touches.length ? <p className="mt-1 text-xs text-gray-500">{t('research.changesFeed.affectedAssumption', { items: touches.join(' · ') })}</p> : null}
      <div className="mt-3 flex flex-wrap items-center gap-2">
        {openReview ? (
          <button
            className="min-h-11 rounded-lg border border-teal-700 px-3 text-sm text-teal-300 transition hover:border-teal-500 hover:text-teal-200"
            onClick={() => window.dispatchEvent(new CustomEvent('gerarai:open-brain', { detail: { ticker, review_id: openReview.id } }))}
            type="button"
          >
            {t('research.changesFeed.openInBrain')}
          </button>
        ) : null}
        <a className="text-xs text-teal-300 underline decoration-gray-700 underline-offset-4 hover:text-teal-200" href={`/research/${encodeURIComponent(ticker)}?view=thesis`}>{t('research.changesFeed.viewThesis')}</a>
      </div>
      {records > 1 || event.reviews.length || event.alerts.length ? (
        <details className="mt-3 text-sm text-gray-400" onToggle={onToggle ? (e) => onToggle(e.currentTarget.open) : undefined} open={open ?? false}>
          <summary className="min-h-11 cursor-pointer text-xs text-gray-400 sm:min-h-0">{t('research.changesFeed.viewRecords', { count: records })}</summary>
          <div className="mt-2 space-y-2">
            {event.changes.map((c: ResearchThesisChange) => (
              <p className="rounded border border-gray-800 p-2 text-xs" id={`thesis-change-${c.id}`} key={`c${c.id}`}><span className="text-gray-500">{t('research.changesFeed.changeMeta', { date: dateTime(c.created_at), score: c.materiality_score })}</span><br />{changeSummaryText(c.summary)}</p>
            ))}
            {groupReviews(event.reviews.map((r) => ({ id: r.id, title: r.title, created_at: r.created_at }))).map((g) => (
              <p className="rounded border border-gray-800 p-2 text-xs" key={`r${g.ids[0]}`}><span className="text-gray-500">{t('research.changesFeed.review')}{g.count > 1 ? ` ×${g.count}` : ''}{g.latest ? ` · ${dateTime(g.latest)}` : ''}</span><br />{g.title}</p>
            ))}
            {event.alerts.map((a) => (
              <p className="rounded border border-gray-800 p-2 text-xs" key={`a${a.id}`}><span className="text-gray-500">{t('research.changesFeed.alertMeta', { severity: a.severity, date: dateTime(a.created_at) })}</span><br />{a.message}</p>
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
  const t = useT();
  const [filter, setFilter] = useState<Filter>('all');
  const [page, setPage] = useState(1);
  const [openKeys, setOpenKeys] = useState<ReadonlySet<string>>(new Set());
  const events = useMemo(() => buildChangeEvents({ changes, reviews, alerts }), [changes, reviews, alerts]);
  const filtered = useMemo(() => events.filter((e) => filter === 'all' ? true : filter === 'reviews' ? e.hasOpenReview || e.requiresReview : e.alerts.length > 0), [events, filter]);
  const view = paginate(filtered, page, CHANGES_PAGE_SIZE);
  // Anclas «Revisar cambio» de Inicio (?view=changes#thesis-change-<id>):
  // el suceso puede quedar en OTRA página del paginador, y un cambio no
  // líder solo existe como ancla dentro de «Ver los registros originales».
  // Al llegar con ancla: saltar a la página del suceso y desplegar ese
  // detalle; el scroll lo hace ResearchHashScroll. Cada hash se atiende una
  // vez: después la paginación y el plegado vuelven a ser del usuario.
  const handledHashRef = useRef<string | null>(null);
  useEffect(() => {
    const handle = () => {
      const hash = window.location.hash;
      if (!hash.startsWith('#thesis-change-') || handledHashRef.current === hash) return;
      const changeId = Number(hash.slice('#thesis-change-'.length));
      if (!Number.isInteger(changeId)) return;
      const index = filtered.findIndex((event) => event.changes.some((change) => change.id === changeId));
      if (index < 0) return;
      handledHashRef.current = hash;
      const targetPage = Math.floor(index / CHANGES_PAGE_SIZE) + 1;
      setPage((current) => (current === targetPage ? current : targetPage));
      const event = filtered[index];
      if (event.changes[0]?.id !== changeId) {
        setOpenKeys((prev) => (prev.has(event.key) ? prev : new Set(prev).add(event.key)));
      }
    };
    handle();
    window.addEventListener('hashchange', handle);
    return () => window.removeEventListener('hashchange', handle);
  }, [filtered]);
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
    <Panel title={t('research.changesFeed.title')}>
      <div className="mb-3 flex gap-2 overflow-x-auto pb-1" role="group" aria-label={t('research.changesFeed.filterAria')}>
        {chip('all', t('research.changesFeed.filterAll'))}{chip('reviews', t('research.changesFeed.filterReviews'))}{chip('alerts', t('research.changesFeed.filterAlerts'))}
      </div>
      {view.items.length ? (
        <ul className="space-y-3">{view.items.map((event) => (
          <EventCard
            event={event}
            key={event.key}
            onToggle={(isOpen) => setOpenKeys((prev) => {
              const next = new Set(prev);
              if (isOpen) next.add(event.key); else next.delete(event.key);
              return next;
            })}
            open={openKeys.has(event.key)}
            ticker={ticker}
          />
        ))}</ul>
      ) : (
        <p className="text-sm text-gray-500">{events.length ? t('research.changesFeed.emptyFiltered') : t('research.changesFeed.empty')}</p>
      )}
      <Pager label={t('research.changesFeed.pagerUnit')} onPage={setPage} page={view.page} pages={view.pages} total={filtered.length} />
    </Panel>
  );
}
