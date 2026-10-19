import { Check, Minus, X } from 'lucide-react';

import type { MoatScoreMetric } from '@/lib/actions/research.actions';
import { moatLabel } from '@/lib/glossary';
import { formatCompact, formatNumber, formatPercent } from '@/lib/format';

type MoatCheck = {
  check: string;
  metric: string;
  threshold: string | null;
  value: string | null;
  passed: boolean | null;
  reason?: string;
};

const CHECK_LABELS: Record<string, string> = {
  fcf_margin_5y_gt_5pct: 'Margen FCF 5 años',
  net_margin_5y_gt_15pct: 'Margen neto 5 años',
  roe_5y_gt_15pct: 'ROE 5 años',
  roa_5y_gt_7pct: 'ROA 5 años',
  roic_gt_wacc: 'ROIC',
  cfroi_approx_gt_wacc: 'CFROI (aprox.)',
  owner_earnings_5y_positive: 'Owner earnings 5 años',
  capex_to_da_5y_le_150pct: 'Capex / D&A 5 años',
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

function formatCheckValue(check: MoatCheck): string {
  if (check.value === null) return 'sin datos';
  if (PERCENT_METRICS.has(check.metric)) return formatPercent(check.value);
  if (check.metric === 'owner_earnings_5y') return formatCompact(check.value);
  return formatNumber(check.value, { maximumFractionDigits: 2 });
}

function formatThreshold(check: MoatCheck): string {
  if (check.check === 'roic_gt_wacc' || check.check === 'cfroi_approx_gt_wacc') {
    return check.threshold === null ? '> WACC' : `> WACC (${formatPercent(check.threshold)})`;
  }
  if (check.check === 'owner_earnings_5y_positive') return '> 0';
  if (check.check === 'capex_to_da_5y_le_150pct') {
    return `≤ ${formatNumber(check.threshold ?? '1.5', { maximumFractionDigits: 1 })}`;
  }
  return check.threshold === null ? '' : `> ${formatPercent(check.threshold)}`;
}

function CheckIcon({ passed }: { passed: boolean | null }) {
  if (passed === null) return <Minus aria-label="no evaluable" className="h-4 w-4 shrink-0 text-gray-500" />;
  if (passed) return <Check aria-label="superado" className="h-4 w-4 shrink-0 text-teal-300" />;
  return <X aria-label="no superado" className="h-4 w-4 shrink-0 text-rose-400" />;
}

/**
 * Panel del marco de calidad (MOAT V2): score + 8 checks trazables con
 * valor y umbral. Los checks sin datos quedan como no evaluables; nunca
 * cuentan como superados.
 */
export function MoatPanel({ metric, company }: { metric: MoatScoreMetric; company: { company_type: string; sector: string; factor_tags: string[]; valuation_model: string } }) {
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
  const profileLabel = earlyStage ? 'Etapa temprana / antes de caja recurrente' :
    financial ? 'Financiera' : cyclical ? 'Cíclica o materias primas' :
    growth ? 'Crecimiento / expansión' : 'Etapa no clasificada';
  const telecomEarlyStage = earlyStage && (
    tags.includes('telecom') || kind.includes('telecom')
  );
  const evidenceToReview = telecomEarlyStage ?
    'Licencias o espectro, despliegue real de la red, contratos verificables y financiación necesaria.' :
    earlyStage ? 'Hitos operativos verificables, acuerdos comerciales, necesidad de financiación y barreras específicas del negocio.' :
    financial ? 'Coste de financiación, calidad de activos, retención y ventajas regulatorias documentadas.' :
    cyclical ? 'Coste relativo a competidores, reservas y rentabilidad a través de ciclos completos.' :
    growth ? 'Retención de clientes, costes de cambio y economía unitaria verificada.' :
    'Identifica el tipo de empresa y contrasta ventajas competitivas con fuentes primarias.';
  const traceMatchesCurrentProfile = trace.profile === (
    earlyStage ? 'early_stage' : financial ? 'financial' : cyclical ? 'cyclical' :
    growth ? 'growth' : unknown ? 'unknown' : 'mature'
  );
  if (trace.score_comparable === false || historicalScoreNotComparable) {
    return <div className="space-y-3 text-sm leading-6 text-gray-300">
      <p className="font-semibold text-amber-300">No evaluable con los 8 umbrales generales</p>
      <p>Perfil actual: {historicalScoreNotComparable ? profileLabel : 'Negocio operativo (perfil general)'}.
        {' '}{traceMatchesCurrentProfile ? trace.profile_reason : 'Clasificación basada en el tipo, sector o etiquetas actuales de esta empresa.'}</p>
      {!traceMatchesCurrentProfile && trace.profile ? <p className="text-amber-300">El perfil guardado es anterior a la clasificación actual; recalcula las métricas antes de interpretar una puntuación.</p> : null}
      <p>En esta etapa o tipo de empresa, pérdidas, reinversión y rentabilidad histórica no prueban ni descartan un foso. No mostramos 0/8: hace falta evidencia verificable de barreras, contratos, costes de cambio o ventajas frente a competidores.</p>
      <p><span className="font-medium text-gray-100">Qué evidencia mirar: </span>{evidenceToReview} No se puntúa sin fuentes.</p>
      <p className="text-xs text-gray-500">Los datos financieros siguen disponibles como métricas individuales. El perfil no es una calificación de foso.</p>
    </div>;
  }

  if (metric.status === 'unavailable' || checks.length === 0) {
    return (
      <p className="text-sm leading-6 text-gray-400">
        Sin datos suficientes para evaluar la calidad financiera de esta empresa. Ningún criterio se
        da por superado sin datos. Esto no es un dictamen de foso competitivo.
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
          criterios financieros superados
          {evaluable < total ? ` (${total - evaluable} sin datos)` : ''}
        </span>
        {metric.status === 'partial' ? (
          <span className="rounded-full border border-amber-800 bg-amber-950/40 px-2 py-0.5 text-xs text-amber-300">
            parcial
          </span>
        ) : null}
      </div>
      <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        {checks.map((check) => (
          <li
            className="flex min-w-0 items-center gap-3 rounded-lg border border-gray-800 bg-black/30 px-3 py-2.5"
            key={check.check}
          >
            <CheckIcon passed={check.passed} />
            <span className="min-w-0 flex-1 truncate text-sm text-gray-200">
              {CHECK_LABELS[check.check] ?? check.check}
            </span>
            <span className="shrink-0 text-right text-xs text-gray-400">
              <span className="block font-medium text-gray-300">{formatCheckValue(check)}</span>
              <span className="block">{formatThreshold(check)}</span>
            </span>
          </li>
        ))}
      </ul>
      <p className="mt-3 text-xs leading-5 text-gray-500">
        Diagnóstico de calidad financiera para {trace.profile_label ?? 'perfil general'}, no una prueba de foso competitivo.
        Marco V2 ({metric.definition_version}); los criterios sin datos no cuentan como superados. Consulta /metodologia.
      </p>
    </div>
  );
}


/** Clasificación conceptual independiente de los umbrales financieros. */
export function MoatClassificationPanel({ moat }: { moat: import('@/lib/actions/research.actions').ResearchMoat | null }) {
  if (!moat?.nico_mapping) return null;
  return <section className="space-y-3" aria-label="Tipos de foso de Nico">
    <h2 className="text-lg font-semibold text-gray-100">Tipos de foso</h2>
    <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2">
      {Object.entries(moat.nico_mapping.types).map(([key, title]) => <li key={key} className="min-w-0 rounded-lg border border-gray-800 p-3">
        <h3 className="text-sm text-gray-200">{title}</h3>
        <p className="mt-1 text-xs text-gray-400">{moat.moats.filter(item => item.nico_classification?.type === key).length} categorías con evaluación</p>
      </li>)}
    </ul>
    <details className="text-xs text-gray-400"><summary className="cursor-pointer">Mapeo declarado</summary>
      <ul className="mt-2 space-y-1">{Object.entries(moat.nico_mapping.mapping).map(([source, target]) => <li key={source}>{moatLabel(source)}: {moat.nico_mapping?.types[target]}</li>)}{moat.nico_mapping.unclassified.map(source => <li key={source}>{moatLabel(source)}: Sin clasificar</li>)}</ul>
      <p className="mt-2">Capa editorial, no cambia la puntuación. Red, distribución, datos, ecosistema y proceso quedan sin clasificar por admitir varios mecanismos.</p>
    </details>
  </section>;
}
