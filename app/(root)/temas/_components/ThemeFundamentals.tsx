import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { formatMoney, formatNumber, naFor } from '@/lib/format';
import type { Locale } from '@/lib/i18n/locale';
import { getLocale, getT } from '@/lib/i18n/server';

type SourceRow = { label: string; values: (number | string | null)[] };
type Series = { title: string; columns: string[]; unit: string; rows: SourceRow[]; source: string; sourceName: string; vintage: string; published: string; kind: string; monthly?: boolean; attribution?: string; terms?: string; unavailableReason?: string };
type Metric = { label: string; value: number | null; unit: string; period: string; source: string; vintage: string };
type Snapshot = { title: string; checkedAt: string; metrics: Metric[]; series: Series[]; notes: string[]; links: { label: string; url: string }[] };

function value(n: number | string | null, unit: string, locale: Locale) {
  if (typeof n === 'string') return n;
  if (n === null || !Number.isFinite(n)) return naFor(locale);
  return unit.startsWith('USD/')
    ? formatMoney(n, unit.split('/')[0], {}, undefined, locale)
    : formatNumber(n, { maximumFractionDigits: 3 }, undefined, locale);
}

/** Reviewed public-source snapshots. No request-time remote calls or silent refresh.
 * A new theme adds a source-reviewed JSON file; no separate page or menu item.
 */
export async function ThemeFundamentals({ themeId }: { themeId: string }) {
  if (!['nuclear', 'materiales', 'utilities'].includes(themeId)) return null;
  let data: Snapshot;
  try {
    data = JSON.parse(await readFile(path.join(process.cwd(), 'data/theme-fundamentals', `${themeId}.json`), 'utf8'));
  } catch { return null; }
  const [t, locale] = await Promise.all([getT(), getLocale()]);
  return <section aria-label={t('themes.fundamentals.ariaLabel', { title: data.title })} className="mt-4 min-w-0 border-t border-gray-800 pt-3">
    <h3 className="text-sm font-semibold text-gray-100">{t('themes.fundamentals.title', { title: data.title })}</h3>
    <p className="mt-1 text-[11px] text-gray-500">{t('themes.fundamentals.checked', { date: data.checkedAt })}</p>
    {data.metrics.map((m) => <div key={m.label} className="mt-3 rounded-lg border border-teal-400/25 bg-teal-400/10 p-3">
      <p className="text-xs text-gray-300">{m.label}</p><p className="text-xl font-semibold text-teal-300">{value(m.value, m.unit, locale)} <span className="text-xs">{m.unit}</span></p>
      <p className="text-[11px] text-gray-400">{t('themes.fundamentals.periodCut', { period: m.period, vintage: m.vintage })}</p>
      <a href={m.source} target="_blank" rel="noopener noreferrer" className="inline-flex min-h-11 items-center text-xs text-teal-300 underline">{t('themes.fundamentals.officialSource')}</a>
    </div>)}
    {data.series.map((s) => <details key={s.title} className="mt-3 min-w-0 rounded-lg border border-gray-800 p-3" open={!s.monthly}>
      <summary className="min-h-11 cursor-pointer text-xs font-semibold text-gray-100">{s.title}{s.monthly ? <span className="mt-1 block font-normal text-teal-300">{t('themes.fundamentals.monthly', { value: value(s.rows[0]?.values[0] ?? null, s.unit, locale), unit: s.unit, label: s.rows[0]?.label ?? '', vintage: s.vintage })}<a href={s.source} target="_blank" rel="noopener noreferrer" className="flex min-h-11 items-center underline">{t('themes.fundamentals.xlsSource', { name: s.sourceName })}</a></span> : null}</summary>
      <p className="text-[11px] text-gray-400">{s.kind === 'escenario' ? t('themes.fundamentals.kindScenario') : s.kind === 'estimacion_oficial' ? t('themes.fundamentals.kindOfficialEstimate') : t('themes.fundamentals.kindReported')}{t('themes.fundamentals.cutPublished', { unit: s.unit, vintage: s.vintage, published: s.published })}</p>
      <ul className="mt-2 space-y-2">{s.rows.map((r) => <li key={r.label} className="border-t border-gray-800 py-2">
        <p className="text-xs font-semibold text-gray-200">{r.label}</p>
        <dl className="mt-1 space-y-1">{s.columns.map((c, i) => <div key={c} className="flex flex-wrap justify-between gap-x-2 text-xs"><dt className="text-gray-400">{c}</dt><dd className={`font-semibold tabular-nums ${s.kind !== 'reportado' ? 'text-amber-300' : 'text-teal-300'}`}>{value(r.values[i], s.unit, locale)}</dd></div>)}</dl>
      {!s.monthly && s.columns.length === 1 && typeof r.values[0] === 'number' && !r.label.startsWith('Otros países') && !r.label.startsWith('Total mundial') ? <div aria-hidden="true" className="mt-1 h-1 rounded bg-gray-800"><div className="h-1 rounded bg-teal-400/60" style={{ width: `${Math.max(0, Math.min(100, r.values[0] / Math.max(...s.rows.filter((row) => !row.label.startsWith('Otros países') && !row.label.startsWith('Total mundial')).map((row) => typeof row.values[0] === 'number' ? row.values[0] : 0), 1) * 100))}%` }} /></div> : null}
      </li>)}</ul>
      {s.unavailableReason ? <p className="text-[11px] text-amber-300">{s.unavailableReason}</p> : null}
      {s.attribution ? <p className="mt-2 break-words text-[11px] text-gray-400">{s.attribution}</p> : null}
      {s.terms ? <a href={s.terms} target="_blank" rel="noopener noreferrer" className="flex min-h-11 items-center text-[11px] text-teal-300 underline">{t('themes.fundamentals.worldBankTerms')}</a> : null}
      <a href={s.source} target="_blank" rel="noopener noreferrer" className="inline-flex min-h-11 items-center text-xs text-teal-300 underline">{t('themes.fundamentals.sourceMethod', { name: s.sourceName })}</a>
    </details>)}
    <details className="mt-2 text-[11px] text-gray-500"><summary className="inline-flex min-h-11 cursor-pointer items-center">{t('themes.fundamentals.scope')}</summary><ul className="space-y-1">{data.notes.map((n) => <li key={n}>{n}</li>)}</ul></details>
    {data.links.map((l) => <a key={l.url} href={l.url} target="_blank" rel="noopener noreferrer" className="flex min-h-11 items-center text-[11px] text-teal-300 underline">{l.label}</a>)}
  </section>;
}
