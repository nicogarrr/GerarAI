'use server';

import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import type { AdvancedScoreData } from '@/lib/utils/advancedStockScoring';
import {
  PROPICKS_STRATEGIES,
  calculateStrategyScore,
  getStrategyById,
} from '@/lib/utils/proPicksStrategies';

import type { SignalOverlay } from '@/lib/utils/propicksSignals';
import { getLatestFunnelPicks } from '@/lib/actions/propicks-funnel.actions';
import { withOptionalBudget } from '@/lib/propicks/optional-budget';

/** Selección con tope de rotación (núcleo puro en proPicksStrategies, usada por el pipeline viejo). */
import { selectRebalancedPicks } from '@/lib/utils/proPicksStrategies';

export interface ConfidenceReason {
  /** Texto mostrado en UI. Siempre incluye `value` para que sea verificable. */
  text: string;
  /** Clave de `facts` de la que sale el número. Nunca referencia métricas inexistentes. */
  metric: string;
  value: number | string;
}

export interface ProPick {
  symbol: string;
  company: string;
  score: number;
  grade: string;
  strategyScore?: number;
  strategy?: string;
  categoryScores: {
    value: number;
    growth: number;
    profitability: number;
    cashFlow: number;
    momentum: number;
    debtLiquidity: number;
  };
  reasons: string[];
  /**
   * Confianza explicada: 2-3 motivos trazables a `facts` (métricas reales).
   * Regla: ningún motivo inventa números; cada `value` existe en `facts`
   * y aparece en `text` (validado por lib/utils/propicksValidation.ts).
   */
  confidenceReasons: ConfidenceReason[];
  /** 0-100. Fórmula: base por banda de score + bonus reales (bandas originales del path viejo; hoy la confianza la persiste el embudo F1). */
  confidence: number;
  /** Alta (>=80) · Media (>=65) · Baja (<65). */
  confidenceLevel: 'Alta' | 'Media' | 'Baja';
  /** Corte temporal ISO: ningún dato posterior a asOf entra al cálculo. */
  asOf: string;
  /** Foto de métricas reales tras el pick (precio, objetivo, categorías...). */
  facts: Record<string, number | string>;
  currentPrice: number;
  /** Precio persistido: su fecha y moneda no son las del run de scoring. */
  priceAsOf?: string;
  priceCurrency?: string;
  sector?: string;
  exchange?: string;
  vsSector?: {
    value: number | null;
    growth: number | null;
    profitability: number | null;
    cashFlow: number | null;
    momentum: number | null;
    debtLiquidity: number | null;
  };
  upsidePotential?: number;
  isStrongBuy?: boolean;
  targetPrice?: number;
  /** Overlays de señales externas (Fase 2). Cada uno vuelca su valor en `facts` como `ov_<metric>` (ver attachSignalOverlays, regla R5). */
  overlays?: SignalOverlay[];
}


type OverlayRecord = Record<string, number | string | boolean | null | undefined>;

/**
 * Sentimiento de un overlay externo (+1 positivo, -1 negativo, 0 neutro/desconocido).
 * Señal primaria: `impact` numérico con signo (contrato del módulo de señales
 * @/lib/utils/propicksSignals: impact en [-10, +10]). Respaldo: campos de
 * dirección en texto, por tolerancia a shapes externos.
 */
function overlaySentiment(overlay: SignalOverlay): 1 | -1 | 0 {
  const raw = overlay as unknown as OverlayRecord;
  const impact = raw['impact'];
  if (typeof impact === 'number' && Number.isFinite(impact)) {
    if (impact > 0) return 1;
    if (impact < 0) return -1;
    return 0;
  }
  const dir = String(raw['direction'] ?? raw['sentiment'] ?? raw['signal'] ?? raw['bias'] ?? '').trim().toLowerCase();
  if (['positive', 'positivo', 'positiva', 'bullish', 'bull', 'long', 'overweight', 'up', '+1', '+'].includes(dir)) return 1;
  if (['negative', 'negativo', 'negativa', 'bearish', 'bear', 'short', 'underweight', 'down', '-1', '-'].includes(dir)) return -1;
  return 0;
}

/**
 * Bonus de confianza por overlays externos: +2 por overlay positivo,
 * -3 por overlay negativo, con tope total de ±6. Neutros o sin dirección no suman.
 */
