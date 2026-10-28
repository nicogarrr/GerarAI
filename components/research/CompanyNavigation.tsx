import Link from 'next/link';

import { DecisionJournalEntryLink } from '@/components/research/DecisionJournalEntryLink';
import { MODULES, moduleHref, type View } from '@/lib/research/research-views';

const PRIMARY = [
  { label: 'Resumen', entry: 'overview', keys: ['overview', 'thesis'] },
  { label: 'Finanzas', entry: 'financials', keys: ['financials', 'valuation'] },
  { label: 'Fuentes', entry: 'documents', keys: ['documents', 'sources', 'chat'] },
] as const;
const ADVANCED = [
  { label: 'Valorar el negocio', keys: ['model', 'supuestos', 'market-opportunity', 'peers', 'moat', 'capital', 'terminal'] },
  { label: 'Contrastar y aprender', keys: ['changes', 'holders', 'directiva', 'lecciones'] },
  { label: 'Señales específicas', keys: ['satellites'] },
] as const;

/** Same links and visual tokens, with specialist tools behind one disclosure. */
export function CompanyNavigation({ ticker, activeView }: { ticker: string; activeView: View }) {
  const primary = PRIMARY.find((group) => group.keys.some((key) => key === activeView));
  const advancedActive = ADVANCED.some((group) => group.keys.some((key) => key === activeView));
  const link = (key: View, compact = false) => {
    const item = MODULES.find((item) => item.key === key)!;
    return <Link
      aria-current={activeView === key ? 'page' : undefined}
      className={compact
        ? `flex min-h-[44px] items-center justify-between gap-3 border-b border-gray-800 px-3 py-2.5 text-sm transition ${activeView === key ? 'bg-teal-950/40 text-teal-200' : 'text-gray-400 hover:text-gray-200'}`
        : `inline-flex min-h-[44px] items-center rounded-lg border px-4 py-2.5 text-sm transition ${activeView === key ? 'border-teal-600 bg-teal-950/40 text-teal-200' : 'border-gray-800 text-gray-400 hover:border-gray-700 hover:text-gray-200'}`}
      href={moduleHref(ticker, item)} key={key} scroll={'path' in item}
    >{item.label}{compact ? <span aria-hidden="true">→</span> : null}</Link>;
  };
  return <div className="min-w-0 space-y-3" data-testid="company-navigation">
    <nav aria-label="Secciones de la empresa" className="flex gap-x-6 border-b border-gray-800">
      {PRIMARY.map((group) => <Link
        aria-current={primary === group ? 'true' : undefined}
        className={`inline-flex min-h-[44px] items-center border-b-2 py-2.5 text-sm font-medium transition ${primary === group ? 'border-teal-300 text-gray-100' : 'border-transparent text-gray-500 hover:text-gray-200'}`}
        href={`/research/${encodeURIComponent(ticker)}?view=${group.entry}`} key={group.entry} scroll={false}
      >{group.label}</Link>)}
    </nav>
    {primary ? <nav aria-label={`Módulos de ${primary.label}`} className="flex flex-wrap gap-2">
      {primary.keys.map((key) => link(key))}
    </nav> : null}
    <details className="group rounded-lg border border-gray-800" open={advancedActive}>
      <summary className="flex min-h-[44px] cursor-pointer list-none items-center justify-between gap-3 rounded-lg px-3 py-2.5 text-sm text-gray-400 hover:text-gray-200 [&::-webkit-details-marker]:hidden">
        Análisis avanzado <span aria-hidden="true" className="transition-transform group-open:rotate-180">⌄</span>
      </summary>
      <nav aria-label="Análisis avanzado" className="grid gap-4 px-3 pb-3 md:grid-cols-3">
        {ADVANCED.map((group) => {
          const keys = group.keys.filter((key) => key !== 'satellites' || ticker === 'ASTS');
          return keys.length ? <div key={group.label}>
            <p className="mb-1 pt-2 text-xs font-semibold uppercase tracking-wide text-gray-500">{group.label}</p>
            {/* El enlace al diario apunta a un ancla y hace su propio scroll
                (DecisionJournalEntryLink): el App Router no baja al ancla si la
                página ya estaba desplazada (suite E2E 28/10). */}
            {keys.map((key) => key === 'changes'
              ? <div key={key}>{link(key, true)}<DecisionJournalEntryLink className="flex min-h-[44px] items-center justify-between gap-3 border-b border-gray-800 px-3 py-2.5 text-sm text-gray-400 hover:text-gray-200" ticker={ticker} /></div>
              : link(key, true))}
          </div> : null;
        })}
      </nav>
    </details>
  </div>;
}
