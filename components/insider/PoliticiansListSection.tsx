import Link from 'next/link';

import { PoliticianCardView } from '@/components/research/PoliticianCard';
import { getPoliticians, type PoliticiansQuery } from '@/lib/actions/politicians.actions';
import { DEFAULT_LOCALE, type Locale } from '@/lib/i18n/locale';
import { createTranslator } from '@/lib/i18n/translate';
import { isAuthError } from '@/lib/types/errors';
import type { TranslationKey } from '@/lib/i18n/t';
import type { PoliticiansList } from '@/lib/research/insiders-politicians';

// Lista de políticos (PTR de la Cámara) como SECCIÓN de /insider (#politicos):
// Nico, 8-nov-2026 16:22 «No hagas más pestañas, solo mete lo que aporte valor
// en cosas ya existentes». La antigua página /politicos redirige aquí con sus
// mismos filtros (camara, partido, orden, q, n).
export const POLITICIANS_ANCHOR = 'politicos';

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

export type PoliticiansSearchParams = { camara?: string; partido?: string; orden?: string; q?: string; n?: string };

function pick<T extends readonly string[]>(options: T, value: string | undefined, fallback: T[number]): T[number] {
  return (options as readonly string[]).includes(value ?? '') ? (value as T[number]) : fallback;
}

