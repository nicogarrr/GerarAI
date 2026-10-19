/**
 * Reserva del Suspense de la cotización de cabecera (#grafico). Reproduce la
 * estructura final de CompanyHeaderQuote (cotización + tira de métricas +
 * hueco del gráfico) con alturas equivalentes: con el fallback anterior
 * (h-40) la llegada del streaming desplazaba la página ~487px en móvil
 * (~76px en desktop) bajo los ojos del usuario. Las alturas son una
 * aproximación deliberada, no una réplica exacta: mantener sincronizadas con
 * CompanyHeaderQuote y con el placeholder h-[400px] de
 * CompanyTechnicalWorkspace.
 */
export function CompanyHeaderQuoteSkeleton() {
    return (
        <div aria-hidden="true" className="flex w-full animate-pulse flex-col gap-4" data-testid="company-header-quote-skeleton">
            {/* Cotización: etiqueta, precio, insignia de variación y fechas. */}
            <div>
                <div className="h-3 w-24 rounded bg-gray-800" />
                <div className="mt-1 h-10 w-44 rounded bg-gray-800 sm:h-12" />
                <div className="mt-2 h-7 w-40 rounded-full bg-gray-800" />
                <div className="mt-2 h-3 w-48 rounded bg-gray-800" />
                <div className="mt-1 h-3 w-32 rounded bg-gray-800" />
            </div>
            {/* Tira de métricas: 2 columnas en móvil, 4 en sm+. */}
            <div className="min-w-0 max-w-full">
                <div className="grid min-w-0 grid-cols-2 gap-x-3 border-y border-gray-800 sm:grid-cols-4 sm:gap-x-0 sm:divide-x sm:divide-gray-800">
                    {['Apertura', 'Máximo', 'Mínimo', 'Cierre anterior'].map((label) => (
                        <div className="min-w-0 py-3 sm:px-3 sm:first:pl-0" key={label}>
                            <div className="h-3 w-14 rounded bg-gray-800" />
                            <div className="mt-1 h-4 w-20 rounded bg-gray-800" />
                        </div>
                    ))}
                </div>
                <div className="mt-2 h-3 w-64 max-w-full rounded bg-gray-800" />
            </div>
            {/* Gráfico: misma reserva que el placeholder del dynamic import. */}
            <div className="h-[400px] rounded-xl border border-gray-800 bg-surface-1" />
        </div>
    );
}