function overlayConfidenceDelta(overlays: readonly SignalOverlay[] | undefined | null): number {
  let delta = 0;
  for (const overlay of overlays ?? []) {
    const sentiment = overlaySentiment(overlay);
    delta += sentiment > 0 ? 2 : sentiment < 0 ? -3 : 0;
  }
  return Math.max(-6, Math.min(6, delta));
}

type SignalOverlaysModule = {
  getSignalOverlays?: (symbol: string, asOf: string) => Promise<SignalOverlay[]> | SignalOverlay[];
};

/**
 * Carga perezosa del módulo de señales externas (Fase 2, otro agente).
 * Devuelve null si el módulo aún no existe o falla al cargar: el pipeline
 * sigue funcionando sin overlays (fallback []).
 */
async function loadSignalOverlaysModule(): Promise<SignalOverlaysModule | null> {
  try {
    // Especificador en variable (no literal): ni tsc ni el bundler lo resuelven
    // estáticamente, así no se rompe aunque el otro agente aún no creó el módulo.
    const specifier = '@/lib/utils/propicksSignals';
    const mod = (await import(specifier)) as Partial<SignalOverlaysModule> | null;
    return mod ?? null;
  } catch {
    return null;
  }
}

/**
 * Clave de `facts` para un overlay: `ov_<metric>`, sin duplicar el prefijo si
 * la métrica ya lo trae (el módulo de señales emite `ov_revisiones`,
 * `ov_insider`, `ov_shortInterest`, `ov_vix`). Misma normalización que R5.
 */
function overlayFactsKey(metric: string): string {
  return metric.startsWith('ov_') ? metric : `ov_${metric}`;
}

/**
 * Adjunta overlays externos SOLO a los finalistas (máx 20).
 *
 *  - Carga el módulo de señales con import dinámico + try/catch: si no existe
 *    todavía o falla, devuelve los finalistas tal cual (fallback []).
 *  - Llama a getSignalOverlays(symbol, asOf) por finalista con
 *    Promise.allSettled: un símbolo que falle no tumba al resto ([] en ese pick).
 *  - Cada overlay vuelca su valor en `facts` con `overlayFactsKey(metric)`
 *    (regla R5: `metric` en facts, mismo valor, y `detail` contiene el valor).
 *  - Ajusta la confianza con el bonus de overlays (+2 positivo / -3 negativo,
 *    tope ±6) sin salir de 5-97 y recalcula el nivel.
 */
export async function attachSignalOverlays(picks: ProPick[], asOf?: string): Promise<ProPick[]> {
  const finalists = picks.slice(0, 20);
  if (finalists.length === 0) return finalists;
  // Presupuesto global de espera, no 4 segundos por fuente o por ticker.
  // Las fuentes no admiten AbortSignal: al vencer no se cancela su I/O interno.
  return withOptionalBudget(async () => {
    const mod = await loadSignalOverlaysModule();
    const fetchOverlays = mod?.getSignalOverlays;
    if (typeof fetchOverlays !== 'function') return finalists;
    const settled = await Promise.allSettled(
      finalists.map((pick) => fetchOverlays(pick.symbol, asOf ?? pick.asOf))
    );
    return finalists.map((pick, index) => {
      const result = settled[index];
      const overlays: SignalOverlay[] =
        result.status === 'fulfilled' && Array.isArray(result.value)
          ? (result.value as SignalOverlay[])
          : [];
      if (overlays.length === 0) return pick;
      const facts: ProPick['facts'] = { ...pick.facts };
      for (const overlay of overlays) {
        const rec = overlay as unknown as OverlayRecord;
        const metric = typeof rec['metric'] === 'string' ? rec['metric'] : '';
        const value = rec['value'];
        if (!metric || (typeof value !== 'number' && typeof value !== 'string')) continue;
        facts[overlayFactsKey(metric)] = value;
      }
      const confidence = Math.max(5, Math.min(97, Math.round(pick.confidence + overlayConfidenceDelta(overlays))));
      const confidenceLevel: ProPick['confidenceLevel'] = confidence >= 80 ? 'Alta' : confidence >= 65 ? 'Media' : 'Baja';
      return { ...pick, overlays, facts, confidence, confidenceLevel };
    });
  }, finalists, 4_000);
}



