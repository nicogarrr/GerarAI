import { EmptyState } from '@/components/ui/empty-state';
import { PagedList } from '@/components/ui/pagination';
import { FactCalculatedLabel } from '@/components/research/FactCalculatedLabel';
import { factDisplayAudit, factStalenessNotice } from '@/lib/research/fact-display-audit';
import { financialPeriod } from '@/lib/research/financial-display';
import { metricLabel } from '@/lib/research/metric-labels';
import { formatResearchMetric } from '@/lib/research/metric-value';
import type { ResearchFact } from '@/lib/actions/research.actions';
import type { ReactNode } from 'react';
import type { Locale } from '@/lib/i18n/locale';
import { createTranslator } from '@/lib/i18n/translate';
import { naFor } from '@/lib/format';

function metricValue(value: number | string | null | undefined, unit: string, locale: Locale) {
  const unknown = createTranslator(locale)('research.facts.unknown');
  if (value === null || value === undefined) return unknown;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? formatResearchMetric(parsed, unit) : unknown;
}

/** Hechos visibles en móvil antes de paginar */
const FACTS_MOBILE_PAGE = 10;

/** La cifra enlaza a su fuente cuando el backend trae URL real del documento. */
function FactValueLink({ fact, children, locale }: { fact: ResearchFact; children: ReactNode; locale: Locale }) {
  if (!fact.source_url) return <>{children}</>;
  return (
    <a
      className="underline-offset-2 transition hover:text-teal-200 hover:underline"
      href={fact.source_url}
      rel="noopener noreferrer"
      target="_blank"
      title={fact.source_title ?? createTranslator(locale)('research.facts.sourceTitle')}
    >
      {children}
    </a>
  );
}

export function FactCard({ fact, ticker, staleness, locale = 'es' }: { fact: ResearchFact; ticker: string; staleness: string | null; locale?: Locale }) {
  const audit = factDisplayAudit(ticker, fact, locale);
  return (
    <div className="rounded-lg border border-gray-800 p-3">
      <div className="flex items-center justify-between gap-2">
        <span className="font-medium text-gray-200">{metricLabel(fact.metric, locale)}</span>
        <span className={`text-sm font-semibold ${audit ? 'text-gray-400' : 'text-teal-300'}`}>{audit ? naFor(locale) : <><FactValueLink fact={fact} locale={locale}>{metricValue(fact.value, fact.unit, locale)}</FactValueLink><FactCalculatedLabel fact={fact} /></>}</span>
      </div>
      {audit ? <p className="mt-2 text-xs text-amber-300">{audit}</p> : null}
      {!audit && staleness ? <p className="mt-2 text-xs text-amber-300">{staleness}</p> : null}
      <div className="mt-1.5 flex flex-wrap gap-2 text-xs text-gray-500">
        <span>{financialPeriod(fact.period, locale)}</span>
      </div>
    </div>
  );
}

export function FactTable({ facts, refreshLabel, ticker, locale = 'es' }: { facts: ResearchFact[]; refreshLabel: string; ticker: string; locale?: Locale }) {
  const t = createTranslator(locale);
  if (!facts.length) {
    return (
      <EmptyState
        description={t('research.facts.emptyDescription', { label: refreshLabel })}
        title={t('research.facts.emptyTitle')}
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
    factStalenessNotice(fact, { isLatestForMetric: latestIdByMetric.get(fact.metric) === fact.id, latestFiscalYear }, locale);
  const hasUnofficial = facts.some((fact) => String(fact.source_type ?? '').toUpperCase() === 'YAHOO_FUNDAMENTALS');
  return (
    <>
      {hasUnofficial ? (
        <p className="mb-3 text-xs text-amber-300" role="note">
          {t('research.facts.unofficial')}
        </p>
      ) : null}
      {/* Móvil: cards paginadas (Anterior/Siguiente), sin «ver más» ni corte silencioso */}
      <div className="space-y-3 md:hidden">
        <PagedList
          items={facts.map((fact) => ({ key: `fact-${fact.id}`, node: <FactCard fact={fact} locale={locale} staleness={stalenessOf(fact)} ticker={ticker} /> }))}
          label={t('research.facts.label')}
          pageSize={FACTS_MOBILE_PAGE}
        />
      </div>
      {/* Escritorio: tabla completa */}
      <div aria-label={t('research.facts.label')} className="hidden overflow-x-auto md:block" role="region" tabIndex={0}>
      <table className="w-full text-left text-sm">
        <caption className="sr-only">{t('research.facts.caption')}</caption>
        <thead className="text-xs uppercase text-gray-500">
          <tr>
            <th className="border-b border-gray-800 py-2" scope="col">{t('research.facts.colMetric')}</th>
            <th className="border-b border-gray-800 py-2" scope="col">{t('research.facts.colPeriod')}</th>
            <th className="border-b border-gray-800 py-2 text-right" scope="col">{t('research.facts.colValue')}</th>
          </tr>
        </thead>
        <tbody>
          {facts.map((fact) => (
            <tr key={fact.id} className="text-gray-300">
              <th className="border-b border-gray-900 py-2 text-left text-sm font-medium" scope="row">{metricLabel(fact.metric, locale)}</th>
              <td className="border-b border-gray-900 py-2">{financialPeriod(fact.period, locale)}</td>
              <td className="border-b border-gray-900 py-2 text-right">{factDisplayAudit(ticker, fact, locale) ? <span className="text-gray-400">{naFor(locale)}<span className="mt-1 block text-xs text-amber-300">{factDisplayAudit(ticker, fact, locale)}</span></span> : <><FactValueLink fact={fact} locale={locale}>{metricValue(fact.value, fact.unit, locale)}</FactValueLink><FactCalculatedLabel fact={fact} />{stalenessOf(fact) ? <span className="mt-1 block text-xs text-amber-300">{stalenessOf(fact)}</span> : null}</>}</td>
            </tr>
          ))}
        </tbody>
      </table>
      </div>
    </>
  );
}
