import DcaHitRatesCard from '@/components/watchlist/DcaHitRatesCard';
import { getDcaHitRates } from '@/lib/actions/dca-signals.actions';

/** Ficha de research: histórico de señales DCA si el ticker está en watchlist o cartera. */
export async function DcaHitRatesSection({ ticker }: { ticker: string }) {
    const data = await getDcaHitRates(ticker);
    // Sin dato (ticker no seguido / sin evaluar, o servicio caído) el acordeón
    // NO puede quedar abierto y vacío: se dice explícitamente.
    if (!data) {
        return (
            <p role="status" data-testid="dca-hit-rates-empty" className="rounded-lg border border-gray-800 bg-gray-900/40 p-3 text-xs text-gray-400">
                Sin histórico de señales DCA para este ticker: aparece cuando está en tu watchlist o cartera y se ha evaluado, o el servicio no responde ahora mismo.
            </p>
        );
    }
    return (
        <section aria-label="Histórico de señales DCA" className="rounded-lg border border-gray-800 bg-gray-900/40 p-3">
            <DcaHitRatesCard data={data} />
        </section>
    );
}
