/** Read-time quarantine. The persisted fact is preserved for source repair. */
export function factDisplayAudit(ticker: string, fact: {
  metric: string; unit: string; period: string; value: string;
}): string | null {
  if (fact.metric === 'market_cap' && !/^[A-Z]{3}$/.test(fact.unit)) {
    return 'Capitalización pendiente de auditoría: unidad monetaria no verificada';
  }
  if (fact.metric !== 'eps_diluted' && fact.metric !== 'eps') return null;
  // EPS is currency per share. A currency total or a share count is not EPS.
  if (!/^[A-Z]{3}\/(?:share|shares)$/.test(fact.unit)) {
    return 'BPA pendiente de auditoría: unidad no verificada';
  }
  // Production audit 2026-10-07: ASTS fact 2892290 (SEC document 3) has
  // 17,600,000 USD/share in Q1 2020, but no accession/concept lineage proving
  // that value. Do not divide by millions or substitute an inferred EPS.
  if (ticker.toUpperCase() === 'ASTS' && fact.metric === 'eps_diluted' &&
      fact.period === '2020-03-31:Q1' && Number(fact.value) === 17600000) {
    return 'BPA pendiente de auditoría: valor sin linaje de filing verificable';
  }
  return null;
}

/** Métricas de «foto» de balance: su último dato disponible se lee como
 *  estado actual. JPM tenia efectivo de 2018 y deuda total de 2013 frente
 *  a ingresos de 2025: el numero es historia, no el estado de hoy. */
const BALANCE_SNAPSHOT_METRICS = new Set([
  'cash_and_equivalents',
  'total_debt',
  'net_debt',
  'total_assets',
  'total_equity',
  'working_capital',
]);

/** Aviso cuando el último hecho de una métrica de balance va muy por detrás
 *  del último dato de la empresa. Tolerancia de un ejercicio (calendarios
 *  fiscales distintos); más allá, el número se muestra con aviso para que
 *  nadie lo tome por el estado actual. Las filas históricas (no las últimas)
 *  no llevan aviso: su antigüedad es evidente. */
export function factStalenessNotice(
  fact: { metric: string; fiscal_year: number | null },
  context: { isLatestForMetric: boolean; latestFiscalYear: number | null },
): string | null {
  if (!context.isLatestForMetric || context.latestFiscalYear === null) return null;
  if (!BALANCE_SNAPSHOT_METRICS.has(fact.metric) || fact.fiscal_year === null) return null;
  if (context.latestFiscalYear - fact.fiscal_year <= 1) return null;
  return `Último dato disponible: ${fact.fiscal_year}, sin refresco posterior`;
}
