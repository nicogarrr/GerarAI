import { Panel } from '@/components/ui/panel';
import { NA } from '@/lib/format';
import { formatScenarioMoney, scenarioCurrency } from '@/lib/research/scenario-format';
import type { ScenarioKey, ScenarioMetric, ThesisScenarios } from '@/lib/actions/thesis-scenarios.actions';

const KEYS: ScenarioKey[] = ['bear', 'base', 'bull'];
const METRICS: { key: ScenarioMetric; label: string; digits: number }[] = [
  { key: 'ingresos', label: 'Ingresos', digits: 1 },
  { key: 'fcf', label: 'Flujo de caja libre', digits: 1 },
  { key: 'bps', label: 'Beneficio por acción', digits: 2 },
];

export function ThesisScenariosPanel({
  data,
  currency,
  adrRatio,
}: {
  data: ThesisScenarios | null;
  currency: string | null | undefined;
  adrRatio: number | null | undefined;
}) {
  const money = scenarioCurrency(currency, adrRatio);
  if (!data || data.estado !== 'persistido') return null;
  const years = Array.from(
    new Set(KEYS.flatMap((key) => data.escenarios[key].proyecciones.map((row) => row.ejercicio))),
  ).sort((a, b) => a - b);
  if (!years.length) return null;
  return (
    <Panel title="Escenarios a 5 años">
      <div className="space-y-4">
        {METRICS.map((metric) => (
          <div className="overflow-x-auto" key={metric.key}>
            <table className="w-full min-w-[360px] text-left text-sm">
              <caption className="pb-1 text-left text-xs font-medium uppercase text-gray-500">{metric.label}</caption>
              <thead className="text-xs text-gray-500">
                <tr>
                  <th className="border-b border-gray-800 py-1" scope="col">Ejercicio</th>
                  {KEYS.map((key) => (
                    <th className="border-b border-gray-800 px-3 py-1 text-right" key={key} scope="col">{data.escenarios[key].nombre}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {years.map((year) => (
                  <tr className="border-b border-gray-900 last:border-0" key={year}>
                    <th className="py-1 font-normal text-gray-400" scope="row">{year}</th>
                    {KEYS.map((key) => {
                      const cell = data.escenarios[key].proyecciones.find((row) => row.ejercicio === year)?.[metric.key];
                      const text = formatScenarioMoney(cell?.valor ?? null, money, metric.digits);
                      const reason = cell?.motivo ?? (cell?.valor != null && !text ? 'Divisa del emisor no verificada.' : null);
                      return (
                        <td className="px-3 py-1 text-right tabular-nums text-gray-200" key={key} title={reason ?? undefined}>
                          {text ?? (cell?.etiqueta && cell.etiqueta !== 'INFERIDO' ? cell.etiqueta : NA)}
                          {reason ? <span className="sr-only"> {reason}</span> : null}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
      </div>
      {data.aviso_coherencia ? <p className="mt-3 text-xs text-amber-300">{data.aviso_coherencia}</p> : null}
      <p className="mt-3 text-xs text-gray-500">
        Proyección del modelo {data.fuente.modelo ?? NA} v{data.fuente.version ?? NA}, corte {data.fuente.fecha ?? NA}.
      </p>
    </Panel>
  );
}
