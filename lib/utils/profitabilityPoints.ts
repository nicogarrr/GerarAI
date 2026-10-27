/**
 * Puntos de rentabilidad del scoring avanzado (margen neto, ROE, ROA).
 *
 * Módulo puro (sin alias ni E/S) para poder testearlo con node:test.
 * El signo se conserva: una pérdida es rentabilidad NEGATIVA, nunca positiva
 * (antes `Math.abs` puntuaba un margen del -30 % como uno del +30 %).
 * Referencia: CFA Institute, Financial Statement Analysis (margen neto = beneficio neto / ventas).
 */

/** Pasa a fracción un valor que el proveedor puede dar en % (30) o en fracción (0.30), CONSERVANDO el signo. */
export function ratioFromProviderValue(value: number): number {
    return Math.abs(value) > 1 ? value / 100 : value;
}

export function netMarginPoints(rawMargin: number, sectorMargin: number): number {
    const margin = ratioFromProviderValue(rawMargin);
    return margin > sectorMargin * 1.3 ? 35 : margin > sectorMargin ? 30 : margin > 0.1 ? 25 : margin > 0 ? 15 : 0;
}

export function roePoints(rawRoe: number): number {
    const roe = ratioFromProviderValue(rawRoe);
    return roe > 0.2 ? 35 : roe > 0.15 ? 30 : roe > 0.1 ? 25 : roe > 0 ? 20 : 10;
}

export function roaPoints(rawRoa: number): number {
    const roa = ratioFromProviderValue(rawRoa);
    return roa > 0.1 ? 30 : roa > 0.05 ? 25 : roa > 0 ? 20 : 10;
}
