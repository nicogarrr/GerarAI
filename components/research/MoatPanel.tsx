import { Check, Minus, X } from 'lucide-react';

import type { MoatScoreMetric } from '@/lib/actions/research.actions';
import { moatLabel } from '@/lib/glossary';
import { createFormatters, type Formatters } from '@/lib/format';
import { t, type TranslationKey, type TranslationVars } from '@/lib/i18n/t';

type TiFn = (key: TranslationKey, vars?: TranslationVars) => string;
/** Fallback español sin RequestScope (tests y render directo): el acceso es de main (lib/i18n/t). */
const esT: TiFn = t;
const esFormat = createFormatters('es');

type MoatCheck = {
  check: string;
  metric: string;
  threshold: string | null;
  value: string | null;
  passed: boolean | null;
  reason?: string;
};

const CHECK_LABELS: Record<string, TranslationKey> = {
  fcf_margin_5y_gt_5pct: 'research.moat.check.fcfMargin',
  net_margin_5y_gt_15pct: 'research.moat.check.netMargin',
  roe_5y_gt_15pct: 'research.moat.check.roe',
  roa_5y_gt_7pct: 'research.moat.check.roa',
  roic_gt_wacc: 'research.moat.check.roic',
  cfroi_approx_gt_wacc: 'research.moat.check.cfroi',
  owner_earnings_5y_positive: 'research.moat.check.ownerEarnings',
  capex_to_da_5y_le_150pct: 'research.moat.check.capexDa',
};

const PERCENT_METRICS = new Set([
  'fcf_margin_5y',
  'net_margin_5y',
  'roe_5y',
  'roa_5y',
  'roic',
  'cfroi_approx',
  'wacc',
]);

function formatCheckValue(check: MoatCheck, ti: TiFn, { formatCompact, formatNumber, formatPercent }: Formatters): string {
  if (check.value === null) return ti('research.moat.noData');
  if (PERCENT_METRICS.has(check.metric)) return formatPercent(check.value);
  if (check.metric === 'owner_earnings_5y') return formatCompact(check.value);
  return formatNumber(check.value, { maximumFractionDigits: 2 });
}

function formatThreshold(check: MoatCheck, { formatNumber, formatPercent }: Formatters): string {
  if (check.check === 'roic_gt_wacc' || check.check === 'cfroi_approx_gt_wacc') {
    return check.threshold === null ? '> WACC' : `> WACC (${formatPercent(check.threshold)})`;
  }
  if (check.check === 'owner_earnings_5y_positive') return '> 0';
  if (check.check === 'capex_to_da_5y_le_150pct') {
    return `≤ ${formatNumber(check.threshold ?? '1.5', { maximumFractionDigits: 1 })}`;
  }
  return check.threshold === null ? '' : `> ${formatPercent(check.threshold)}`;
}

function CheckIcon({ passed, ti }: { passed: boolean | null; ti: TiFn }) {
  if (passed === null) return <Minus aria-label={ti('research.moat.iconNa')} className="h-4 w-4 shrink-0 text-gray-500" />;
  if (passed) return <Check aria-label={ti('research.moat.iconPass')} className="h-4 w-4 shrink-0 text-teal-300" />;
  return <X aria-label={ti('research.moat.iconFail')} className="h-4 w-4 shrink-0 text-rose-400" />;
}

/**
 * Panel del marco de calidad (MOAT V2): score + 8 checks trazables con
 * valor y umbral. Los checks sin datos quedan como no evaluables; nunca
 * cuentan como superados.
 */
