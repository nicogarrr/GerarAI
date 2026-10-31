import type {
  PortfolioForecast,
  PortfolioForecastExcluded,
} from '@/lib/actions/portfolio.actions';
import Link from 'next/link';
import { Panel } from '@/components/ui/panel';
import type { TranslateFn as TFunction } from '@/lib/i18n/translate';
import { createFormatters, type Formatters } from '@/lib/format';
import { intlLocale } from '@/lib/i18n/locale';
import { t } from '@/lib/i18n/t';

const esT: TFunction = t;
const esF = createFormatters('es');

const SCENARIO_KEYS = {
  bear: 'portfolio.forecast.scenarioBear',
  base: 'portfolio.forecast.scenarioBase',
  bull: 'portfolio.forecast.scenarioBull',
} as const;

function fmtNumber(digits: number, f: Formatters) {
  return new Intl.NumberFormat(intlLocale(f.locale), {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function pct(value: number | null | undefined, digits = 1, ti: TFunction = esT, f: Formatters = esF): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return ti('common.na');
  return `${fmtNumber(digits, f).format(value * 100)}%`;
}

function signedPct(value: number | null | undefined, digits = 1, ti: TFunction = esT, f: Formatters = esF): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return ti('common.na');
  const rendered = fmtNumber(digits, f).format(value * 100);
  return value > 0 ? `+${rendered}%` : `${rendered}%`;
}

function Veracity({ value }: { value: string }) {
  if (value === 'OFICIAL') {
    return <span className="text-gray-500">{value}</span>;
  }
  return <span className="text-amber-400">{value}</span>;
}

function ExcludedList({ items, ti = esT, f = esF }: { items: PortfolioForecastExcluded[]; ti?: TFunction; f?: Formatters }) {
  return (
    <div className="rounded-lg border border-amber-900/70 bg-amber-950/20 p-3">
      <p className="text-sm font-medium text-amber-200">{ti('portfolio.forecast.excludedTitle')}</p>
      <ul className="mt-1 space-y-1 text-sm text-amber-100/80">
        {items.map((item) => (
          <li key={item.ticker}>
            <Link
              href={`/research/${encodeURIComponent(item.ticker)}?view=thesis`}
              className="font-medium text-teal-300 underline-offset-2 hover:text-teal-200 hover:underline"
            >
              {item.ticker}
            </Link>{' '}
            —{' '}
            {item.weight === null
              ? ti('portfolio.forecast.weightNa')
              : ti('portfolio.forecast.weightPct', { pct: pct(item.weight, 1, ti, f) })}
            . {item.reason}
          </li>
        ))}
      </ul>
    </div>
  );
}

function AssumptionList({ items }: { items: string[] }) {
  return (
    <ul className="list-disc space-y-1 pl-5 text-xs leading-5 text-gray-500">
      {items.map((assumption) => (
        <li key={assumption}>{assumption}</li>
      ))}
    </ul>
  );
}

/**
 * Hipótesis de convergencia: proxy anual de cuánto aporta cada posición si su
 * tesis converge al valor intrínseco en su propio horizonte. NO es una
 * previsión de rentabilidad de la cartera: son contribuciones ponderadas del
 * subset valorado. Toda cifra viene del endpoint determinista
 * /api/portfolio/forecast; la veracidad del precio se rotula por fila
 * (OFICIAL / MANUAL / NO VERIFICADA, con fuente y fecha) y los valores
 * intrínsecos son INFERIDOS (tesis/modelo vigente, versión visible). Lo que no
 * entra en el cálculo se lista aparte con su motivo; nunca se inventa un cero.
 */
export default function PortfolioForecast({ forecast, ti = esT, f = esF }: { forecast: PortfolioForecast; ti?: TFunction; f?: Formatters }) {
  const portfolio = forecast.portfolio;
  const positionsText = (n: number) => (n === 1 ? ti('portfolio.forecast.positionOne') : ti('portfolio.forecast.positionMany', { n }));
  const yearsText = (n: number) => (n === 1 ? ti('portfolio.forecast.yearOne') : ti('portfolio.forecast.yearMany', { n }));
  if (!portfolio) {
    // Sin agregado: el MOTIVO lo da siempre el backend en assumptions
    // (vacio real, monedas base mezcladas, todo FX N/D...). Nunca se infiere
    // por arrays vacios: se muestra su razón verbatim y las excluidas.
    return (
      <Panel title={ti('portfolio.forecast.panelTitleConvergence')}>
        <div className="space-y-3">
          {forecast.assumptions.length > 0 ? (
            <div className="rounded-lg border border-amber-900/70 bg-amber-950/20 p-3">
              {forecast.assumptions.map((assumption) => (
                <p className="text-sm text-amber-100/90" key={assumption}>
                  {assumption}
                </p>
              ))}
            </div>
          ) : (
            <p className="text-sm text-gray-400">
              {ti('portfolio.forecast.noAggregate')}
            </p>
          )}
          {forecast.excluded.length > 0 ? <ExcludedList items={forecast.excluded} ti={ti} f={f} /> : null}
        </div>
      </Panel>
    );
  }
  const noThesis = forecast.excluded.filter((item) => item.reason_code === 'no_published_thesis');
  if (portfolio.covered_count === 0 && noThesis.length > 0) {
    // Solo se afirma "falta la tesis" para las posiciones cuyo motivo es ese
    // (código de motivo del backend). El resto se declara aparte, sin causa asumida.
    const heaviest = [...noThesis]
      .filter((item) => item.weight !== null)
      .sort((a, b) => (b.weight as number) - (a.weight as number))[0];
    const others = forecast.excluded.length - noThesis.length;
    return (
      <Panel title={ti('portfolio.forecast.panelTitleForecast')}>
        <p className="text-sm text-gray-200">
          {heaviest ? (
            <>
              {ti('portfolio.forecast.activateHeaviestPre')}
              <Link
                href={`/research/${encodeURIComponent(heaviest.ticker)}?view=thesis`}
                className="font-medium text-teal-300 underline-offset-2 hover:text-teal-200 hover:underline"
              >
                {heaviest.ticker}
              </Link>{' '}
              {ti('portfolio.forecast.activateHeaviestPost', { pct: pct(heaviest.weight, 1, ti, f) })}
            </>
          ) : (
            ti('portfolio.forecast.activateGeneric')
          )}
        </p>
        <p className="mt-1 text-xs text-gray-500">
          {ti('portfolio.forecast.noThesisLine', { missing: noThesis.length, count: positionsText(portfolio.position_count) })}
          {others > 0 ? ti('portfolio.forecast.othersSuffix', { others }) : ''}.
        </p>
        {others > 0 ? <ExcludedList items={forecast.excluded.filter((item) => item.reason_code !== 'no_published_thesis')} ti={ti} f={f} /> : null}
      </Panel>
    );
  }
  const scenarioOrder = ['bear', 'base', 'bull'] as const;
  return (
    <div className="space-y-6">
      <p className="text-xs text-gray-500">
        {ti('portfolio.forecast.intro')}
      </p>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {scenarioOrder.map((key) => {
          const scenario = portfolio.scenarios?.[key];
          return (
            <div className="rounded-lg border border-gray-800 p-4" key={key}>
              <p className="text-xs uppercase tracking-wide text-gray-500">{ti(SCENARIO_KEYS[key])}</p>
              <p className="mt-1 text-2xl font-semibold text-gray-100">
                {scenario ? signedPct(scenario.contribution_cagr, 1, ti, f) : ti('common.na')}
              </p>
              <p className="mt-1 text-xs text-gray-500">
                {ti('portfolio.forecast.contributionLine', { pct: scenario ? signedPct(scenario.contribution_total_return, 1, ti, f) : ti('common.na') })}
              </p>
              <p className="mt-1 text-xs text-gray-500">
                {scenario
                  ? ti('portfolio.forecast.coverageLine', { pct: pct(scenario.coverage, 1, ti, f) })
                  : ti('common.na')}
                {scenario?.horizon_scope === 'mixed' ? ti('portfolio.forecast.mixedHorizons') : ''}
              </p>
            </div>
          );
        })}
        <div className="rounded-lg border border-teal-900/60 bg-teal-950/20 p-4">
          <p className="text-xs uppercase tracking-wide text-teal-300">{ti('portfolio.forecast.expectedTitle')}</p>
          <p className="mt-1 text-2xl font-semibold text-teal-100">
            {signedPct(portfolio.expected_cagr, 1, ti, f)}
          </p>
          <p className="mt-1 text-xs text-gray-500">
            {portfolio.expected_cagr !== null
              ? ti('portfolio.forecast.expectedNoteFull')
              : ti('portfolio.forecast.expectedNotePartial')}
          </p>
        </div>
      </div>
      <Panel
        title={ti('portfolio.forecast.perPositionTitle')}
        description={ti('portfolio.forecast.perPositionDesc', {
          weight: portfolio.covered_weight !== null ? pct(portfolio.covered_weight, 1, ti, f) : ti('portfolio.forecast.coverageNa'),
          covered: portfolio.covered_count,
          count: positionsText(portfolio.position_count),
        })}
      >
        <div className="overflow-x-auto" role="region" aria-label={ti('portfolio.forecast.region')} tabIndex={0}>
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-gray-800 text-xs uppercase tracking-wide text-gray-500">
                <th className="py-2 pr-4">{ti('portfolio.forecast.thPosition')}</th>
                <th className="py-2 pr-4">{ti('portfolio.forecast.thWeight')}</th>
                <th className="py-2 pr-4">{ti('portfolio.forecast.thBear')}</th>
                <th className="py-2 pr-4">{ti('portfolio.forecast.thBase')}</th>
                <th className="py-2 pr-4">{ti('portfolio.forecast.thBull')}</th>
                <th className="py-2 pr-4">{ti('portfolio.forecast.thExpected')}</th>
                <th className="py-2">{ti('portfolio.forecast.thBasis')}</th>
              </tr>
            </thead>
            <tbody>
              {forecast.positions.map((item) => (
                <tr className="border-b border-gray-900 text-gray-300" key={item.ticker}>
                  <td className="py-2 pr-4 font-medium">
                    <Link
                      href={`/research/${encodeURIComponent(item.ticker)}?view=thesis`}
                      className="text-teal-300 underline-offset-2 hover:text-teal-200 hover:underline"
                    >
                      {item.ticker}
                    </Link>
                  </td>
                  <td className="py-2 pr-4">
                    {pct(item.weight, 1, ti, f)}
                    {item.weight_scope === 'valued_subset' ? (
                      <span className="block text-xs text-amber-400/80">{ti('portfolio.forecast.valuedSubset')}</span>
                    ) : null}
                  </td>
                  <td className="py-2 pr-4">{signedPct(item.cagr.bear, 1, ti, f)}</td>
                  <td className="py-2 pr-4">{signedPct(item.cagr.base, 1, ti, f)}</td>
                  <td className="py-2 pr-4">{signedPct(item.cagr.bull, 1, ti, f)}</td>
                  <td className="py-2 pr-4">
                    {item.expected_cagr !== null
                      ? signedPct(item.expected_cagr)
                      : item.partial_expected_cagr !== null
                        ? ti('portfolio.forecast.partialExpected', { pct: signedPct(item.partial_expected_cagr, 1, ti, f), mass: pct(item.probability_mass, 0, ti, f) })
                        : ti('common.na')}
                  </td>
                  <td className="py-2 text-xs text-gray-500">
                    {ti('portfolio.forecast.basisPrefix', { source: item.price_source })}<Veracity value={item.price_veracity} />{ti('portfolio.forecast.basisSuffix', { date: f.formatMarketDate(item.price_as_of), thesisVersion: item.thesis_version, thesisStatus: item.thesis_status ?? '' })}
                    {item.model_version !== null ? ti('portfolio.forecast.modelSuffix', { version: item.model_version }) : ''} · {yearsText(item.horizon_years)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {forecast.excluded.length > 0 ? (
          <div className="mt-4">
            <ExcludedList items={forecast.excluded} ti={ti} f={f} />
          </div>
        ) : null}
      </Panel>
      <Panel title={ti('portfolio.forecast.assumptionsTitle')} density="compact">
        <AssumptionList items={forecast.assumptions} />
      </Panel>
    </div>
  );
}
