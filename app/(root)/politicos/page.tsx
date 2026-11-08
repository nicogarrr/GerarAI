import type { Metadata } from 'next';
import Link from 'next/link';

import BackendOffline from '@/components/system/BackendOffline';
import { PoliticianCardView } from '@/components/research/PoliticianCard';
import { getPoliticians, type PoliticiansQuery } from '@/lib/actions/politicians.actions';
import { isBackendUnavailableError } from '@/lib/backend-offline';
import { getLocale, getT } from '@/lib/i18n/server';
import type { TranslationKey } from '@/lib/i18n/t';
import type { PoliticiansList } from '@/lib/research/insiders-politicians';

export const dynamic = 'force-dynamic';
export const revalidate = 0;

const PAGE = 30;
const CHAMBERS = ['all', 'house', 'senate', 'executive'] as const;
const PARTIES = ['all', 'D', 'R', 'I'] as const;
const SORTS = ['trades', 'late', 'recent', 'on_time'] as const;

const CHAMBER_KEYS = {
  all: 'insider.politicians.chambers.all',
  house: 'insider.politicians.chambers.house',
  senate: 'insider.politicians.chambers.senate',
  executive: 'insider.politicians.chambers.executive',
} as const satisfies Record<(typeof CHAMBERS)[number], TranslationKey>;
const PARTY_KEYS = {
  all: 'insider.politicians.parties.all',
  D: 'insider.politicians.parties.D',
  R: 'insider.politicians.parties.R',
  I: 'insider.politicians.parties.I',
} as const satisfies Record<(typeof PARTIES)[number], TranslationKey>;
const SORT_KEYS = {
  trades: 'insider.politicians.sorts.trades',
  late: 'insider.politicians.sorts.late',
  recent: 'insider.politicians.sorts.recent',
  on_time: 'insider.politicians.sorts.onTime',
} as const satisfies Record<(typeof SORTS)[number], TranslationKey>;

export async function generateMetadata(): Promise<Metadata> {
  const t = await getT();
  return { title: t('insider.politicians.metaTitle'), description: t('insider.politicians.metaDescription') };
}

type SearchParams = { camara?: string; partido?: string; orden?: string; q?: string; n?: string };

function pick<T extends readonly string[]>(options: T, value: string | undefined, fallback: T[number]): T[number] {
  return (options as readonly string[]).includes(value ?? '') ? (value as T[number]) : fallback;
}

function href(current: Required<Pick<SearchParams, 'camara' | 'partido' | 'orden'>> & { q?: string }, patch: Partial<SearchParams>): string {
  const params = new URLSearchParams();
  const next = { ...current, ...patch };
  if (next.camara && next.camara !== 'all') params.set('camara', next.camara);
  if (next.partido && next.partido !== 'all') params.set('partido', next.partido);
  if (next.orden && next.orden !== 'trades') params.set('orden', next.orden);
  if (next.q) params.set('q', next.q);
  if (patch.n) params.set('n', patch.n);
  const qs = params.toString();
  return qs ? `/politicos?${qs}` : '/politicos';
}

function Pill({ active, to, children }: { active: boolean; to: string; children: React.ReactNode }) {
  return (
    <Link
      aria-current={active ? 'true' : undefined}
      className={`inline-flex min-h-11 shrink-0 items-center rounded-full border px-3 text-sm md:min-h-0 md:py-1 ${active ? 'border-teal-700 bg-teal-400/10 text-teal-300' : 'border-gray-800 text-gray-400 hover:text-gray-100'}`}
      href={to}
    >
      {children}
    </Link>
  );
}

