import type { Metadata } from 'next';
import Link from 'next/link';
import { ExternalLink } from 'lucide-react';

import BackendOffline from '@/components/system/BackendOffline';
import { MutationForm } from '@/components/forms/MutationForm';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import {
  getBottleneckDiscoveries,
  getBottlenecks,
  runBottleneckDiscovery,
  type DiscoveryView,
} from '@/lib/actions/bottlenecks.actions';
import { isBackendUnavailableError } from '@/lib/backend-offline';
import { BOTTLENECK_TO_THEMES, basketName, bottleneckThemeName } from '@/lib/market/theme-bottleneck-map';
import { NA, type Formatters } from '@/lib/format';
import { getFormat, getT } from '@/lib/i18n/server';
import type { TranslateFn } from '@/lib/i18n/translate';

export async function generateMetadata(): Promise<Metadata> {
  const t = await getT();
  return { title: t('bottlenecks.page.metaTitle'), description: t('bottlenecks.page.metaDescription') };
}

export const dynamic = 'force-dynamic';
export const revalidate = 0;

const PAGE_SIZE = 20;

type PageProps = { searchParams: Promise<{ pagina?: string | string[] }> };

function parsePage(raw: string | string[] | undefined): number {
  const value = Array.isArray(raw) ? raw[0] : raw;
  const page = Number(value);
  return Number.isInteger(page) && page >= 1 ? page : 1;
}

function SignalCard({ signal, minSources, t, fmt }: { signal: Awaited<ReturnType<typeof getBottlenecks>>['signals'][number]; minSources: number; t: TranslateFn; fmt: Formatters }) {
  const detected = signal.status === 'detectado';
  return (
    <li className="rounded-xl border border-gray-800 bg-gray-900/40 p-4">
      <div className="flex items-start justify-between gap-2">
        <h2 className="text-sm font-semibold text-gray-100">{bottleneckThemeName(signal.theme, t)}</h2>
        {detected ? (
          <span className="rounded bg-teal-400/15 px-1.5 py-0.5 text-[10px] font-bold uppercase text-teal-300">
            {t('bottlenecks.page.detected')}
          </span>
        ) : (
          <span className="rounded bg-gray-800 px-1.5 py-0.5 text-[10px] font-bold uppercase text-gray-500">
            {fmt.na}
          </span>
        )}
      </div>
      <p className="mt-3 text-xs text-gray-400">
        {detected
          ? t('bottlenecks.page.sourcesDetected', { n: signal.n_sources, date: fmt.formatUserDate(signal.last_seen) })
          : /* Puede haber evidencias enlazables y aun asi N/D: el umbral cuenta
               FUENTES independientes, no evidencias (Tester 6: 2 evidencias de
               un mismo editor no detectan). El contador lo hace visible. */
            t('bottlenecks.page.sourcesShort', { n: signal.n_sources, min: minSources })}
      </p>
      {signal.evidence?.length ? (
        <details className="mt-3 text-xs">
          <summary className="min-h-11 cursor-pointer py-3 text-teal-300">{t('bottlenecks.page.showEvidence', { n: signal.evidence.length })}</summary>
          <ul className="mt-2 space-y-2">
            {signal.evidence.map((item) => (
              <li key={item.id}>
                {item.status === 'verificada' && item.url ? (
                  <a className="inline-flex min-h-11 min-w-0 items-center break-all text-teal-300 underline" href={item.url} rel="noopener noreferrer" target="_blank">
                    {item.title ?? item.url}
                  </a>
                ) : <span className="text-gray-500">{item.title ?? t('bottlenecks.page.evidenceUnavailable')} · {t('bottlenecks.page.noVerifiableLink')}</span>}
              </li>
            ))}
          </ul>
        </details>
      ) : detected ? <p className="mt-2 text-xs text-gray-500">{t('bottlenecks.page.evidenceNotQueryable')}</p> : null}
      {BOTTLENECK_TO_THEMES[signal.theme]?.length ? (
        <p className="mt-3 border-t border-gray-800 pt-2 text-xs text-gray-400">
          {t('bottlenecks.page.relatedThemes')}{' '}
          <Link className="inline-flex min-h-11 min-w-11 items-center text-teal-300 underline hover:text-teal-200" href="/temas">
            {BOTTLENECK_TO_THEMES[signal.theme].map((theme) => basketName(theme.id, theme.name, t)).join(' · ')}
          </Link>
        </p>
      ) : null}
    </li>
  );
}

