import { EmptyState } from '@/components/ui/empty-state';
import { PagedList } from '@/components/ui/pagination';
import { FactCalculatedLabel } from '@/components/research/FactCalculatedLabel';
import { factDisplayAudit, factStalenessNotice } from '@/lib/research/fact-display-audit';
import { financialPeriod } from '@/lib/research/financial-display';
import { metricLabel } from '@/lib/research/metric-labels';
import { formatResearchMetric } from '@/lib/research/metric-value';
import type { ResearchFact } from '@/lib/actions/research.actions';
import type { ReactNode } from 'react';

function metricValue(value: number | string | null | undefined, unit: string) {
  if (value === null || value === undefined) return 'desconocido';
  const parsed = Number(value);
  return Number.isFinite(parsed) ? formatResearchMetric(parsed, unit) : 'desconocido';
}

/** Hechos visibles en móvil antes de paginar */
const FACTS_MOBILE_PAGE = 10;

/** La cifra enlaza a su fuente cuando el backend trae URL real del documento. */
function FactValueLink({ fact, children }: { fact: ResearchFact; children: ReactNode }) {
  if (!fact.source_url) return <>{children}</>;
  return (
    <a
      className="underline-offset-2 transition hover:text-teal-200 hover:underline"
      href={fact.source_url}
      rel="noopener noreferrer"
      target="_blank"
      title={fact.source_title ?? 'Fuente del dato'}
    >
      {children}
    </a>
  );
}

export function FactCard({ fact, ticker, staleness }: { fact: ResearchFact; ticker: string; staleness: string | null }) {
  const audit = factDisplayAudit(ticker, fact);
  return (
    <div className="rounded-lg border border-gray-800 p-3">
      <div className="flex items-center justify-between gap-2">
        <span className="font-medium text-gray-200">{metricLabel(fact.metric)}</span>
        <span className={`text-sm font-semibold ${audit ? 'text-gray-400' : 'text-teal-300'}`}>{audit ? 'N/D' : <><FactValueLink fact={fact}>{metricValue(fact.value, fact.unit)}</FactValueLink><FactCalculatedLabel fact={fact} /></>}</span>
      </div>
      {audit ? <p className="mt-2 text-xs text-amber-300">{audit}</p> : null}
      {!audit && staleness ? <p className="mt-2 text-xs text-amber-300">{staleness}</p> : null}
      <div className="mt-1.5 flex flex-wrap gap-2 text-xs text-gray-500">
        <span>{financialPeriod(fact.period)}</span>
      </div>
    </div>
  );
}

export function FactTable({ facts, refreshLabel, ticker }: { facts: ResearchFact[]; refreshLabel: string; ticker: string }) {
  if (!facts.length) {
    return (
      <EmptyState
        description={`Pulsa «${refreshLabel}» arriba para traerlos del proveedor indicado. Si sigue vacío, no hay datos persistidos: comprueba el resultado del refresh y la fuente.`}
        title="Todavía no hay hechos financieros persistidos."
      />
    );
  }
  // El último hecho de cada métrica (la lista viene ordenada por año fiscal
  // descendente) es el que un lector toma por «estado actual».
  const latestFiscalYear = facts.reduce((acc, fact) => Math.max(acc, fact.fiscal_year ?? 0), 0) || null;
  const latestIdByMetric = new Map<string, number>();
  for (const fact of facts) {
    if (!latestIdByMetric.has(fact.metric)) latestIdByMetric.set(fact.metric, fact.id);
  }
  const stalenessOf = (fact: ResearchFact) =>
    factStalenessNotice(fact, { isLatestForMetric: latestIdByMetric.get(fact.metric) === fact.id, latestFiscalYear });
  const hasUnofficial = facts.some((fact) => String(fact.source_type ?? '').toUpperCase() === 'YAHOO_FUNDAMENTALS');
  return (
    <>
      {hasUnofficial ? (
        <p className="mb-3 text-xs text-amber-300" role="note">
          Incluye cifras de una fuente no oficial, sin auditar ni contrastar con el emisor.
        </p>
      ) : null}
      {/* Móvil: cards paginadas (Anterior/Siguiente), sin «ver más» ni corte silencioso */}
      <div className="space-y-3 md:hidden">
        <PagedList
          items={facts.map((fact) => ({ key: `fact-${fact.id}`, node: <FactCard fact={fact} staleness={stalenessOf(fact)} ticker={ticker} /> }))}
          label="Hechos financieros"
          pageSize={FACTS_MOBILE_PAGE}
        />
      </div>
      {/* Escritorio: tabla completa */}
      <div aria-label="Hechos financieros" className="hidden overflow-x-auto md:block" role="region" tabIndex={0}>
      <table className="w-full text-left text-sm">
        <caption className="sr-only">Hechos financieros de la empresa (oficiales y, si se indica, no oficiales): métrica, periodo y valor</caption>
        <thead className="text-xs uppercase text-gray-500">
          <tr>
            <th className="border-b border-gray-800 py-2" scope="col">Métrica</th>
            <th className="border-b border-gray-800 py-2" scope="col">Periodo</th>
            <th className="border-b border-gray-800 py-2 text-right" scope="col">Valor</th>
          </tr>
        </thead>
        <tbody>
          {facts.map((fact) => (
            <tr key={fact.id} className="text-gray-300">
              <th className="border-b border-gray-900 py-2 text-left text-sm font-medium" scope="row">{metricLabel(fact.metric)}</th>
              <td className="border-b border-gray-900 py-2">{financialPeriod(fact.period)}</td>
              <td className="border-b border-gray-900 py-2 text-right">{factDisplayAudit(ticker, fact) ? <span className="text-gray-400">N/D<span className="mt-1 block text-xs text-amber-300">{factDisplayAudit(ticker, fact)}</span></span> : <><FactValueLink fact={fact}>{metricValue(fact.value, fact.unit)}</FactValueLink><FactCalculatedLabel fact={fact} />{stalenessOf(fact) ? <span className="mt-1 block text-xs text-amber-300">{stalenessOf(fact)}</span> : null}</>}</td>
            </tr>
          ))}
        </tbody>
      </table>
      </div>
    </>
  );
}
