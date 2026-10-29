import { getAnalystTargets } from '@/lib/research/analyst-targets';
import { AnalystTargetsView } from './AnalystTargetsView';

export async function AnalystTargetsSection({ symbol, currency }: { symbol: string; currency?: string | null }) {
    // Lectura compartida con el panel de vistazo rápido (React cache):
    // una sola llamada al motor por render aunque lo pidan dos secciones.
    const data = await getAnalystTargets(symbol);
    return <AnalystTargetsView data={data} currency={currency} />;
}
