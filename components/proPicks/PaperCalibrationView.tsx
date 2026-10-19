import type { PaperCalibration } from '@/lib/actions/paper-trading.actions';

const metric = (value: number | null | undefined, ratio = false) =>
    typeof value === 'number' && Number.isFinite(value)
        ? `${(ratio ? value * 100 : value).toLocaleString('es-ES', { maximumFractionDigits: ratio ? 1 : 4 })}${ratio ? ' %' : ''}`
        : 'N/D';

const rangeLabel = (value: string) => {
    const match = /^(0(?:\.\d+)?|1(?:\.0+)?)-(0(?:\.\d+)?|1(?:\.0+)?)$/.exec(value);
    if (!match || Number(match[1]) > Number(match[2])) return value;
    return `${metric(Number(match[1]), true)} - ${metric(Number(match[2]), true)}`;
};

/** Read-only calibration of recorded paper outcomes. Never claims forecast accuracy. */
export function PaperCalibrationView({ data }: { data?: PaperCalibration }) {
    return <section className="min-w-0 space-y-3 rounded-lg border border-gray-700 p-4 text-sm text-gray-300" aria-label="Calibración del LLM">
        <h3 className="font-semibold text-gray-100">Calibración del LLM</h3>
        {!data ? <p>Calibración no disponible. No se puede evaluar la convicción con estos datos.</p> : <>
            <p>{data.cerradas_con_resultado} propuestas LLM cerradas con resultado, de {data.propuestas_llm} registradas.</p>
            {data.muestra_insuficiente && <p role="status" className="text-amber-200">Muestra insuficiente: {data.cerradas_con_resultado} cerradas; mínimo {data.minimo_cerradas}. Resultados orientativos, no validan la capacidad predictiva.</p>}
            {data.aviso && <p className="text-gray-400">{data.aviso}</p>}
            <dl className="grid grid-cols-2 gap-2">
                <dt>Error Brier</dt><dd>{metric(data.brier)}</dd>
                <dt>Referencia sin información</dt><dd>{metric(data.brier_referencia_sin_informacion)}</dd>
            </dl>
            <p className="text-xs text-gray-400">Brier mide la distancia entre la convicción y el acierto observado: más bajo es mejor. Compáralo con la referencia de la misma muestra. No es una rentabilidad ni una garantía.</p>
            {data.bins.length ? <div>
                <div className="space-y-2 sm:hidden" aria-label="Grupos de convicción">
                    {data.bins.map(bin => <article key={bin.rango} className="rounded border border-gray-800 p-3">
                        <h4 className="font-medium">Rango {rangeLabel(bin.rango)} · {bin.cerradas} cerradas</h4>
                        <dl className="mt-2 grid grid-cols-2 gap-2 text-xs">
                            <dt>Convicción media</dt><dd>{metric(bin.conviction_media, true)}</dd>
                            <dt>Aciertos</dt><dd>{metric(bin.tasa_acierto, true)}</dd>
                            <dt>Diferencia</dt><dd>{bin.hueco === null || !Number.isFinite(bin.hueco) ? 'N/D' : `${metric(bin.hueco * 100)} p.p.`}</dd>
                        </dl>
                        {bin.aviso && <p className="mt-2 text-xs text-gray-400">{bin.aviso}</p>}
                    </article>)}
                </div>
                <div className="hidden max-w-full overflow-x-auto sm:block">
                <table className="w-full text-left text-xs">
                    <caption className="pb-2 text-left text-gray-400">Convicción declarada frente a aciertos observados</caption>
                    <thead><tr>{['Rango', 'Cerradas', 'Convicción media', 'Aciertos', 'Diferencia (p.p.)'].map(label => <th className="px-2 py-2 first:pl-0" key={label} scope="col">{label}</th>)}</tr></thead>
                    <tbody>{data.bins.map(bin => <tr key={bin.rango} className="border-t border-gray-800">
                        <th scope="row" className="px-2 py-2 first:pl-0 font-normal">{rangeLabel(bin.rango)}{bin.aviso ? <p className="mt-1 text-gray-400">{bin.aviso}</p> : null}</th>
                        <td className="px-2 py-2">{bin.cerradas}</td>
                        <td className="px-2 py-2">{metric(bin.conviction_media, true)}</td>
                        <td className="px-2 py-2">{metric(bin.tasa_acierto, true)}</td>
                        <td className="px-2 py-2">{bin.hueco === null || !Number.isFinite(bin.hueco) ? 'N/D' : `${metric(bin.hueco * 100)} p.p.`}</td>
                    </tr>)}</tbody>
                </table>
                </div>
            </div> : <p className="text-gray-400">Sin grupos de resultados para comparar.</p>}
            <p className="text-xs text-gray-400">Base: {data.base}</p>
        </>}
    </section>;
}