export async function generateProPicks(limit = 5, strategyId = 'adaptive'): Promise<ProPick[]> {
  await requireAuthenticatedUser();
  // Fuente: ultimo run persistido del embudo (F1). El path viejo evaluaba ~70
  // tickers en vivo contra Finnhub desde serverless (rate limit/timeout, F11).
  const funnel = await getLatestFunnelPicks();
  const strategy = getStrategyById(strategyId) ?? PROPICKS_STRATEGIES[0];
  const picks = (funnel?.picks ?? []).map((pick) => ({
    ...pick,
    strategy: strategy.id,
    strategyScore: calculateStrategyScore(
      { categoryScores: pick.categoryScores } as AdvancedScoreData,
      strategy
    ),
  }));
  const qualified = picks.filter((pick) => pick.score >= 60);
  const finalists = (qualified.length > 0 ? qualified : picks)
    .sort((left, right) => (right.strategyScore ?? right.score) - (left.strategyScore ?? left.score))
    .slice(0, Math.max(1, Math.min(limit, 100)));
  // Overlays externos SOLO sobre finalistas (máx 20); [] si el módulo aún no existe.
  return attachSignalOverlays(finalists, funnel?.runAsOf);
}

export async function generateProPicksForStrategy(strategyId: string, limit = 10): Promise<ProPick[]> {
  return generateProPicks(limit, strategyId);
}

export async function getAvailableStrategies() {
  await requireAuthenticatedUser();
  return PROPICKS_STRATEGIES.map(({ id, name, description }) => ({ id, name, description }));
}

export interface EnhancedProPicksFilters {
  timePeriod?: 'week' | 'month' | 'quarter' | 'year';
  limit?: number;
  minScore?: number;
  sector?: string;
  sortBy?: 'score' | 'momentum' | 'value' | 'growth' | 'profitability';
}

const SECTOR_ALIASES: Record<string, string[]> = {
  Technology: ['technology', 'software', 'semiconductor', 'internet'],
  Healthcare: ['health', 'biotech', 'pharma', 'medical'],
  'Financial Services': ['financial', 'bank', 'insurance', 'asset management'],
  'Consumer Discretionary': ['consumer', 'retail', 'apparel', 'hotel', 'restaurant'],
  Industrials: ['industrial', 'aerospace', 'defense', 'machinery'],
  Energy: ['energy', 'oil', 'gas', 'petroleum'],
  Utilities: ['utilities', 'electric', 'power'],
  'Real Estate': ['real estate', 'reit', 'property'],
  Materials: ['materials', 'chemical', 'mining', 'metal'],
};

export interface EnhancedProPicksResult {
  picks: ProPick[];
  /** Corte de datos (as_of) del último run completado del embudo; null si
   *  todavía no hay ninguno. La página lo muestra como fecha del dato: la
   *  hora de carga de la página no es la fecha del run (F49). */
  runAsOf: string | null;
  /** Candidatos aptos (passed) del run antes de filtrar por score/sector:
   *  0 con run existente significa que el embudo no produjo candidatos, no
   *  que los filtros descartaran picks (estado vacío honesto, F49). */
  passedCount: number | null;
}

export async function generateEnhancedProPicksWithRun(filters: EnhancedProPicksFilters = {}, options: { includeSignalOverlays?: boolean } = {}): Promise<EnhancedProPicksResult> {
  await requireAuthenticatedUser();
  const { limit = 20, minScore = 70, sector = 'all', sortBy = 'score' } = filters;
  // Fuente: ultimo run del embudo (ver generateProPicks).
  const funnel = await getLatestFunnelPicks();
  let picks = funnel?.picks ?? [];
  picks = picks.filter((pick) => pick.score >= minScore);

  if (sector !== 'all') {
    const aliases = SECTOR_ALIASES[sector] ?? [sector.toLowerCase()];
    picks = picks.filter((pick) => aliases.some((alias) => pick.sector?.toLowerCase().includes(alias)));
  }

  const scoreFor = (pick: ProPick) => {
    if (sortBy === 'score') return pick.strategyScore ?? pick.score;
    return pick.categoryScores[sortBy];
  };
  const finalists = picks.sort((left, right) => scoreFor(right) - scoreFor(left)).slice(0, Math.max(1, Math.min(limit, 100)));
  // Overlays externos SOLO sobre finalistas (máx 20); [] si el módulo aún no existe.
  return {
    picks: options.includeSignalOverlays === false
      ? finalists
      : await attachSignalOverlays(finalists, funnel?.runAsOf),
    runAsOf: funnel?.runAsOf ?? null,
    passedCount: funnel?.passedCount ?? null,
  };
}

export async function generateEnhancedProPicks(filters: EnhancedProPicksFilters = {}): Promise<ProPick[]> {
  const { picks } = await generateEnhancedProPicksWithRun(filters);
  return picks;
}
