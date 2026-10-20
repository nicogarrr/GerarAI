import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { formatMoney, formatNumber } from '@/lib/format';

type SourceRow = { label: string; values: (number | string | null)[] };
type Series = { title: string; columns: string[]; unit: string; rows: SourceRow[]; source: string; sourceName: string; vintage: string; published: string; kind: string };
type Metric = { label: string; value: number | null; unit: string; period: string; source: string; vintage: string };
type Snapshot = { title: string; checkedAt: string; metrics: Metric[]; series: Series[]; notes: string[]; links: { label: string; url: string }[] };

function value(n: number | string | null, unit: string) {
  if (typeof n === 'string') return n;
  if (n === null || !Number.isFinite(n)) return 'N/D';
  return unit.startsWith('USD/') ? formatMoney(n, 'USD') : formatNumber(n, { maximumFractionDigits: 3 });
}

/** Reviewed public-source snapshots. No request-time remote calls or silent refresh.
 * A new theme adds a source-reviewed JSON file; no separate page or menu item.
 */
export async function ThemeFundamentals({ themeId }: { themeId: string }) {
  if (!['nuclear', 'materiales'].includes(themeId)) return null;
  let data: Snapshot;
  try {
    data = JSON.parse(await readFile(path.join(process.cwd(), 'data/theme-fundamentals', `${themeId}.json`), 'utf8'));
  } catch { return null; }
  return <section aria-label={`Fundamentales: ${data.title}`} className="mt-4 min-w-0 border-t border-gray-800 pt-3">
    <h3 className="text-sm font-semibold text-gray-100">{data.title} · fundamentales</h3>
    <p className="mt-1 text-[11px] text-gray-500">Instantánea revisada el {data.checkedAt} · no es dato en vivo</p>
    {data.metrics.map((m) => <div key={m.label} className="mt-3 rounded-lg border border-teal-400/25 bg-teal-400/10 p-3">
      <p className="text-xs text-gray-300">{m.label}</p><p className="text-xl font-semibold text-teal-300">{value(m.value, m.unit)} <span className="text-xs">{m.unit}</span></p>
      <p className="text-[11px] text-gray-400">{m.period} · corte {m.vintage}</p>
      <a href={m.source} target="_blank" rel="noopener noreferrer" className="inline-flex min-h-11 items-center text-xs text-teal-300 underline">Fuente oficial</a>
    </div>)}
    {data.series.map((s) => <details key={s.title} className="mt-3 min-w-0 rounded-lg border border-gray-800 p-3" open>
      <summary className="min-h-11 cursor-pointer text-xs font-semibold text-gray-100">{s.title}</summary>
      <p className="text-[11px] text-gray-400">{s.kind === 'escenario' ? 'Escenario atribuido · ' : s.kind === 'estimacion_oficial' ? 'Estimación oficial · ' : 'Reportado · '}{s.unit} · corte {s.vintage} · publicado {s.published}</p>
      <ul className="mt-2 space-y-2">{s.rows.map((r) => <li key={r.label} className="border-t border-gray-800 py-2">
        <p className="text-xs font-semibold text-gray-200">{r.label}</p>
        <dl className="mt-1 space-y-1">{s.columns.map((c, i) => <div key={c} className="flex flex-wrap justify-between gap-x-2 text-xs"><dt className="text-gray-400">{c}</dt><dd className={`font-semibold tabular-nums ${s.kind !== 'reportado' ? 'text-amber-300' : 'text-teal-300'}`}>{value(r.values[i], s.unit)}</dd></div>)}</dl>
      {s.columns.length === 1 && typeof r.values[0] === 'number' ? <div aria-hidden="true" className="mt-1 h-1 rounded bg-gray-800"><div className="h-1 rounded bg-teal-400/60" style={{ width: `${Math.max(0, Math.min(100, r.values[0] / Math.max(...s.rows.map((row) => typeof row.values[0] === 'number' ? row.values[0] : 0), 1) * 100))}%` }} /></div> : null}
      </li>)}</ul>
      <a href={s.source} target="_blank" rel="noopener noreferrer" className="inline-flex min-h-11 items-center text-xs text-teal-300 underline">{s.sourceName} · fuente y metodología</a>
    </details>)}
    <details className="mt-2 text-[11px] text-gray-500"><summary className="inline-flex min-h-11 cursor-pointer items-center">Alcance y límites</summary><ul className="space-y-1">{data.notes.map((n) => <li key={n}>{n}</li>)}</ul></details>
    {data.links.map((l) => <a key={l.url} href={l.url} target="_blank" rel="noopener noreferrer" className="flex min-h-11 items-center text-[11px] text-teal-300 underline">{l.label}</a>)}
  </section>;
}
