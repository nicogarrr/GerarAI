/**
 * Temas de mercado: tipos y lógica de vista (pura, sin imports: la ejecutan
 * los guards con `node --experimental-strip-types`).
 *
 * El cálculo vive en el backend (data-engine/app/services/market_themes.py):
 * cestas curadas, media simple, cobertura mínima del 70 % por métrica.
 */

export type ThemeMetric = { pct: number | null; n: number };
export type ThemeConstituent = {
  ticker: string;
  ytd: number | null;
  m1: number | null;
  /** Por qué está en la cesta (hecho verificable, curado en el backend). */
  reason?: string | null;
};
export type ThemeTurn = 'sube' | 'baja' | null;

export type MarketTheme = {
  id: string;
  name: string;
  n_total: number;
  ytd: ThemeMetric;
  m1: ThemeMetric;
  rank: number | null;
  rank_1m: number | null;
  hot: boolean;
  turn: ThemeTurn;
  constituents: ThemeConstituent[];
};

export type MarketThemes = {
  status: 'ok' | 'parcial' | 'sin_datos';
  as_of: string | null;
  intraday: boolean;
  generated_at: string;
  source: string;
  method: string;
  symbols_total: number;
  symbols_with_data: number;
  themes: MarketTheme[];
  /** true = dato anterior servido mientras el servidor lo refresca. */
  stale?: boolean;
};

export type ThemeOrder = 'ytd' | '1m';

/** `?orden=1m` ordena por 1M; cualquier otra cosa (o nada) es YTD. */
export function parseThemeOrder(value: string | string[] | undefined): ThemeOrder {
  const raw = Array.isArray(value) ? value[0] : value;
  return raw === '1m' ? '1m' : 'ytd';
}

export function themeMetric(theme: MarketTheme, order: ThemeOrder): ThemeMetric {
  return order === '1m' ? theme.m1 : theme.ytd;
}

/** Orden por la métrica elegida (descendente); sin dato suficiente al final, por nombre. */
export function sortThemes(themes: readonly MarketTheme[], order: ThemeOrder): MarketTheme[] {
  return [...themes].sort((a, b) => {
    const pa = themeMetric(a, order).pct;
    const pb = themeMetric(b, order).pct;
    if (pa === null && pb === null) return a.name.localeCompare(b.name, 'es');
    if (pa === null) return 1;
    if (pb === null) return -1;
    return pb - pa || a.name.localeCompare(b.name, 'es');
  });
}

/** Posición en el orden elegido; null si el tema no tiene cobertura suficiente. */
export function themeRank(theme: MarketTheme, order: ThemeOrder): number | null {
  return order === '1m' ? theme.rank_1m : theme.rank;
}

export type ThemeTone = 'up' | 'down' | 'none';
export function themeTone(pct: number | null): ThemeTone {
  if (pct === null || !Number.isFinite(pct)) return 'none';
  return pct < 0 ? 'down' : 'up';
}

/** "11/12 con datos": cobertura declarada en cada tarjeta. */
export function coverageLabel(metric: ThemeMetric, total: number): string {
  return `${metric.n}/${total} con datos`;
}

/** Los tres primeros del orden elegido (solo con cobertura suficiente). */
export function isHot(theme: MarketTheme, order: ThemeOrder): boolean {
  const rank = themeRank(theme, order);
  return rank !== null && rank <= 3;
}

export type ThemeBadge = { kind: 'turn-up' | 'turn-down' | 'hot'; label: string };

/** Una sola etiqueta por tarjeta. El giro (YTD y 1M con signo contrario) manda
 *  sobre "caliente" (top 3 del orden): un tema no puede ser a la vez caliente y
 *  girar a la baja. */
export function themeBadge(theme: MarketTheme, order: ThemeOrder): ThemeBadge | null {
  if (theme.turn === 'sube') return { kind: 'turn-up', label: 'Giro al alza' };
  if (theme.turn === 'baja') return { kind: 'turn-down', label: 'Giro a la baja' };
  if (isHot(theme, order)) return { kind: 'hot', label: 'Caliente' };
  return null;
}

/** Peso real de cada valor en la media simple de la métrica: 1/n entre los que
 *  tienen dato; 0 para los que no cuentan. Null si la métrica no se publica. */
export function constituentWeight(
  theme: MarketTheme,
  metric: ThemeMetric,
  value: number | null,
): number | null {
  if (metric.pct === null || metric.n <= 0) return null;
  return value === null ? 0 : 100 / metric.n;
}

/** Aportación en puntos porcentuales a la rentabilidad del tema. */
export function constituentContribution(
  theme: MarketTheme,
  metric: ThemeMetric,
  value: number | null,
): number | null {
  const weight = constituentWeight(theme, metric, value);
  if (weight === null || value === null) return null;
  return (weight / 100) * value;
}