function DiscoveryCard({ item, t, fmt }: { item: DiscoveryView; t: TranslateFn; fmt: Formatters }) {
  const known = item.ticker !== NA;
  return (
    <li className="rounded-xl border border-gray-800 bg-gray-900/40 p-4">
      <div className="flex flex-wrap items-center gap-2">
        {known ? (
          <Link
            className="inline-flex min-h-11 min-w-11 items-center text-base font-semibold text-teal-300 hover:text-teal-200"
            href={`/research/${item.ticker}`}
          >
            {item.ticker}
          </Link>
        ) : (
          <span className="text-base font-semibold text-gray-300">{t('bottlenecks.page.unidentified')}</span>
        )}
        <span className="text-xs text-gray-500">{item.theme}</span>
        <Badge className="border-amber-500/50 text-amber-300" variant="outline">
          {item.label}
        </Badge>
        {!item.theme_detected ? (
          <Badge className="border-gray-600 text-gray-400" variant="outline">
            {t('bottlenecks.page.themeNoLongerDetected')}
          </Badge>
        ) : null}
        {item.in_portfolio ? (
          <Badge className="border-teal-500/50 text-teal-300" variant="outline">
            {t('bottlenecks.page.inPortfolio')}
          </Badge>
        ) : null}
        {item.in_watchlist ? (
          <Badge className="border-sky-500/50 text-sky-300" variant="outline">
            {t('bottlenecks.page.inWatchlist')}
          </Badge>
        ) : null}
        {item.recent_insider_activity ? (
          <Badge className="border-violet-500/50 text-violet-300" variant="outline">
            {t('bottlenecks.page.insiderActivity')}
          </Badge>
        ) : null}
      </div>
      <p className="mt-2 text-sm leading-relaxed text-gray-300">{item.reasoning}</p>
      {item.evidence.length > 0 ? (
        <ul className="mt-3 space-y-1 border-t border-gray-800 pt-2">
          {item.evidence.map((evidence) => (
            <li className="flex items-center gap-1.5 text-xs" key={evidence.id}>
              {evidence.status === 'verificada' && evidence.url ? (
                <a
                  className="inline-flex min-h-11 min-w-0 items-center gap-1 break-all text-teal-300 underline hover:text-teal-200"
                  href={evidence.url}
                  rel="noopener noreferrer"
                  target="_blank"
                >
                  {evidence.title ?? evidence.url}
                  <ExternalLink aria-hidden="true" className="h-3 w-3" />
                </a>
              ) : (
                <span className="text-gray-500">
                  {evidence.title ?? t('bottlenecks.page.evidence')} · {fmt.na}
                </span>
              )}
            </li>
          ))}
        </ul>
      ) : null}
      <p className="mt-3 text-[11px] text-gray-500">
        {t('bottlenecks.page.discoveryMeta', { date: fmt.formatUserDate(item.created_at), model: item.model })}{' '}
        {item.theme_last_seen ? fmt.formatUserDate(item.theme_last_seen) : fmt.na}
      </p>
    </li>
  );
}

