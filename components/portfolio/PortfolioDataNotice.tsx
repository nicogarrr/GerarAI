import type { PortfolioDataQuality } from '@/lib/actions/portfolio.actions';
import { formatDate, formatMoney } from '@/lib/format';

export default function PortfolioDataNotice({ quality }: { quality?: PortfolioDataQuality | null }) {
    if (!quality || quality.status === 'no_portfolio') return null;
    return (
        <div className="mb-4 rounded-lg border border-gray-700 bg-gray-900/40 p-3 text-sm text-gray-400" role="note">
            <p>Datos de cartera: posiciones a {quality.position_dates.map((d) => formatDate(d)).join(', ') || 'fecha no disponible'};
                {' '}caja a {quality.cash_dates.map((d) => formatDate(d)).join(', ') || 'fecha no disponible'}.</p>
            {quality.missing_cost_positions > 0 && <p className="mt-2 text-amber-300">
                Falta una base de coste válida en {quality.missing_cost_positions} posiciones.
                {quality.position_sources.includes('ibkr_flex') ? ' La sincronización no puede recuperar un coste que IBKR no entrega. Se necesita un extracto Flex completo con la PyG preparada.' : ' Revisa el coste original de los movimientos registrados.'}
            </p>}
            {quality.reasons.includes('mixed_valuation_dates') && <p className="mt-2 text-amber-300">
                Posiciones y caja tienen fechas distintas: el valor mostrado no es una foto conciliada del mismo día.
            </p>}
            <details className="mt-2">
                <summary className="cursor-pointer">Caja por divisa e historial disponible</summary>
                <p className="mt-2">{Object.entries(quality.cash_native).map(([currency, balance]) => formatMoney(balance, currency)).join(' · ') || 'Sin saldos registrados'}.
                    {' '}Un saldo negativo se conserva como deuda de margen; no se convierte en cero.</p>
                <p className="mt-2">{quality.snapshots} fotos guardadas, {quality.complete_snapshots} con cobertura de precios marcada al 100% y {quality.return_observations} retornos con cálculo completo.
                    {' '}La cobertura de precios no acredita por sí sola una conciliación con IBKR.</p>
            </details>
        </div>
    );
}
