import { impliedGrowthView } from '@/lib/research/implied-growth';
import Link from 'next/link';
import { modelConditionState } from '@/lib/research/coverage-state';
import { formatCompact, formatMarketDate, formatNumber, formatPercent, NA } from '@/lib/format';
import { etiquetaTipoEvento } from '@/lib/labels';
import { metricLabel } from '@/lib/research/metric-labels';
import { financialFormula } from '@/lib/research/financial-display';
import { frameworkLabel, frameworkTerm } from '@/lib/research/framework-terms';
import { expectationMetricLabel, reviewStatusLabel } from '@/lib/research/expectation-labels';
import { ExpectationsList, type ExpectationRow } from '@/components/research/ExpectationsList';
import { BarChart3, BrainCircuit, CircleHelp, GitBranch } from 'lucide-react';
import { GlossaryTerm } from '@/components/GlossaryTerm';
import { MutationForm } from '@/components/forms/MutationForm';
import ScenarioAssumptions from '@/components/research/ScenarioAssumptions';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { describeFairValue, describeTrade, type JournalTrade } from '@/lib/research/journal-trade';
import {
  createResearchDecision,
  linkResearchDecisionTrade,
  reviewResearchExpectations,
  type ResearchDecisionJournalEntry,
  type ResearchExpectationReview,
  type ResearchLongTermModel,
} from '@/lib/actions/research.actions';

function compactNumber(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value)) return NA;
  return formatCompact(value, { maximumFractionDigits: 1 });
}

function percentage(value: number | null | undefined) {
  return value == null || !Number.isFinite(value) ? NA : formatPercent(value);
}

/** El WACC solo se muestra con base documentada (CalculatedMetric u
 *  InferredInput). El valor `model_policy` es un supuesto de vista previa sin
 *  fuente: se muestra N/D, nunca una cifra sin base (regla OFICIAL/INFERIDO). */
function waccHasSource(wacc: { source_type: string } | null | undefined) {
  return wacc != null && wacc.source_type !== 'model_policy';
}

function waccDisplay(wacc: { value: number | null; source_type: string } | null | undefined) {
  if (!waccHasSource(wacc)) return NA;
  return percentage(wacc?.value);
}

/** Frases «what must be true» en español (F24). El backend las genera en
 *  inglés, pero cada condición trae id + valor estructurados: se redacta la
 *  prosa en la UI. Id desconocido: se muestra la frase original, nunca se
 *  oculta una condición. */
function conditionInSpanish(
  item: { id: string; condition: string; value?: number | null; comparison?: number | null },
  bindingConstraint: string | null | undefined,
  waccHasSource = true,
): string {
  const pct = (v: number | null | undefined) =>
    v == null || !Number.isFinite(v) ? 's/d' : formatPercent(v);
  switch (item.id) {
    case 'revenue_growth':
      return `Los ingresos deben crecer al menos un ${pct(item.value)} anual`;
    case 'fcf_margin':
      return `El margen FCF normalizado debe mantenerse al menos en un ${pct(item.value)}`;
    case 'roic_above_wacc':
      return `El ROIC (${pct(item.value)}) debe mantenerse por encima del WACC (${waccHasSource ? pct(item.comparison) : 'N/D, sin fuente'}) para crear valor`;
    case 'price_expectations':
      return `El precio actual descuenta un crecimiento de ingresos de en torno al ${pct(item.value)}${item.comparison != null ? ` (con margen FCF normalizado ${pct(item.comparison)})` : ''}`;
    case 'share_count':
      return `El número de acciones no debe crecer más rápido que lo asumido por el modelo (${pct(item.value)} anual)`;
    case 'competitive_position':
      return 'La cuota de mercado no debe deteriorarse materialmente';
    case 'binding_constraint':
      return `La restricción vinculante (${bindingConstraint ? metricLabel(bindingConstraint) : 'desconocida'}) debe soportar el escenario base`;
    default:
      return item.condition;
  }
}


/** F24: la vista del modelo se presenta en español. Los ids tecnicos
 *  (organic_growth, PREVIEW_ONLY, nombres de drivers/KPIs) se quedan como
 *  estan; lo que se traduce son etiquetas y prosa de presentacion. Los
 *  mapas tienen fallback al texto original: nunca se oculta informacion. */