/** Enlace a la sección de /insider con los filtros de la lista. */
export function politiciansHref(current: Required<Pick<PoliticiansSearchParams, 'camara' | 'partido' | 'orden'>> & { q?: string }, patch: Partial<PoliticiansSearchParams>): string {
  const params = new URLSearchParams();
  const next = { ...current, ...patch };
  if (next.camara && next.camara !== 'all') params.set('camara', next.camara);
  if (next.partido && next.partido !== 'all') params.set('partido', next.partido);
  if (next.orden && next.orden !== 'trades') params.set('orden', next.orden);
  if (next.q) params.set('q', next.q);
  if (patch.n) params.set('n', patch.n);
  const qs = params.toString();
  return qs ? `/insider?${qs}#${POLITICIANS_ANCHOR}` : `/insider#${POLITICIANS_ANCHOR}`;
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

export type PoliticiansSectionView = {
  camara: (typeof CHAMBERS)[number];
  partido: (typeof PARTIES)[number];
  orden: (typeof SORTS)[number];
  q: string;
  shown: number;
  data: PoliticiansList | null;
  offline: boolean;
};

/** Lee la lista con los filtros de la URL. Estado honesto por sección: que
 *  falle la lista no tumba /insider (solo se propaga una sesión caducada). */
export async function loadPoliticiansSection(sp: PoliticiansSearchParams): Promise<PoliticiansSectionView> {
  const camara = pick(CHAMBERS, sp.camara, 'all');
  const partido = pick(PARTIES, sp.partido, 'all');
  const orden = pick(SORTS, sp.orden, 'trades');
  const q = (sp.q ?? '').trim().slice(0, 80);
  const shown = Math.min(Math.max(Number(sp.n) || PAGE, PAGE), 300);
  const view: PoliticiansSectionView = { camara, partido, orden, q, shown, data: null, offline: false };
  if (camara === 'senate' || camara === 'executive') return view;
  try {
    const query: PoliticiansQuery = { chamber: camara, party: partido === 'all' ? null : partido, sort: orden, q: q || null, limit: shown };
    view.data = await getPoliticians(query);
  } catch (error) {
    if (isAuthError(error)) throw error;
    view.offline = true;
  }
  return view;
}

/** Sección «Políticos» de /insider: filtros por cámara, partido y orden, búsqueda y tarjetas. */
export function PoliticiansListSection({ view, locale = DEFAULT_LOCALE }: { view: PoliticiansSectionView; locale?: Locale }) {
  const t = createTranslator(locale);
  const { camara, partido, orden, q, shown, data, offline } = view;
  const current = { camara, partido, orden, q };
  const unavailable = camara === 'senate' || camara === 'executive';
  return (
    <section aria-labelledby="politicos-title" className="flex scroll-mt-24 flex-col gap-4 border-t border-gray-800 pt-5" id={POLITICIANS_ANCHOR}>
      <header>
        <h2 className="text-lg font-semibold text-gray-100" id="politicos-title">{t('insider.politicians.title')}</h2>
        <p className="mt-1 text-sm text-gray-400">{t('insider.politicians.intro')}</p>
      </header>
      <div aria-label={t('insider.politicians.search')} className="flex flex-col gap-3">
        <div aria-label={t('insider.politicians.chamber')} className="flex flex-nowrap gap-2 overflow-x-auto" role="group">
          {CHAMBERS.map((c) => <Pill active={camara === c} key={c} to={politiciansHref(current, { camara: c })}>{t(CHAMBER_KEYS[c])}</Pill>)}
        </div>
        <div aria-label={t('insider.politicians.party')} className="flex flex-nowrap gap-2 overflow-x-auto" role="group">
          {PARTIES.map((p) => <Pill active={partido === p} key={p} to={politiciansHref(current, { partido: p })}>{t(PARTY_KEYS[p])}</Pill>)}
        </div>
        <div aria-label={t('insider.politicians.sort')} className="flex flex-nowrap gap-2 overflow-x-auto" role="group">
          {SORTS.map((s) => <Pill active={orden === s} key={s} to={politiciansHref(current, { orden: s })}>{t(SORT_KEYS[s])}</Pill>)}
        </div>
        <form action={`/insider#${POLITICIANS_ANCHOR}`} className="flex gap-2" method="get">
          {camara !== 'all' ? <input name="camara" type="hidden" value={camara} /> : null}
          {partido !== 'all' ? <input name="partido" type="hidden" value={partido} /> : null}
          {orden !== 'trades' ? <input name="orden" type="hidden" value={orden} /> : null}
          <input aria-label={t('insider.politicians.search')} className="min-h-11 w-full min-w-0 rounded-lg border border-gray-800 bg-surface-1 px-3 text-base text-gray-100 md:text-sm" defaultValue={q} name="q" placeholder={t('insider.politicians.search')} />
          <button className="min-h-11 shrink-0 rounded-lg border border-gray-700 px-3 text-sm text-gray-200" type="submit">{t('insider.politicians.searchButton')}</button>
        </form>
      </div>
      {unavailable ? (
        <p className="rounded-lg border border-amber-900/70 bg-amber-950/20 p-3 text-sm text-amber-200" role="status">
          {t('insider.politicians.unavailable', {
            chamber: t(CHAMBER_KEYS[camara]),
            reason: t(camara === 'senate' ? 'insider.politicians.senateReason' : 'insider.politicians.executiveReason'),
          })}
        </p>
      ) : offline ? (
        <p className="rounded-lg border border-amber-900/70 bg-amber-950/20 p-3 text-sm text-amber-200" role="status">{t('insider.politicians.offline')}</p>
      ) : data && data.politicians.length ? (
        <>
          <p className="text-xs text-gray-500">
            {t('insider.politicians.count', { total: data.total })} · {t('insider.politicians.coverage', { filings: data.coverage.filings, years: data.coverage.years.join(', '), scanned: data.coverage.scanned_filings })}
          </p>
          <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {data.politicians.map((card) => <PoliticianCardView card={card} key={card.member_key} locale={locale} />)}
          </ul>
          {data.total > data.politicians.length ? (
            <Link className="self-center rounded-lg border border-gray-700 px-4 py-2 text-sm text-gray-200" href={politiciansHref(current, { n: String(shown + PAGE) })}>{t('insider.politicians.more')}</Link>
          ) : null}
        </>
      ) : (
        <p className="text-sm text-gray-400" role="status">{t('insider.politicians.empty')}</p>
      )}
      <p className="text-xs text-gray-500">{t('insider.politicians.legal')}</p>
    </section>
  );
}