export function MoatPanel({ metric, company, ti = esT, fmt = esFormat }: { metric: MoatScoreMetric; company: { company_type: string; sector: string; factor_tags: string[]; valuation_model: string }; ti?: TiFn; fmt?: Formatters }) {
  const trace = metric.calculation_trace as {
    checks?: MoatCheck[];
    checks_evaluable?: number;
    checks_total?: number;
    score?: number;
    profile?: string;
    profile_label?: string;
    profile_reason?: string;
    score_comparable?: boolean;
  };
  const checks = trace.checks ?? [];
  const evaluable = trace.checks_evaluable ?? checks.filter((check) => check.passed !== null).length;
  const total = trace.checks_total ?? checks.length;
  const score = trace.score ?? checks.filter((check) => check.passed === true).length;

  // Old persisted V2 rows may predate profile-aware backend recalculation.
  // Fail closed on the company's explicit metadata even before the next refresh.
  const kind = company.company_type.toLowerCase();
  const tags = company.factor_tags.map((tag) => tag.toLowerCase());
  const model = company.valuation_model.toLowerCase();
  const earlyStage = kind.includes('pre_fcf') || kind.includes('pre_revenue') || tags.includes('pre_fcf');
  const financial = ['bank', 'insurer', 'insurance', 'asset_manager'].some((term) => kind.includes(term)) ||
    company.sector.toLowerCase() === 'financials';
  const cyclical = tags.includes('cyclical') || tags.includes('commodities') ||
    ['mining', 'commodity'].some((term) => kind.includes(term));
  const growth = tags.includes('growth') || kind.includes('growth') ||
    tags.includes('speculative') || model.includes('speculative');
  const unknown = ['', 'research_candidate', 'unknown', 'unassigned'].includes(kind) ||
    ['', 'unassigned', 'unknown'].includes(model);
  const historicalScoreNotComparable = earlyStage || financial || cyclical || growth || unknown;
  const profileLabel = ti(earlyStage ? 'research.moat.profile.early' :
    financial ? 'research.moat.profile.financial' : cyclical ? 'research.moat.profile.cyclical' :
    growth ? 'research.moat.profile.growth' : 'research.moat.profile.unclassified');
  const telecomEarlyStage = earlyStage && (
    tags.includes('telecom') || kind.includes('telecom')
  );
  const evidenceToReview = ti(telecomEarlyStage ?
    'research.moat.evidence.telecom' :
    earlyStage ? 'research.moat.evidence.early' :
    financial ? 'research.moat.evidence.financial' :
    cyclical ? 'research.moat.evidence.cyclical' :
    growth ? 'research.moat.evidence.growth' :
    'research.moat.evidence.other');
  const traceMatchesCurrentProfile = trace.profile === (
    earlyStage ? 'early_stage' : financial ? 'financial' : cyclical ? 'cyclical' :
    growth ? 'growth' : unknown ? 'unknown' : 'mature'
  );
  if (trace.score_comparable === false || historicalScoreNotComparable) {
    return <div className="space-y-3 text-sm leading-6 text-gray-300">
      <p className="font-semibold text-amber-300">{ti('research.moat.notComparable.title')}</p>
      <p>{ti('research.moat.notComparable.profile', { profile: historicalScoreNotComparable ? profileLabel : ti('research.moat.profile.general') })}
        {' '}{traceMatchesCurrentProfile ? trace.profile_reason : ti('research.moat.notComparable.basis')}</p>
      {!traceMatchesCurrentProfile && trace.profile ? <p className="text-amber-300">{ti('research.moat.notComparable.stale')}</p> : null}
      <p>{ti('research.moat.notComparable.why')}</p>
      <p><span className="font-medium text-gray-100">{ti('research.moat.notComparable.lookAt')}</span>{evidenceToReview} {ti('research.moat.notComparable.noSources')}</p>
      <p className="text-xs text-gray-500">{ti('research.moat.notComparable.footer')}</p>
    </div>;
  }

  if (metric.status === 'unavailable' || checks.length === 0) {
    return (
      <p className="text-sm leading-6 text-gray-400">
        {ti('research.moat.unavailable')}
      </p>
    );
  }

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-baseline gap-2">
        <span className="text-2xl font-semibold text-gray-100">
          {score}/{evaluable}
        </span>
        <span className="text-sm text-gray-400">
          {ti('research.moat.passed')}
          {evaluable < total ? ti('research.moat.missing', { count: total - evaluable }) : ''}
        </span>
        {metric.status === 'partial' ? (
          <span className="rounded-full border border-amber-800 bg-amber-950/40 px-2 py-0.5 text-xs text-amber-300">
            {ti('research.moat.partial')}
          </span>
        ) : null}
      </div>
      <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        {checks.map((check) => (
          <li
            className="flex min-w-0 items-center gap-3 rounded-lg border border-gray-800 bg-black/30 px-3 py-2.5"
            key={check.check}
          >
            <CheckIcon passed={check.passed} ti={ti} />
            <span className="min-w-0 flex-1 truncate text-sm text-gray-200">
              {CHECK_LABELS[check.check] ? ti(CHECK_LABELS[check.check]) : check.check}
            </span>
            <span className="shrink-0 text-right text-xs text-gray-400">
              <span className="block font-medium text-gray-300">{formatCheckValue(check, ti, fmt)}</span>
              <span className="block">{formatThreshold(check, fmt)}</span>
            </span>
          </li>
        ))}
      </ul>
      <p className="mt-3 text-xs leading-5 text-gray-500">
        {ti('research.moat.footer', { profile: trace.profile_label ?? ti('research.moat.generalProfile'), version: metric.definition_version })}
      </p>
    </div>
  );
}


