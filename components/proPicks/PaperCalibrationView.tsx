import type { PaperCalibration } from '@/lib/actions/paper-trading.actions';
import { naFor } from '@/lib/format';
import { DEFAULT_LOCALE, type Locale } from '@/lib/i18n/locale';
import { createTranslator } from '@/lib/i18n/translate';

const metricFor = (locale: Locale) => (value: number | null | undefined, ratio = false) =>
    typeof value === 'number' && Number.isFinite(value)
        ? `${(ratio ? value * 100 : value).toLocaleString(locale === 'en' ? 'en-US' : 'es-ES', { maximumFractionDigits: ratio ? 1 : 4 })}${ratio ? (locale === 'en' ? '%' : ' %') : ''}`
        : naFor(locale);

const rangeLabelFor = (metric: ReturnType<typeof metricFor>) => (value: string) => {
    const match = /^(0(?:\.\d+)?|1(?:\.0+)?)-(0(?:\.\d+)?|1(?:\.0+)?)$/.exec(value);
    if (!match || Number(match[1]) > Number(match[2])) return value;
    return `${metric(Number(match[1]), true)} - ${metric(Number(match[2]), true)}`;
};

/** Read-only calibration of recorded paper outcomes. Never claims forecast accuracy. */
export function PaperCalibrationView({ data, locale = DEFAULT_LOCALE }: { data?: PaperCalibration; locale?: Locale }) {
    const t = createTranslator(locale);
    const metric = metricFor(locale);
    const rangeLabel = rangeLabelFor(metric);
    const gap = (value: number | null) => (value === null || !Number.isFinite(value) ? naFor(locale) : t('propicks.paper.pp', { value: metric(value * 100) }));
    return <section className="min-w-0 space-y-3 rounded-lg border border-gray-700 p-4 text-sm text-gray-300" aria-label={t('propicks.paper.calLabel')}>
        <h3 className="font-semibold text-gray-100">{t('propicks.paper.calLabel')}</h3>
        {!data ? <p>{t('propicks.paper.calUnavailable')}</p> : <>
            <p>{t('propicks.paper.calClosed', { closed: data.cerradas_con_resultado, total: data.propuestas_llm })}</p>
            {data.muestra_insuficiente && <p role="status" className="text-amber-200">{t('propicks.paper.calInsufficient', { closed: data.cerradas_con_resultado, min: data.minimo_cerradas })}</p>}
            {data.aviso && <p className="text-gray-400">{data.aviso}</p>}
            <dl className="grid grid-cols-2 gap-2">
                <dt>{t('propicks.paper.brier')}</dt><dd>{metric(data.brier)}</dd>
                <dt>{t('propicks.paper.brierRef')}</dt><dd>{metric(data.brier_referencia_sin_informacion)}</dd>
            </dl>
            <p className="text-xs text-gray-400">{t('propicks.paper.notReturn')}</p>
            {data.bins.length ? <div>
                <div className="space-y-2 sm:hidden" aria-label={t('propicks.paper.groupsLabel')}>
                    {data.bins.map(bin => <article key={bin.rango} className="rounded border border-gray-800 p-3">
                        <h4 className="font-medium">{t('propicks.paper.rangeClosed', { range: rangeLabel(bin.rango), closed: bin.cerradas })}</h4>
                        <dl className="mt-2 grid grid-cols-2 gap-2 text-xs">
                            <dt>{t('propicks.paper.avgConviction')}</dt><dd>{metric(bin.conviction_media, true)}</dd>
                            <dt>{t('propicks.paper.wins')}</dt><dd>{metric(bin.tasa_acierto, true)}</dd>
                            <dt>{t('propicks.paper.difference')}</dt><dd>{gap(bin.hueco)}</dd>
                        </dl>
                        {bin.aviso && <p className="mt-2 text-xs text-gray-400">{bin.aviso}</p>}
                    </article>)}
                </div>
                <div className="hidden max-w-full overflow-x-auto sm:block">
                <table className="w-full text-left text-xs">
                    <caption className="pb-2 text-left text-gray-400">{t('propicks.paper.caption')}</caption>
                    <thead><tr>{[t('propicks.paper.colRange'), t('propicks.paper.colClosed'), t('propicks.paper.avgConviction'), t('propicks.paper.wins'), t('propicks.paper.colDiff')].map(label => <th className="px-2 py-2 first:pl-0" key={label} scope="col">{label}</th>)}</tr></thead>
                    <tbody>{data.bins.map(bin => <tr key={bin.rango} className="border-t border-gray-800">
                        <th scope="row" className="px-2 py-2 first:pl-0 font-normal">{rangeLabel(bin.rango)}{bin.aviso ? <p className="mt-1 text-gray-400">{bin.aviso}</p> : null}</th>
                        <td className="px-2 py-2">{bin.cerradas}</td>
                        <td className="px-2 py-2">{metric(bin.conviction_media, true)}</td>
                        <td className="px-2 py-2">{metric(bin.tasa_acierto, true)}</td>
                        <td className="px-2 py-2">{gap(bin.hueco)}</td>
                    </tr>)}</tbody>
                </table>
                </div>
            </div> : <p className="text-gray-400">{t('propicks.paper.noGroups')}</p>}
            <p className="text-xs text-gray-400">{t('propicks.paper.base', { value: data.base })}</p>
        </>}
    </section>;
}
