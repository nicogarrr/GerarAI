import { hasRows, safeLink, thesisParagraphs, type ThesisV2, type ThesisV2Table } from '@/lib/research/thesis-v2';
import type { TranslateFn } from '@/lib/i18n/translate';

/**
 * Tesis v2 de nivel comité dentro del Informe (pedido de Nico, 8-nov-2026:
 * «que lleguemos a un nivel de tesis mucho mejor»). Pura: cifras y tablas ya
 * vienen calculadas por el código; aquí solo se maquetan como documento
 * imprimible (prosa larga a una columna, tablas que no se parten de página).
 */
export function AnalystReportThesis({ thesis, t }: { thesis: ThesisV2 | null; t: TranslateFn }) {
  if (!thesis) return null;
  const h = thesis.headline;
  const facts: Array<[string, string | null]> = [
    [t('research.informe.tesis.price'), h.price],
    [t('research.informe.tesis.irr5'), h.tir5],
    [t('research.informe.tesis.irr10'), h.tir10],
    [t('research.informe.tesis.base10'), h.base_tir10],
    [t('research.informe.tesis.coe'), h.cost_of_equity],
    [t('research.informe.tesis.multiple'), h.multiple],
    [t('research.informe.tesis.peers'), h.peers_median],
  ];
  return (
    <article className="print-document min-w-0 rounded-xl border border-gray-800 bg-surface-1 p-4 sm:p-6 print:break-before-page" data-testid="informe-tesis-v2" aria-labelledby="tesis-v2-title">
      <header className="border-b border-gray-800 pb-3">
        <p className="text-xs uppercase tracking-wide text-gray-500">{t('research.informe.tesis.kicker', { date: thesis.as_of ?? '' })}</p>
        <h2 id="tesis-v2-title" className="mt-1 text-xl font-semibold text-gray-100">{t('research.informe.tesis.title', { company: thesis.company, ticker: thesis.ticker })}</h2>
        <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-4" data-testid="tesis-v2-headline">
          {facts.map(([label, value]) => (
            <div className="min-w-0" key={label}>
              <dt className="text-xs text-gray-500">{label}</dt>
              <dd className="font-semibold text-gray-100">{value ?? t('research.informe.na')}</dd>
            </div>
          ))}
        </dl>
        {thesis.probability_reason ? <p className="mt-2 text-xs text-gray-400">{t('research.informe.tesis.probabilities', { reason: thesis.probability_reason })}</p> : null}
        {thesis.stale ? <p className="mt-2 text-xs text-amber-300">{t('research.informe.tesis.stale')}</p> : null}
      </header>
      {thesis.sections.map((section) => (
        <section className="mt-5" key={section.key} aria-labelledby={`tesis-${section.key}`}>
          <h3 id={`tesis-${section.key}`} className="mb-2 border-b border-gray-800 pb-1 text-base font-semibold text-teal-300 print:break-after-avoid">{section.title}</h3>
          {thesisParagraphs(section.text).map((p, i) => (
            <p className="mb-3 text-[15px] leading-relaxed text-gray-200 print:text-justify print:text-[11pt]" key={i}>{p}</p>
          ))}
          {section.tables.filter(hasRows).map((table) => <ThesisTable key={table.title} table={table} />)}
        </section>
      ))}
      <footer className="mt-6 border-t border-gray-800 pt-3 text-xs text-gray-500">
        <p>{t('research.informe.tesis.footer')}</p>
        {thesis.warnings.length ? (
          <>
            <p className="mt-2 font-semibold text-gray-400">{t('research.informe.tesis.warnings')}</p>
            <ul className="ml-4 list-disc">{thesis.warnings.map((w) => <li key={w}>{w}</li>)}</ul>
          </>
        ) : null}
        {thesis.sources.length ? (
          <p className="mt-2">{t('research.informe.tesis.sources', { list: thesis.sources.join(' · ') })}</p>
        ) : null}
      </footer>
    </article>
  );
}

function ThesisTable({ table }: { table: ThesisV2Table }) {
  return (
    <div className="mb-4 overflow-x-auto break-inside-avoid" role="region" aria-label={table.title} tabIndex={0}>
      <table className="w-full text-right text-xs print:text-[9pt]">
        <caption className="mb-1 text-left text-xs font-semibold text-gray-400">{table.title}</caption>
        <thead className="text-gray-500">
          <tr>{table.head.map((c, i) => <th className={`py-1 pl-2 font-medium ${i === 0 ? 'text-left' : ''}`} key={`${c}-${i}`} scope="col">{c}</th>)}</tr>
        </thead>
        <tbody>
          {table.rows.map((row, r) => {
            const href = safeLink(table.links?.[r]);
            return (
              <tr className="border-t border-gray-800" key={r}>
                {row.map((cell, i) => {
                  if (i === 0) return <th className="py-1 text-left font-normal text-gray-300" key={i} scope="row">{cell}</th>;
                  const last = i === row.length - 1;
                  return (
                    <td className="whitespace-nowrap py-1 pl-2 text-gray-100" key={i}>
                      {last && href ? <a className="text-teal-300 underline" href={href} target="_blank" rel="noopener noreferrer">{cell || href}</a> : cell}
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
