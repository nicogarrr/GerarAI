import { t, type TranslationKey, type TranslationVars } from '@/lib/i18n/t';

type TiFn = (key: TranslationKey, vars?: TranslationVars) => string;
/** Fallback español sin RequestScope (tests y render directo). */
const esT: TiFn = t;

/**
 * Supuestos visibles de los escenarios bear/base/bull.
 *
 * Los spreads son los reales del motor (long_term_model_service.py:
 * bear/bull con ±spread de crecimiento y margen, WACC +2pp/−1pp; el
 * standard_dcf.py usa la misma parrilla ±8pp crecimiento, ±6pp margen).
 * Se muestra dentro de un <details> para no saturar la vista principal.
 */
export default function ScenarioAssumptions({ ti = esT }: { ti?: TiFn }) {
  return (
    <details className="mt-3 rounded-lg border border-gray-800 bg-black/20 px-4 py-3 text-sm">
      <summary className="cursor-pointer text-xs font-semibold uppercase tracking-wide text-gray-400">
        {ti('research.scenarioHelp.title')}
      </summary>
      <div className="mt-3 space-y-2 text-xs leading-5 text-gray-400">
        <p>
          <span className="font-semibold text-gray-300">Bear:</span> {ti('research.scenarioHelp.bear')}
        </p>
        <p>
          <span className="font-semibold text-gray-300">Base:</span> {ti('research.scenarioHelp.base')}
        </p>
        <p>
          <span className="font-semibold text-gray-300">Bull:</span> {ti('research.scenarioHelp.bull')}
        </p>
        <p className="border-t border-gray-800 pt-2 text-gray-500">
          {ti('research.scenarioHelp.note')}
        </p>
      </div>
    </details>
  );
}
