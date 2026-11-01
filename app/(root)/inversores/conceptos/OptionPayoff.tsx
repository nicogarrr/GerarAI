/** Ejemplo didáctico, no cotizaciones reales. Resultado por acción al vencimiento. */
import { getT } from "@/lib/i18n/server";

export async function OptionPayoff() {
  const t = await getT();
  return (
    <section
      aria-label={t('investors.payoff.aria')}
      className="flex flex-col gap-4 rounded-2xl border border-gray-800 bg-surface-1 p-5"
    >
      <h2 className="text-lg font-medium text-gray-100">
        {t('investors.payoff.title')}
      </h2>
      <p className="text-sm text-gray-400">
        {t('investors.payoff.terms')}
      </p>
      <svg
        role="img"
        aria-labelledby="payoff-title payoff-desc"
        viewBox="0 0 440 240"
        className="w-full max-w-xl"
      >
        <title id="payoff-title">{t('investors.payoff.chartTitle')}</title>
        <desc id="payoff-desc">{t('investors.payoff.chartDesc')}</desc>
        <line x1="50" y1="145" x2="410" y2="145" stroke="#6b7280" />
        <line x1="50" y1="25" x2="50" y2="190" stroke="#6b7280" />
        <g fill="#9ca3af" fontSize="12">
          <text x="8" y="39">
            +$15
          </text>
          <text x="16" y="149">
            $0
          </text>
          <text x="12" y="184">
            -$5
          </text>
          <text x="40" y="208">
            $80
          </text>
          <text x="215" y="208">
            $100
          </text>
          <text x="391" y="208">
            $120
          </text>
          <text x="145" y="231">
            {t('investors.payoff.axis')}
          </text>
        </g>
        <polyline
          points="50,180 230,180 410,35"
          fill="none"
          stroke="#bef264"
          strokeWidth="3"
        />
        <polyline
          points="50,35 230,180 410,180"
          fill="none"
          stroke="#60a5fa"
          strokeWidth="3"
          strokeDasharray="6 4"
        />
        <g fontSize="13">
          <text x="290" y="40" fill="#bef264">
            {t('investors.payoff.longCall')}
          </text>
          <text x="65" y="24" fill="#60a5fa">
            {t('investors.payoff.longPut')}
          </text>
        </g>
      </svg>
      <p className="text-xs text-gray-500">
        {t('investors.payoff.formula')}
      </p>
    </section>
  );
}
