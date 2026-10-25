import { useEffect, useState } from 'react';
import { PaperProposalCard } from './PaperProposalCard';
import { PaperCalibrationView } from './PaperCalibrationView';
import { feedPaperProposalsNow, getPaperTrading, type PaperState } from '@/lib/actions/paper-trading.actions';

const number = (value: string | number | null) => value === null ? 'Sin datos' : Number(value).toLocaleString('es-ES', { maximumFractionDigits: 2 });
const horizon = (value: string) => value === 'five_years' ? 'Tesis 5 años' : 'Operación a 30 días';


function PaperFeedButton() {
    const [state, setState] = useState<'idle' | 'feeding' | 'queued' | 'error'>('idle');
    const handleFeed = async () => {
        setState('feeding');
        let success = false;
        try {
            const result = await feedPaperProposalsNow();
            success = result.success;
        } catch {
            success = false;
        } finally {
            // Un rechazo no puede dejar el botón en «Encolando…» para siempre.
            setState(success ? 'queued' : 'error');
        }
    };
    const loading = state === 'feeding';
    return (
        <div className="flex flex-col items-center gap-2">
            <button
                onClick={handleFeed}
                disabled={loading || state === 'queued'}
                aria-busy={loading}
                className="rounded-md bg-teal-600 px-4 py-2 text-sm font-medium text-white hover:bg-teal-700 disabled:opacity-50"
            >
                {loading ? 'Encolando generación...' : 'Generar propuestas simuladas'}
            </button>
            {state === 'queued' ? (
                <p className="text-sm text-teal-300">Generación en curso; recarga la página en unos minutos para ver las propuestas.</p>
            ) : null}
            {state === 'error' ? (
                <p className="text-sm text-red-400">No se pudo encolar la generación. Inténtalo de nuevo.</p>
            ) : null}
        </div>
    );
}

export function PaperTradingContent({ data }: { data: PaperState }) {
    if (data.error) return <p role="alert" className="text-red-300">{data.error}</p>;
    return <section className="min-w-0 space-y-4" aria-label="Cartera simulada LLM">
        <h2 className="text-xl font-semibold text-gray-100">Cartera simulada · IA</h2>
        <div className="grid gap-3 sm:grid-cols-2">
            {data.score.groups.map(group => <article key={`${group.horizon}-${group.currency}`} className="rounded-lg border border-gray-700 bg-gray-800/50 p-4">
                <h3 className="font-medium text-teal-300">{horizon(group.horizon)} · {group.currency === 'sin_datos' ? 'Sin divisa' : group.currency}</h3>
                <dl className="mt-3 grid grid-cols-2 gap-2 text-sm text-gray-300">
                    <dt>Aciertos / cerradas</dt><dd>{group.wins} / {group.closed}</dd>
                    <dt>Tasa de acierto</dt><dd>{group.hit_rate === null ? 'Sin datos' : `${number(group.hit_rate * 100)} %`}</dd>
                    <dt>Errores / neutras</dt><dd>{group.losses} / {group.flat}</dd>
                    <dt>Resultado bruto cerrado</dt><dd>{number(group.realized_pnl)}</dd>
                    <dt>Resultado bruto abierto</dt><dd>{number(group.unrealized_pnl)}</dd>
                    <dt>Abiertas sin precio</dt><dd>{group.missing_marks}</dd>
                </dl>
            </article>)}
        </div>
        <PaperCalibrationView data={data.score.calibracion} />
        {data.trades.length === 0 && (
            <div className="flex flex-col items-center gap-3 rounded-lg border border-gray-700 bg-gray-800/50 p-6 text-center">
                <p className="text-gray-400">Sin propuestas del modelo registradas. No se ha generado una operación simulada para mostrar.</p>
                <PaperFeedButton />
            </div>
        )}
        {data.trades.map(trade => <PaperProposalCard key={trade.id} trade={trade} />)}
        <details className="text-xs text-gray-400"><summary>Base de medición</summary><p className="mt-2">Acierto = resultado bruto positivo al cerrar. Divisas separadas. Sin comisiones, dividendos, financiación ni ajustes por splits. Una salida anticipada no valida una tesis a 5 años. Cantidad simulada: supuesto.</p></details>
    </section>;
}

export default function PaperTradingView() {
    const [data, setData] = useState<PaperState | null>(null);
    useEffect(() => { let alive = true; getPaperTrading().then(result => { if (alive) setData(result); }).catch(() => { if (alive) setData({ trades: [], score: { groups: [] }, error: 'No se pudo cargar la cartera simulada.' }); }); return () => { alive = false; }; }, []);
    return data ? <PaperTradingContent data={data} /> : <p role="status" className="text-gray-400">Cargando cartera simulada…</p>;
}