export default async function PoliticiansPage({ searchParams }: { searchParams: Promise<SearchParams> }) {
  const t = await getT();
  const locale = await getLocale();
  const sp = await searchParams;
  const camara = pick(CHAMBERS, sp.camara, 'all');
  const partido = pick(PARTIES, sp.partido, 'all');
  const orden = pick(SORTS, sp.orden, 'trades');
  const q = (sp.q ?? '').trim().slice(0, 80);
  const shown = Math.min(Math.max(Number(sp.n) || PAGE, PAGE), 300);
  const current = { camara, partido, orden, q };
  let data: PoliticiansList | null = null;
  const unavailable = camara === 'senate' || camara === 'executive';
  if (!unavailable) {
    try {
      const query: PoliticiansQuery = { chamber: camara, party: partido === 'all' ? null : partido, sort: orden, q: q || null, limit: shown };
      data = await getPoliticians(query);
    } catch (error) {
      if (isBackendUnavailableError(error)) return <BackendOffline feature={t('insider.politicians.title')} retryHref="/politicos" />;
      throw error;
    }
  }
  return (
    <main className="mx-auto flex w-full min-w-0 max-w-6xl flex-col gap-5 overflow-x-clip" id="content" tabIndex={-1}>
      <header className="border-b border-gray-800 pb-4">
        <h1 className="text-xl font-bold text-gray-100 sm:text-2xl">{t('insider.politicians.title')}</h1>
        <p className="mt-1 text-sm text-gray-400">{t('insider.politicians.intro')}</p>
      </header>
      <section aria-label={t('insider.politicians.search')} className="flex flex-col gap-3">
        <div aria-label={t('insider.politicians.chamber')} className="flex flex-nowrap gap-2 overflow-x-auto" role="group">
          {CHAMBERS.map((c) => <Pill active={camara === c} key={c} to={href(current, { camara: c })}>{t(CHAMBER_KEYS[c])}</Pill>)}
        </div>
        <div aria-label={t('insider.politicians.party')} className="flex flex-nowrap gap-2 overflow-x-auto" role="group">
          {PARTIES.map((p) => <Pill active={partido === p} key={p} to={href(current, { partido: p })}>{t(PARTY_KEYS[p])}</Pill>)}
        </div>
        <div aria-label={t('insider.politicians.sort')} className="flex flex-nowrap gap-2 overflow-x-auto" role="group">
          {SORTS.map((s) => <Pill active={orden === s} key={s} to={href(current, { orden: s })}>{t(SORT_KEYS[s])}</Pill>)}
        </div>
        <form action="/politicos" className="flex gap-2" method="get">
          {camara !== 'all' ? <input name="camara" type="hidden" value={camara} /> : null}
          {partido !== 'all' ? <input name="partido" type="hidden" value={partido} /> : null}
          {orden !== 'trades' ? <input name="orden" type="hidden" value={orden} /> : null}
          <input aria-label={t('insider.politicians.search')} className="min-h-11 w-full min-w-0 rounded-lg border border-gray-800 bg-surface-1 px-3 text-base text-gray-100 md:text-sm" defaultValue={q} name="q" placeholder={t('insider.politicians.search')} />
          <button className="min-h-11 shrink-0 rounded-lg border border-gray-700 px-3 text-sm text-gray-200" type="submit">{t('insider.politicians.searchButton')}</button>
        </form>
      </section>
      {unavailable ? (
        <p className="rounded-lg border border-amber-900/70 bg-amber-950/20 p-3 text-sm text-amber-200" role="status">
          {t('insider.politicians.unavailable', {
            chamber: t(CHAMBER_KEYS[camara]),
            reason: t(camara === 'senate' ? 'insider.politicians.senateReason' : 'insider.politicians.executiveReason'),
          })}
        </p>
      ) : data && data.politicians.length ? (
        <>
          <p className="text-xs text-gray-500">
            {t('insider.politicians.count', { total: data.total })} · {t('insider.politicians.coverage', { filings: data.coverage.filings, years: data.coverage.years.join(', '), scanned: data.coverage.scanned_filings })}
          </p>
          <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {data.politicians.map((card) => <PoliticianCardView card={card} key={card.member_key} locale={locale} />)}
          </ul>
          {data.total > data.politicians.length ? (
            <Link className="self-center rounded-lg border border-gray-700 px-4 py-2 text-sm text-gray-200" href={href(current, { n: String(shown + PAGE) })}>{t('insider.politicians.more')}</Link>
          ) : null}
        </>
      ) : (
        <p className="text-sm text-gray-400" role="status">{t('insider.politicians.empty')}</p>
      )}
      <p className="text-xs text-gray-500">{t('insider.politicians.legal')}</p>
    </main>
  );
}
