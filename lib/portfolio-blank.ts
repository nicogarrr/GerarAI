/**
 * Cartera «en blanco»: sin posiciones, sin caja y sin valor. Su valor total no es
 * un 0,00 € real sino ausencia de datos: el resumen (tarjetas) y la tarjeta
 * principal de «Valor de la cartera» lo pintan igual (N/D con motivo / estado vacío).
 */
export function isBlankPortfolio(summary: { holdings: readonly unknown[]; totalValue: number; cash?: number | null; equityValue?: number | null }): boolean {
    return summary.holdings.length === 0 && summary.totalValue === 0 && !summary.cash && !summary.equityValue;
}
