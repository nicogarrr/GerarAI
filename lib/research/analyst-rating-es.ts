const RATINGS_ES: Record<string, string> = {
  'strong buy': 'Compra fuerte',
  buy: 'Compra',
  outperform: 'Superar al mercado',
  'market outperform': 'Superar al mercado',
  'sector outperform': 'Superar al sector',
  overweight: 'Sobreponderar',
  'add': 'Añadir',
  accumulate: 'Acumular',
  positive: 'Positiva',
  'top pick': 'Selección preferida',
  neutral: 'Neutral',
  hold: 'Mantener',
  'equal-weight': 'Ponderación neutral',
  'equal weight': 'Ponderación neutral',
  'market perform': 'En línea con el mercado',
  'sector perform': 'En línea con el sector',
  'peer perform': 'En línea con comparables',
  'in-line': 'En línea',
  'in line': 'En línea',
  perform: 'En línea',
  'sector weight': 'Ponderación del sector',
  underperform: 'Peor que el mercado',
  'market underperform': 'Peor que el mercado',
  'sector underperform': 'Peor que el sector',
  underweight: 'Infraponderar',
  reduce: 'Reducir',
  negative: 'Negativa',
  sell: 'Venta',
  'strong sell': 'Venta fuerte',
};

/** Recomendación de analista en español; si no hay traducción conocida se deja el texto original (nada inventado). */
export function analystRatingEs(rating: string | null | undefined): string | null {
  if (!rating) return null;
  const key = rating.trim().toLowerCase().replace(/\s+/g, ' ');
  return Object.hasOwn(RATINGS_ES, key) ? RATINGS_ES[key] : rating.trim();
}