const SCENARIO_LABELS: Record<string, string> = { bear: 'Bajista', base: 'Base', bull: 'Alcista' };
const QUALITY_LABELS: Record<string, string> = { high: 'alta', medium: 'media', unknown: 's/d' };
const VERDICT_LABELS: Record<string, string> = {
  unknown: 's/d',
  reasonable: 'razonable',
  aggressive_but_possible: 'agresivo pero posible',
  unrealistic_without_new_evidence: 'irrealista sin nueva evidencia',
};
const IMPACT_LABELS: Record<string, string> = { positive: 'positivo', negative: 'negativo', neutral: 'neutro', none: 'sin impacto' };
const PROSE_ES: Record<string, string> = {
  'Growth quality is a partial assessment until price/volume/mix, M&A and working-capital drivers are sourced.':
    'La calidad del crecimiento es una evaluación parcial hasta que se contrasten los drivers de precio/volumen/mix, M&A y capital de trabajo.',
  'net income + D&A - maintenance capex - normalized change in working capital':
    'beneficio neto + D&A − capex de mantenimiento − cambio normalizado del capital de trabajo',
};
const DECISION_LABELS: Record<string, string> = {
  buy: 'Comprar', hold: 'Mantener', trim: 'Reducir', sell: 'Vender', watch: 'Vigilar', avoid: 'Evitar',
};
const MODEL_STATUS_LABELS: Record<string, string> = {
  // Catálogo cerrado de long_term_model_service: ok, insufficient_data,
  // missing_mandatory_drivers, preview_only.
  ok: 'completo',
  blocked: 'bloqueado',
  insufficient_data: 'datos insuficientes',
  // Estado de snapshots anteriores al 27/10/2026; hoy un KPI sin dato no bloquea.
  missing_mandatory_drivers: 'con datos operativos pendientes',
  preview_only: 'solo vista previa',
};
function translate(map: Record<string, string>, value: string | null | undefined, fallback = 's/d'): string {
  if (value == null || value === '') return fallback;
  return map[value] ?? value;
}

/** Fórmula del beneficio del propietario tal como llega del backend. */
export function ownerEarningsFormulaLabel(formula: string): string {
  return PROSE_ES[formula] ?? financialFormula(formula);
}

/** Driver, KPI, entrada o restricción del modelo en español (marco por tipo de empresa primero, luego métricas). */
export function termLabel(raw: string): string {
  return frameworkTerm(raw) ?? metricLabel(raw);
}

function ModelStat({ label, value, positive = false, hint }: { label: string; value: string; positive?: boolean; hint?: string }) {
  return (
    <div className="rounded-lg border border-gray-800 bg-surface-1 p-4" title={hint}>
      <div className="text-xs font-semibold uppercase text-gray-500">{label}</div>
      <div className={`mt-2 text-2xl font-semibold ${positive ? 'text-teal-300' : 'text-gray-100'}`}>{value}</div>
    </div>
  );
}