/** Clasificación conceptual independiente de los umbrales financieros. */
export function MoatClassificationPanel({ moat, ti = esT }: { moat: import('@/lib/actions/research.actions').ResearchMoat | null; ti?: TiFn }) {
  if (!moat?.nico_mapping) return null;
  return <section className="space-y-3" aria-label={ti('research.moat.types.label')}>
    <h2 className="text-lg font-semibold text-gray-100">{ti('research.moat.types.title')}</h2>
    <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2">
      {Object.entries(moat.nico_mapping.types).map(([key, title]) => <li key={key} className="min-w-0 rounded-lg border border-gray-800 p-3">
        <h3 className="text-sm text-gray-200">{title}</h3>
        <p className="mt-1 text-xs text-gray-400">{(() => { const count = moat.moats.filter(item => item.nico_classification?.type === key).length; return count === 1 ? ti('research.moat.types.countOne', { count }) : ti('research.moat.types.countOther', { count }); })()}</p>
      </li>)}
    </ul>
    <details className="text-xs text-gray-400"><summary className="cursor-pointer">{ti('research.moat.types.mapping')}</summary>
      <ul className="mt-2 space-y-1">{Object.entries(moat.nico_mapping.mapping).map(([source, target]) => <li key={source}>{moatLabel(source)}: {moat.nico_mapping?.types[target]}</li>)}{moat.nico_mapping.unclassified.map(source => <li key={source}>{moatLabel(source)}: {ti('research.moat.types.unclassified')}</li>)}</ul>
      <p className="mt-2">{ti('research.moat.types.note')}</p>
    </details>
  </section>;
}

export function MoatChecklistPanel({ moat, ti = esT }: { moat: import('@/lib/actions/research.actions').ResearchMoat | null; ti?: TiFn }) {
  if (!moat?.qualitative_checklist) return null;
  return <section className="space-y-3" aria-label={ti('research.moat.checklist.label')}>
    <h2 className="text-lg font-semibold text-gray-100">{ti('research.moat.checklist.title')}</h2>
    {moat.qualitative_checklist.map(item => <div className="min-w-0 rounded-lg border border-gray-800 p-3" key={item.id}>
      <h3 className="text-sm font-medium text-gray-200">{item.question}</h3>
      {!item.excerpts.length ? <p className="mt-2 text-xs text-gray-500">{ti('research.moat.checklist.noEvidence')}</p> : <>
        <p className="mt-1 text-xs text-gray-500">{ti('research.moat.checklist.related')}</p>
        {item.excerpts.map((excerpt, index) => <blockquote className="mt-3 border-l border-gray-700 pl-3 text-sm text-gray-300" key={index}>
          <p className="break-words">{excerpt.quote}</p>
          <a className="mt-1 block break-words text-xs text-teal-300 underline" href={excerpt.source_url} target="_blank" rel="noopener noreferrer">{excerpt.source_title}</a>
          <span className="text-xs text-gray-500">{ti(excerpt.relation === 'contradicts' ? 'research.moat.checklist.against' : excerpt.relation === 'supports' ? 'research.moat.checklist.for' : 'research.moat.checklist.unclassified')}</span>
        </blockquote>)}
      </>}
    </div>)}
  </section>;
}