export default async function CuellosPage({ searchParams }: PageProps) {
  const page = parsePage((await searchParams).pagina);
  const [t, fmt] = await Promise.all([getT(), getFormat()]);
  let bottlenecks: Awaited<ReturnType<typeof getBottlenecks>>;
  let discoveries: Awaited<ReturnType<typeof getBottleneckDiscoveries>>;
  try {
    [bottlenecks, discoveries] = await Promise.all([
      getBottlenecks(),
      getBottleneckDiscoveries((page - 1) * PAGE_SIZE, PAGE_SIZE),
    ]);
  } catch (error) {
    if (isBackendUnavailableError(error)) {
      return <BackendOffline feature={t('bottlenecks.page.title')} retryHref="/cuellos" />;
    }
    throw error;
  }

  const detectedCount = bottlenecks.signals.filter((signal) => signal.status === 'detectado').length;
  const totalPages = Math.max(1, Math.ceil(discoveries.total / PAGE_SIZE));
  const pageHref = (target: number) => (target <= 1 ? '/cuellos' : `/cuellos?pagina=${target}`);

  return (
    <main id="content" tabIndex={-1} className="mx-auto flex max-w-6xl flex-col gap-6">
      <header>
        <h1 className="text-3xl font-bold text-gray-100">{t('bottlenecks.page.title')}</h1>
        <p className="mt-1 text-sm text-gray-400">
          {t('bottlenecks.page.summary', { detected: detectedCount, total: bottlenecks.signals.length })}
        </p>
      </header>

      <section aria-label={t('bottlenecks.page.signalsAria')}>
        <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {bottlenecks.signals.map((signal) => (
            <SignalCard key={signal.theme} signal={signal} minSources={bottlenecks.min_sources} t={t} fmt={fmt} />
          ))}
        </ul>
      </section>

      <section aria-label={t('bottlenecks.page.candidates')}>
        <h2 className="mb-3 text-xl font-semibold text-gray-100">{t('bottlenecks.page.candidates')}</h2>
        <MutationForm action={runBottleneckDiscovery} showSuccessInline className="mb-3">
          <Button type="submit" variant="outline">{t('bottlenecks.page.searchCandidates')}</Button>
          <p className="mt-2 text-sm text-gray-400">{t('bottlenecks.page.candidatesHint')}</p>
        </MutationForm>
        {discoveries.items.length === 0 && discoveries.total === 0 ? (
          <div className="rounded-xl border border-gray-800 bg-surface-1 p-5">
            <p className="font-semibold text-gray-100">{t('bottlenecks.page.noCandidates')}</p>
            <p className="mt-1 text-sm text-gray-400">
              {t('bottlenecks.page.noCandidatesHint')}
            </p>
          </div>
        ) : discoveries.items.length === 0 ? (
          <div className="rounded-xl border border-gray-800 bg-surface-1 p-5">
            <p className="font-semibold text-gray-100">{t('bottlenecks.page.outOfRange')}</p>
            <p className="mt-1 text-sm text-gray-400">
              {t('bottlenecks.page.outOfRangeHint', {
                total: discoveries.total,
                pages: totalPages,
                pagesWord: totalPages === 1 ? t('bottlenecks.page.pageOne') : t('bottlenecks.page.pageMany'),
              })}
            </p>
            <nav aria-label={t('bottlenecks.page.backAria')} className="mt-3 flex flex-wrap gap-2 text-sm">
              <Link
                className="inline-flex min-h-11 items-center rounded-lg px-4 font-medium text-teal-300 hover:bg-gray-800"
                href="/cuellos"
              >
                {t('bottlenecks.page.firstPage')}
              </Link>
              {totalPages > 1 ? (
                <Link
                  className="inline-flex min-h-11 items-center rounded-lg px-4 font-medium text-teal-300 hover:bg-gray-800"
                  href={pageHref(totalPages)}
                >
                  {t('bottlenecks.page.lastPage')}
                </Link>
              ) : null}
            </nav>
          </div>
        ) : (
          <>
            <ul className="grid gap-3 sm:grid-cols-2">
              {discoveries.items.map((item) => (
                <DiscoveryCard item={item} key={item.id} t={t} fmt={fmt} />
              ))}
            </ul>
            <nav aria-label={t('bottlenecks.page.pagerAria')} className="mt-4 flex items-center gap-2 text-sm">
              {page > 1 ? (
                <Link
                  className="inline-flex min-h-11 items-center rounded-lg px-4 font-medium text-gray-400 hover:bg-gray-800 hover:text-gray-100"
                  href={pageHref(page - 1)}
                >
                  {t('bottlenecks.page.prev')}
                </Link>
              ) : null}
              <span className="px-2 text-gray-500">{t('bottlenecks.page.page', { page })}</span>
              {discoveries.has_more ? (
                <Link
                  className="inline-flex min-h-11 items-center rounded-lg px-4 font-medium text-gray-400 hover:bg-gray-800 hover:text-gray-100"
                  href={pageHref(page + 1)}
                >
                  {t('bottlenecks.page.next')}
                </Link>
              ) : null}
            </nav>
          </>
        )}
      </section>

      <footer className="border-t border-gray-800 pt-3 text-xs text-gray-500">
        <p>{bottlenecks.method} · {bottlenecks.limitation}</p>
        <p className="mt-1">{discoveries.note}</p>
      </footer>
    </main>
  );
}
