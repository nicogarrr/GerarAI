import type {
  PortfolioForecast,
  PortfolioForecastExcluded,
} from '@/lib/actions/portfolio.actions';
import Link from 'next/link';
import { formatMarketDate, formatCountEs } from '@/lib/format';
import { Panel } from '@/components/ui/panel';

const SCENARIO_LABELS: Record<string, string> = {
  bear: 'Bajista',
  base: 'Base',
  bull: 'Alcista',
};

function fmtNumber(digits: number) {
  return new Intl.NumberFormat('es-ES', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function pct(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return 'N/D';
  return `${fmtNumber(digits).format(value * 100)}%`;
}

function signedPct(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return 'N/D';
  const rendered = fmtNumber(digits).format(value * 100);
  return value > 0 ? `+${rendered}%` : `${rendered}%`;
}

function Veracity({ value }: { value: string }) {
  if (value === 'OFICIAL') {
    return <span className="text-gray-500">{value}</span>;
  }
  return <span className="text-amber-400">{value}</span>;
}

function ExcludedList({ items }: { items: PortfolioForecastExcluded[] }) {
  return (
    <div className="rounded-lg border border-amber-900/70 bg-amber-950/20 p-3">
      <p className="text-sm font-medium text-amber-200">Excluidas del cálculo:</p>
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
              ? 'peso N/D (divisa sin conversión)'
              : `${pct(item.weight)} de la cartera`}
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
export default function PortfolioForecast({ forecast }: { forecast: PortfolioForecast }) {
  const portfolio = forecast.portfolio;
  if (!portfolio) {
    // Sin agregado: el MOTIVO lo da siempre el backend en assumptions
    // (vacio real, monedas base mezcladas, todo FX N/D...). Nunca se infiere
    // por arrays vacios: se muestra su razón verbatim y las excluidas.
    return (
      <Panel title="Hipótesis de convergencia">
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
              N/D: no hay agregado ni motivo disponible.
            </p>
          )}
          {forecast.excluded.length > 0 ? <ExcludedList items={forecast.excluded} /> : null}
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
      <Panel title="Previsión">
        <p className="text-sm text-gray-200">
          {heaviest ? (
            <>
              Publica la tesis de{' '}
              <Link
                href={`/research/${encodeURIComponent(heaviest.ticker)}?view=thesis`}
                className="font-medium text-teal-300 underline-offset-2 hover:text-teal-200 hover:underline"
              >
                {heaviest.ticker}
              </Link>{' '}
              ({pct(heaviest.weight)} de la cartera) para activar la previsión.
            </>
          ) : (
            'Publica la tesis de alguna posición para activar la previsión.'
          )}
        </p>
        <p className="mt-1 text-xs text-gray-500">
          {noThesis.length} de {formatCountEs(portfolio.position_count, 'posición', 'posiciones')} sin tesis publicada vigente (un borrador no cuenta)
          {others > 0 ? `; ${others} sin comparación verificada por otro motivo (ver detalle)` : ''}.
        </p>
        {others > 0 ? <ExcludedList items={forecast.excluded.filter((item) => item.reason_code !== 'no_published_thesis')} /> : null}
      </Panel>
    );
  }
  const scenarioOrder = ['bear', 'base', 'bull'] as const;
  return (
    <div className="space-y-6">
      <p className="text-xs text-gray-500">
        Contribución anual del subset valorado. No es la rentabilidad total de la cartera.
      </p>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {scenarioOrder.map((key) => {
          const scenario = portfolio.scenarios?.[key];
          return (
            <div className="rounded-lg border border-gray-800 p-4" key={key}>
              <p className="text-xs uppercase tracking-wide text-gray-500">{SCENARIO_LABELS[key]}</p>
              <p className="mt-1 text-2xl font-semibold text-gray-100">
                {scenario ? signedPct(scenario.contribution_cagr) : 'N/D'}
              </p>
              <p className="mt-1 text-xs text-gray-500">
                Contribución anual · aporte total {scenario ? signedPct(scenario.contribution_total_return) : 'N/D'}
              </p>
              <p className="mt-1 text-xs text-gray-500">
                {scenario
                  ? `Cobertura ${pct(scenario.coverage)} de la cartera valorada`
                  : 'N/D'}
                {scenario?.horizon_scope === 'mixed' ? ' · horizontes mezclados (proxy anual)' : ''}
              </p>
            </div>
          );
        })}
        <div className="rounded-lg border border-teal-900/60 bg-teal-950/20 p-4">
          <p className="text-xs uppercase tracking-wide text-teal-300">Esperado del CAGR</p>
          <p className="mt-1 text-2xl font-semibold text-teal-100">
            {signedPct(portfolio.expected_cagr)}
          </p>
          <p className="mt-1 text-xs text-gray-500">
            {portfolio.expected_cagr !== null
              ? 'Media de los CAGR por escenario, ponderada por probabilidad.'
              : 'Sin cobertura completa de la cartera valorada: abajo van los esperados parciales.'}
          </p>
        </div>
      </div>
      <Panel
        title="Por posición"
        description={`Cobertura: ${portfolio.covered_weight !== null ? pct(portfolio.covered_weight) : 'N/D (hay posiciones sin conversión; pesos sobre el subset valorado)'} de la cartera con tesis computable (${portfolio.covered_count} de ${formatCountEs(portfolio.position_count, 'posición', 'posiciones')}).`}
      >
        <div className="overflow-x-auto" role="region" aria-label="Contribuciones por posición" tabIndex={0}>
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-gray-800 text-xs uppercase tracking-wide text-gray-500">
                <th className="py-2 pr-4">Posición</th>
                <th className="py-2 pr-4">Peso</th>
                <th className="py-2 pr-4">Oso</th>
                <th className="py-2 pr-4">Base</th>
                <th className="py-2 pr-4">Toro</th>
                <th className="py-2 pr-4">Esperado del CAGR</th>
                <th className="py-2">Base del cálculo</th>
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
                    {pct(item.weight)}
                    {item.weight_scope === 'valued_subset' ? (
                      <span className="block text-xs text-amber-400/80">sobre subset valorado</span>
                    ) : null}
                  </td>
                  <td className="py-2 pr-4">{signedPct(item.cagr.bear)}</td>
                  <td className="py-2 pr-4">{signedPct(item.cagr.base)}</td>
                  <td className="py-2 pr-4">{signedPct(item.cagr.bull)}</td>
                  <td className="py-2 pr-4">
                    {item.expected_cagr !== null
                      ? signedPct(item.expected_cagr)
                      : item.partial_expected_cagr !== null
                        ? `Parcial ${signedPct(item.partial_expected_cagr)} · masa ${pct(item.probability_mass, 0)}`
                        : 'N/D'}
                  </td>
                  <td className="py-2 text-xs text-gray-500">
                    Precio {item.price_source} · <Veracity value={item.price_veracity} /> · {formatMarketDate(item.price_as_of)} · tesis v{item.thesis_version} ({item.thesis_status})
                    {item.model_version !== null ? ` · modelo v${item.model_version}` : ''} · {formatCountEs(item.horizon_years, 'año', 'años')}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {forecast.excluded.length > 0 ? (
          <div className="mt-4">
            <ExcludedList items={forecast.excluded} />
          </div>
        ) : null}
      </Panel>
      <Panel title="Supuestos" density="compact">
        <AssumptionList items={forecast.assumptions} />
      </Panel>
    </div>
  );
}