export function LongTermModelPanel({ model, ticker }: { model: ResearchLongTermModel | null; ticker?: string }) {
  if (!model) {
    return (
      <section className="rounded-lg border border-gray-800 bg-surface-1 p-5">
        <div className="flex items-center gap-2">
          <BrainCircuit aria-hidden="true" className="h-5 w-5 text-teal-300" />
          <h2 className="text-lg font-semibold text-gray-100">Modelo fundamental a largo plazo</h2>
        </div>
        <p className="mt-3 text-sm text-gray-500">No se pudo construir el modelo con los datos disponibles.</p>
      </section>
    );
  }

  const base = model.scenarios.base;
  const year5 = base?.year_5 ?? base?.terminal_year;
  const terminal = base?.terminal_year;
  const growthAssumption = model.assumptions.revenue_growth;
  const marginAssumption = model.assumptions.fcf_margin;

  return (
    <section className="rounded-lg border border-gray-800 bg-surface-1 p-5">
      <div className="mb-4 flex flex-col gap-2 md:flex-row md:items-center">
        <div className="flex items-center gap-2">
          <BrainCircuit aria-hidden="true" className="h-5 w-5 text-teal-300" />
          <h2 className="text-lg font-semibold text-gray-100">Modelo fundamental a largo plazo</h2>
        </div>
        <span className="text-xs uppercase tracking-wide text-gray-500 md:ml-auto">
          {/* La cobertura mide valores PRESENTES con fuente, no completitud:
              siempre con su alcance explícito y, si no es publicable
              (missing_inputs, bloqueos o cobertura <60), con la causa visible. */}
          {model.horizon_years} años de proyección · {translate(MODEL_STATUS_LABELS, model.status, model.status)}
          {` · valores con fuente ${formatNumber(model.source_coverage.coverage_percent, { maximumFractionDigits: 0 })} % de los presentes`}
          {model.publishable ? '' : ' · modelo no publicable'}
        </span>
      </div>
      <p className="mb-4 text-xs leading-5 text-gray-500">
        El «valor por acción» de cada escenario es un cálculo interno del modelo
        (versión {model.model_version}{model.as_of_period ? ` · datos a ${model.as_of_period}` : ' · fecha s/d'}).
        {/* Una sola fuente de verdad (WorldStocks punto 3): la valoración de
            referencia de la ficha es la vista Valoración (motor persistido y
            publicable). Este cálculo interno puede no coincidir con ella. */}
        La valoración de referencia de la ficha es la de la vista Valoración
        {ticker ? (
          <>
            {' ('}
            <Link className="text-teal-300 underline decoration-gray-700 underline-offset-4 hover:text-teal-200" href={`/research/${encodeURIComponent(ticker)}?view=valuation`}>
              ver sus 3 escenarios
            </Link>
            )
          </>
        ) : null}
        : si no coincide con este cálculo interno, manda ella; compara versión y fecha antes de usarlo.
      </p>

      {model.missing_inputs.length ? (
        <div className="mb-4 rounded-md border border-amber-900/70 bg-amber-950/20 p-3 text-sm text-amber-200">
          Modelo no publicable: faltan {model.missing_inputs.map(termLabel).join(', ')}.
        </div>
      ) : null}

      <div className="mb-4 rounded-md border border-gray-800 bg-black/10 p-3 text-xs leading-5 text-gray-400">
        <span className="font-semibold text-gray-300">Drivers:</span> {model.framework.revenue_drivers.map(termLabel).join(' · ')}
        <span aria-hidden="true" className="mx-2 text-gray-700">|</span>
        <span className="font-semibold text-gray-300">KPIs:</span> {model.framework.kpis.map(termLabel).join(' · ')}
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <ModelStat label={`Ingresos ${year5?.year ?? 'año 5'}`} value={compactNumber(year5?.revenue)} />
        <ModelStat label={`FCF ${year5?.year ?? 'año 5'}`} value={compactNumber(year5?.free_cash_flow)} positive />
        <ModelStat label="Margen FCF" value={percentage(year5?.fcf_margin)} />
        <ModelStat label="FCF / acción" value={compactNumber(year5?.fcf_per_share)} positive hint={year5?.fcf_per_share == null ? 'N/D: el modelo no proyecta el número de acciones cuando no puede determinar cómo se financia el hueco de caja.' : undefined} />
      </div>

      <div className="mt-5 grid grid-cols-1 gap-6 lg:grid-cols-[1.2fr_0.8fr]">
        {/* F319: min-w-0 en las pistas del grid: sin él, el min-content de
            la tabla de escenarios (min-w-[540px]) expandía la pista por
            encima del contenedor a 768-1279px en vez de dejar que el
            wrapper overflow-x-auto recortara con scroll interno. */}
        {/* F27: un modelo no publicable (falta WACC u otro input) NO puede
            ensenar escenarios con valor/accion: serian dos valoraciones
            incompatibles a la vez. Se muestran solo cuando publishable. */}
        {model.publishable ? (
        <div className="min-w-0">
          <div className="mb-3 text-xs font-semibold uppercase tracking-wide text-gray-500">Bajista / Base / Alcista</div>
          {/* Móvil: cards sin scroll horizontal */}
          <div className="space-y-3 md:hidden">
            {Object.entries(model.scenarios).map(([name, scenario]) => {
              const point = scenario.terminal_year;
              return (
                <div key={name} className="rounded-lg border border-gray-800 p-3">
                  <div className="font-semibold capitalize text-gray-200">{translate(SCENARIO_LABELS, name)}</div>
                  <dl className="mt-2 space-y-1.5 text-sm">
                    <div className="flex items-center justify-between gap-2"><dt className="text-gray-500">Ingresos</dt><dd className="text-gray-300">{compactNumber(point?.revenue)}</dd></div>
                    <div className="flex items-center justify-between gap-2"><dt className="text-gray-500">FCF</dt><dd className="text-gray-300">{compactNumber(point?.free_cash_flow)}</dd></div>
                    <div className="flex items-center justify-between gap-2"><dt className="text-gray-500">Margen FCF</dt><dd className="text-gray-300">{percentage(point?.fcf_margin)}</dd></div>
                    <div className="flex items-center justify-between gap-2"><dt className="text-gray-500">Valor/acción</dt><dd className="font-semibold text-teal-200">{compactNumber(scenario.valuation?.value_per_share)}</dd></div>
                  </dl>
                </div>
              );
            })}
          </div>
          <div aria-label="Escenarios del modelo" className="hidden overflow-x-auto md:block" role="region" tabIndex={0}>
            <table className="w-full min-w-[540px] text-left text-sm">
              <caption className="sr-only">Escenarios bajista, base y alcista del modelo, con ingresos, FCF, margen FCF y valor por acción</caption>
              <thead className="text-xs uppercase text-gray-500">
                <tr>
                  <th className="border-b border-gray-800 py-2" scope="col">Escenario</th>
                  <th className="border-b border-gray-800 py-2 text-right" scope="col">Ingresos</th>
                  <th className="border-b border-gray-800 py-2 text-right" scope="col">FCF</th>
                  <th className="border-b border-gray-800 py-2 text-right" scope="col">Margen FCF</th>
                  <th className="border-b border-gray-800 py-2 text-right" scope="col">Valor/acción</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(model.scenarios).map(([name, scenario]) => {
                  const point = scenario.terminal_year;
                  return (
                    <tr key={name} className="border-b border-gray-900 last:border-0">
                      <th className="py-3 text-left text-sm font-semibold capitalize text-gray-200" scope="row">{translate(SCENARIO_LABELS, name)}</th>
                      <td className="py-3 text-right text-gray-300">{compactNumber(point?.revenue)}</td>
                      <td className="py-3 text-right text-gray-300">{compactNumber(point?.free_cash_flow)}</td>
                      <td className="py-3 text-right text-gray-300">{percentage(point?.fcf_margin)}</td>
                      <td className="py-3 text-right text-teal-200">{compactNumber(scenario.valuation?.value_per_share)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <ScenarioAssumptions />
        </div>
        ) : null}

        <div className="space-y-3">
          <div className="rounded-md border border-gray-800 p-3">
            <div className="text-xs font-semibold uppercase text-gray-500">Supuestos base</div>
            <div className="mt-2 grid gap-2 text-sm">
              <div className="flex justify-between gap-3"><span className="text-gray-400">CAGR de ingresos</span><span className="text-gray-200">{percentage(growthAssumption?.value)}</span></div>
              <div className="flex justify-between gap-3"><span className="text-gray-400">Margen FCF normalizado</span><span className="text-gray-200">{percentage(marginAssumption?.value)}</span></div>
              <div className="flex justify-between gap-3"><span className="text-gray-400"><GlossaryTerm k="roic" icon={false}>ROIC</GlossaryTerm> / <GlossaryTerm k="wacc" icon={false}>WACC</GlossaryTerm></span><span className="text-gray-200">{percentage(terminal?.roic)} / {waccDisplay(model.assumptions.wacc)}</span></div>
            </div>
            <p className="mt-3 text-xs leading-5 text-gray-500">
              Fuentes ingresos: <AssumptionSources fuentes={growthAssumption?.fuentes} /> · FCF: <AssumptionSources fuentes={marginAssumption?.fuentes} />
            </p>
          </div>
          <div className="rounded-md border border-gray-800 p-3 text-sm">
            <div className="text-xs font-semibold uppercase text-gray-500">
              <GlossaryTerm k="reverse_dcf" icon={false}>
                Reverse DCF
              </GlossaryTerm>
            </div>
            <p className="mt-2 text-gray-300">
              {model.reverse_dcf.status === 'ok'
                ? `El precio actual exige ${percentage(model.reverse_dcf.required_revenue_growth)} de crecimiento; la base asume ${percentage(model.reverse_dcf.base_revenue_growth)}${model.reverse_dcf.fcf_margin != null ? `, con margen FCF normalizado ${percentage(model.reverse_dcf.fcf_margin)}` : ''}.`
                : `No disponible: ${(model.reverse_dcf.missing_inputs ?? []).map(termLabel).join(', ') || 'faltan inputs de mercado o financieros'}.`}
            </p>
            <p className="mt-2 text-xs leading-5 text-gray-500">
              El reverse DCF parte del precio de mercado y calcula qué crecimiento está descontando ya.
            </p>
            <ImpliedGrowthDetail reverse={model.reverse_dcf} />
          </div>
        </div>
      </div>

      <div className="mt-5 grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
        <div className="rounded-md border border-gray-800 p-3 text-sm">
          <div className="text-xs font-semibold uppercase text-gray-500">Calidad del crecimiento</div>
          <div className="mt-2 text-xl font-semibold capitalize text-gray-200">{translate(QUALITY_LABELS, model.quality_of_growth.quality)}</div>
          <p className="mt-2 text-gray-400">CAGR de ingresos {percentage(model.quality_of_growth.revenue_cagr.value)} · cambio de margen FCF {percentage(model.quality_of_growth.fcf_margin_change.value)}</p>
          <p className="mt-2 text-xs leading-5 text-gray-500">{translate(PROSE_ES, model.quality_of_growth.conclusion, model.quality_of_growth.conclusion)}</p>
        </div>
        <div className="rounded-md border border-gray-800 p-3 text-sm">
          <div className="text-xs font-semibold uppercase text-gray-500">Beneficio del propietario</div>
          <div className="mt-2 text-xl font-semibold text-gray-200">{compactNumber(model.owner_earnings.value)}</div>
          <p className="mt-2 text-xs leading-5 text-gray-500">{model.owner_earnings.status === 'ok' ? ownerEarningsFormulaLabel(model.owner_earnings.formula) : `Insuficiente: ${(model.owner_earnings.missing_inputs ?? []).map(termLabel).join(', ')}.`}</p>
        </div>
        <div className="rounded-md border border-gray-800 p-3 text-sm">
          <div className="text-xs font-semibold uppercase text-gray-500">Motor de oportunidad de mercado</div>
          <div className="mt-2 text-sm font-semibold text-gray-200">{frameworkLabel(model.framework.label)}</div>
          <p className="mt-2 text-gray-400">TAM top-down {compactNumber(model.market_opportunity.top_down.tam.value)} · bottom-up {compactNumber(model.market_opportunity.bottom_up.value)}</p>
          <p className="mt-2 text-gray-400">Restricción vinculante: {model.market_opportunity.constraints.binding_constraint ? termLabel(model.market_opportunity.constraints.binding_constraint) : 'desconocida'}</p>
          <p className="mt-2 text-xs leading-5 text-gray-500">
              {translate(VERDICT_LABELS, model.market_opportunity.verdict.label)} ·{' '}
              {model.market_opportunity.verdict.conclusion.startsWith('Base revenue uses') && model.market_opportunity.verdict.base_revenue_to_binding_capacity != null
                ? `El escenario base usa el ${formatPercent(model.market_opportunity.verdict.base_revenue_to_binding_capacity)} de la estimación de mercado/capacidad más restrictiva contrastada.`
                : model.market_opportunity.verdict.conclusion}
            </p>
        </div>
      </div>

      <div className="mt-5 grid gap-6 lg:grid-cols-2">
        <div>
          <div className="mb-3 text-xs font-semibold uppercase tracking-wide text-gray-500">Lo que debe cumplirse</div>
          <ul className="space-y-2 text-sm">
            {model.what_must_be_true.map((item) => (
              <li key={item.id} className="flex gap-2 text-gray-300">
                <CircleHelp aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0 text-amber-300" />
                <span><span className="block text-xs text-amber-300">{modelConditionState(item, waccHasSource(model.assumptions.wacc))}</span>{conditionInSpanish(item, model.market_opportunity?.constraints?.binding_constraint, waccHasSource(model.assumptions.wacc))}</span>
              </li>
            ))}
          </ul>
        </div>
        <div>
          <div className="mb-3 text-xs font-semibold uppercase tracking-wide text-gray-500">Cronología reciente de la empresa</div>
          <div className="space-y-2 text-sm">
            {model.timeline.slice(0, 4).map((event, index) => (
              <div key={`${event.date}-${event.title}-${index}`} className="rounded-md border border-gray-800 p-2">
                <div className="flex justify-between gap-3"><span className="font-medium text-gray-300">{event.title}</span><span className="text-xs text-gray-500">{event.date ? formatMarketDate(event.date.slice(0, 10)) : 's/d'}</span></div>
                <div className="mt-1 text-xs text-gray-500">{etiquetaTipoEvento(event.type)} · {event.source} · impacto {translate(IMPACT_LABELS, event.thesis_impact, event.thesis_impact)}</div>
              </div>
            ))}
            {!model.timeline.length ? <div className="text-sm text-gray-500">No hay eventos históricos almacenados.</div> : null}
          </div>
        </div>
      </div>

      <p className="mt-5 border-t border-gray-800 pt-3 text-xs leading-5 text-gray-500">
        Historial disponible: {model.historical_review.years_covered} {model.historical_review.years_covered === 1 ? 'año' : 'años'} ({model.historical_review.first_year ?? '—'}–{model.historical_review.last_year ?? '—'}), frente a los {model.horizon_years} años proyectados. Los números calculados conservan sus fact IDs; lo no disponible se muestra como unknown/insufficient_data.
      </p>
    </section>
  );
}

function expectationRows(reviews: ResearchExpectationReview[]): ExpectationRow[] {
  const year = new Date().getUTCFullYear();
  return reviews.map((review) => {
    const comparable = review.expected_value != null && review.actual_value != null && Number.isFinite(review.expected_value) && Number.isFinite(review.actual_value);
    return {
      id: review.id,
      year: review.fiscal_year,
      metric: expectationMetricLabel(review.metric),
      expected: compactNumber(review.expected_value),
      actual: compactNumber(review.actual_value),
      status: comparable ? reviewStatusLabel(review.status) : 'Sin comparación: falta dato',
      pending: !comparable && review.actual_value == null && review.fiscal_year >= year,
    };
  });
}

/**
 * «Contra tesis v3 · modelo v2». El servicio guarda el número de versión en
 * `metadata` al registrar la decisión; los `*_version_id` son claves internas
 * y no se muestran.
 */
export function journalVersionLabel(entry: Pick<ResearchDecisionJournalEntry, 'thesis_version_id' | 'model_version_id' | 'metadata'>): string {
  const number = (value: unknown) => (typeof value === 'number' && Number.isInteger(value) && value > 0 ? value : null);
  const part = (label: string, linked: string, id: number | null, version: number | null) =>
    version !== null ? `${label} v${version}` : id !== null ? `${label} ${linked}` : `sin ${label}`;
  return `Contra ${part('tesis', 'registrada', entry.thesis_version_id, number(entry.metadata?.thesis_version))} · ${part('modelo', 'registrado', entry.model_version_id, number(entry.metadata?.model_version))}`;
}

export function DecisionAndRealityPanel({
  ticker,
  decisions,
  reviews,
  trades = [],
}: {
  ticker: string;
  decisions: ResearchDecisionJournalEntry[];
  reviews: ResearchExpectationReview[];
  /** Compras/ventas del ticker (IBKR o manuales) que se pueden enlazar. */
  trades?: JournalTrade[];
}) {
  const selectClass = 'h-11 rounded-md border border-gray-700 bg-gray-900 px-3 text-base text-gray-200 sm:h-10 sm:text-sm';
  return (
    <section className="grid grid-cols-1 gap-6 lg:grid-cols-2">
      <div className="scroll-mt-24 rounded-lg border border-gray-800 bg-surface-1 p-5" id="diario-decisiones">
        <div className="mb-4 flex items-center gap-2">
          <GitBranch aria-hidden="true" className="h-5 w-5 text-teal-300" />
          <h2 className="text-lg font-semibold text-gray-100">Diario de decisiones</h2>
        </div>
        <MutationForm
          action={createResearchDecision.bind(null, ticker)}
          className="grid grid-cols-1 gap-3"
          resetOnSuccess
          successMessage="Decisión registrada contra la tesis vigente"
        >
          <select aria-label="Decisión" className="h-11 rounded-md border border-gray-700 bg-gray-900 px-3 text-base text-gray-200 sm:h-10 sm:text-sm" defaultValue="hold" name="decision">
            <option value="buy">Comprar</option>
            <option value="hold">Mantener</option>
            <option value="trim">Reducir</option>
            <option value="sell">Vender</option>
            <option value="watch">Vigilar</option>
            <option value="avoid">Evitar</option>
          </select>
          <Textarea aria-label="Motivo de la decisión" className="border-gray-700 bg-transparent text-gray-100" name="rationale" placeholder="Qué evidencia justifica esta decisión" required />
          <Textarea aria-label="Qué debe cumplirse" className="border-gray-700 bg-transparent text-gray-100" name="what_must_be_true" placeholder="Una condición verificable por línea" />
          {trades.length > 0 ? (
            <select aria-label="Operación ejecutada (opcional)" className={selectClass} defaultValue="" name="transaction_id">
              <option value="">Sin operación (solo la decisión)</option>
              {trades.map((trade) => (
                <option key={trade.id} value={trade.id}>{describeTrade(trade)}</option>
              ))}
            </select>
          ) : null}
          <Button type="submit">Registrar decisión</Button>
        </MutationForm>
        <div className="mt-5 space-y-3">
          {decisions.length === 0 ? (
            <p className="text-sm text-gray-500">Todavía no hay decisiones registradas.</p>
          ) : decisions.slice(0, 8).map((entry) => (
            <div className="rounded-md border border-gray-800 p-3" key={entry.id}>
              <div className="flex items-center justify-between gap-3">
                <Badge variant="outline">{translate(DECISION_LABELS, entry.decision, entry.decision)}</Badge>
                <span className="text-xs text-gray-500">{entry.decision_date}</span>
              </div>
              <p className="mt-2 text-sm text-gray-300">{entry.rationale}</p>
              <p className="mt-2 text-xs text-gray-500">{journalVersionLabel(entry)}</p>
              {entry.transaction ? (
                <div className="mt-2 rounded border border-teal-900/50 bg-teal-950/10 p-2 text-xs leading-5 text-gray-300">
                  <p><span className="text-teal-300">Operación:</span> {describeTrade(entry.transaction)}</p>
                  {isAutoLinked(entry.metadata) ? (
                    <div className="text-amber-200" data-testid="journal-auto-link-badge">
                      <Badge variant="outline">Enlace detectado automáticamente</Badge>{' '}
                      Coincide en empresa, sentido y fecha (hasta 3 días después), sin otra candidata. No confirma cantidad ni cuenta: corrígelo si no es esa operación.
                    </div>
                  ) : <p className="text-teal-300" data-testid="journal-confirmed-link">Enlace confirmado manualmente</p>}
                  <p className="text-gray-400" title="Margen = valor justo / precio de ejecución − 1">{describeFairValue(entry.fair_value_on_day)}</p>
                  <MutationForm action={linkResearchDecisionTrade.bind(null, ticker, entry.id)} className="mt-1" successMessage="Operación desenlazada">
                    <input name="transaction_id" type="hidden" value="" />
                    <button className="text-gray-500 underline hover:text-gray-300" type="submit">{isAutoLinked(entry.metadata) ? 'Corregir / desenlazar' : 'Desenlazar'}</button>
                  </MutationForm>
                </div>
              ) : trades.length > 0 ? (
                <MutationForm action={linkResearchDecisionTrade.bind(null, ticker, entry.id)} className="mt-2 flex flex-wrap items-center gap-2" successMessage="Decisión enlazada a la operación">
                  {ambiguousCandidateIds(entry.metadata) && tradesForEntry(trades, entry.metadata).length === 0 ? (
                    <p className="w-full text-xs leading-5 text-amber-200" data-testid="journal-unavailable-link" role="status">
                      Las operaciones sugeridas ya no están disponibles; no se ha enlazado ninguna.
                    </p>
                  ) : isSuggested(entry.metadata) ? (
                    <p className="w-full text-xs leading-5 text-amber-200" data-testid="journal-suggested-link" role="status">
                      Sugerencia sin confirmar: una operación coincide en empresa, sentido y fecha (hasta 3 días después). No se conoce cantidad ni cuenta, así que no se ha enlazado. Confírmala o deja la decisión sin operación.
                    </p>
                  ) : ambiguousCandidateIds(entry.metadata) ? (
                    <p className="w-full text-xs leading-5 text-amber-200" data-testid="journal-ambiguous-link" role="status">
                      Hay varias operaciones posibles para esta decisión y no se ha enlazado ninguna sola. Elige cuál la ejecutó, o deja la decisión sin operación.
                    </p>
                  ) : null}
                  {tradesForEntry(trades, entry.metadata).length > 0 ? (
                    <>
                  <select aria-label="Enlazar a una operación" className={`${selectClass} h-8 text-xs`} defaultValue="" name="transaction_id" required>
                    <option disabled value="">Enlazar a una operación…</option>
                    {tradesForEntry(trades, entry.metadata).map((trade) => (
                      <option key={trade.id} value={trade.id}>{describeTrade(trade)}</option>
                    ))}
                  </select>
                  <Button size="sm" type="submit" variant="outline">{isSuggested(entry.metadata) ? 'Confirmar enlace' : 'Enlazar'}</Button>
                    </>
                  ) : null}
                </MutationForm>
              ) : null}
              {!entry.transaction && (entry.metadata?.auto_link as { status?: unknown } | undefined)?.status === 'user_unlinked' ? (
                <p className="mt-2 text-xs text-gray-400" data-testid="journal-no-operation">Sin operación por elección del usuario. No se enlazará automáticamente.</p>
              ) : null}
              {!entry.transaction && ambiguousCandidateIds(entry.metadata) ? (
                <MutationForm action={linkResearchDecisionTrade.bind(null, ticker, entry.id)} className="mt-1" successMessage="Decisión marcada sin operación">
                  <input name="transaction_id" type="hidden" value="" />
                  <button className="text-gray-500 underline hover:text-gray-300" type="submit">No enlazar (sin operación)</button>
                </MutationForm>
              ) : null}
            </div>
          ))}
        </div>
      </div>

      <div className="rounded-lg border border-gray-800 bg-surface-1 p-5">
        <div className="mb-4 flex items-center gap-2">
          <BarChart3 aria-hidden="true" className="h-5 w-5 text-teal-300" />
          <h2 className="text-lg font-semibold text-gray-100">Expectativa vs realidad</h2>
          <MutationForm action={reviewResearchExpectations.bind(null, ticker)} className="ml-auto" successMessage="Forecasts comparados con los hechos disponibles">
            <Button size="sm" type="submit" variant="outline">Comparar ahora</Button>
          </MutationForm>
        </div>
        {reviews.length === 0 ? (
          <p className="text-sm text-gray-500">Sin comparaciones persistidas. Solo se pueden contrastar previsiones que tengan datos esperados y reales.</p>
        ) : (
          <ExpectationsList rows={expectationRows(reviews)} />
        )}
      </div>
    </section>
  );
}

function AssumptionSources({ fuentes }: { fuentes?: Array<{ fact_id: number; titulo: string | null; url: string | null; fecha: string | null }> }) {
  if (!fuentes || fuentes.length === 0) return <>sin fuente</>;
  return (
    <>
      {fuentes.map((fuente, index) => (
        <span key={fuente.fact_id}>
          {index > 0 ? ', ' : ''}
          {fuente.url && /^https:\/\//.test(fuente.url) ? (
            <a href={fuente.url} target="_blank" rel="noopener noreferrer" className="text-teal-400 underline">
              {fuente.titulo ?? 'Fuente oficial'}
            </a>
          ) : (
            (fuente.titulo ?? 'Fuente oficial')
          )}
          {fuente.fecha ? ` (${fuente.fecha})` : ''}
        </span>
      ))}
    </>
  );
}


/** Candidatas detectadas, sin confirmación del usuario. */
function ambiguousCandidateIds(metadata: Record<string, unknown> | undefined): number[] | null {
  const link = metadata?.auto_link as { status?: unknown; candidate_transaction_ids?: unknown } | undefined;
  const sug = metadata?.auto_link as { status?: unknown; candidate_transaction_id?: unknown } | undefined;
  if (sug?.status === 'suggested' && typeof sug.candidate_transaction_id === 'number') return [sug.candidate_transaction_id];
  if (!link || link.status !== 'ambiguous' || !Array.isArray(link.candidate_transaction_ids)) return null;
  const ids = link.candidate_transaction_ids.filter((id): id is number => typeof id === 'number');
  return ids;
}

/** Con ambigüedad, el selector ofrece SOLO las candidatas que siguen existiendo (puede quedar vacío); nunca todas. */
function tradesForEntry(trades: JournalTrade[], metadata: Record<string, unknown> | undefined): JournalTrade[] {
  const ids = ambiguousCandidateIds(metadata);
  if (!ids) return trades;
  const subset = trades.filter((trade) => ids.includes(trade.id));
  return subset;
}

function isAutoLinked(metadata: Record<string, unknown> | undefined): boolean {
  const link = metadata?.auto_link as { status?: unknown } | undefined;
  return link?.status === 'linked';
}

function isSuggested(metadata: Record<string, unknown> | undefined): boolean {
  return (metadata?.auto_link as { status?: unknown } | undefined)?.status === 'suggested';
}

function ImpliedGrowthDetail({ reverse }: { reverse: Parameters<typeof impliedGrowthView>[0] }) {
  const view = impliedGrowthView(reverse);
  if (!view.perpetual && !view.split.length && !view.grid) return null;
  return (
    <div className="mt-3 space-y-3 border-t border-gray-800 pt-3" data-testid="implied-growth">
      <div className="text-xs font-semibold uppercase text-gray-500">Crecimiento implícito</div>
      {view.perpetual ? <p className="text-gray-300">A este precio, el mercado descuenta un crecimiento perpetuo del flujo de caja de {view.perpetual} (WACC − FCF / valor empresa).</p> : null}
      {view.split.length ? (
        <div>
          <p className="text-xs text-gray-500">De dónde sale el valor que pagas hoy</p>
          <ul className="mt-1 space-y-1">
            {view.split.map((part) => (
              <li key={part.label} className="flex items-center gap-2 text-xs">
                <span className="w-32 shrink-0 text-gray-400">{part.label}</span>
                <span className="h-2 flex-1 rounded bg-gray-800"><span className="block h-2 rounded bg-teal-400/60" style={{ width: `${part.width}%` }} /></span>
                <span className="w-10 text-right tabular-nums text-gray-200">{part.share}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {view.grid ? (
        <div className="overflow-x-auto">
          <p className="text-xs text-gray-500">Crecimiento exigido si cambian el WACC o el margen</p>
          <table className="mt-1 w-full text-xs tabular-nums">
            <thead><tr><th className="text-left font-normal text-gray-500" scope="col"><span className="sr-only">WACC</span></th>{view.grid.columns.map((column) => <th key={column} scope="col" className="px-1 text-right font-normal text-gray-500">{column}</th>)}</tr></thead>
            <tbody>
              {view.grid.rows.map((row) => (
                <tr key={row.label}>
                  <th scope="row" className="text-left font-normal text-gray-400">{row.label}</th>
                  {row.cells.map((cell, index) => <td key={index} className={`px-1 text-right ${cell.base ? 'font-semibold text-teal-300' : 'text-gray-300'}`}>{cell.text}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}
