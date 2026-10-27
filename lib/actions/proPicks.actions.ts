'use server';

import { getCandles, getStockFinancialDataLight } from './finnhub.actions';
import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import { calculateAdvancedStockScore, type AdvancedScoreData } from '@/lib/utils/advancedStockScoring';
import {
  PROPICKS_STRATEGIES,
  calculateStrategyScore,
  getStrategyById,
} from '@/lib/utils/proPicksStrategies';

import type { SignalOverlay } from '@/lib/utils/propicksSignals';
import { getLatestFunnelPicks } from '@/lib/actions/propicks-funnel.actions';
import { withOptionalBudget } from '@/lib/propicks/optional-budget';

/** Selección con tope de rotación (núcleo puro en proPicksStrategies, reexportada aquí para el pipeline). */
import { selectRebalancedPicks, type RankedCandidate } from '@/lib/utils/proPicksStrategies';

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
  /** 0-100. Fórmula: base por banda de score + bonus reales (ver buildConfidence). */
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

const LIQUID_UNIVERSE = [
  'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'META', 'AVGO', 'ORCL', 'CRM', 'AMD',
  'JPM', 'BAC', 'GS', 'MS', 'V', 'MA', 'AXP', 'BLK', 'SCHW', 'C',
  'LLY', 'UNH', 'JNJ', 'MRK', 'ABBV', 'TMO', 'ABT', 'ISRG', 'GILD', 'AMGN',
  'WMT', 'COST', 'HD', 'MCD', 'BKNG', 'TJX', 'LOW', 'SBUX', 'NKE', 'DIS',
  'XOM', 'CVX', 'COP', 'SLB', 'EOG', 'CAT', 'GE', 'RTX', 'HON', 'ETN',
  'NEE', 'DUK', 'SO', 'CEG', 'VST', 'LIN', 'FCX', 'NEM', 'SHW', 'APD',
  'PLD', 'AMT', 'EQIX', 'WELL', 'VICI', 'TSM', 'ASML', 'NVO', 'MELI', 'SE',
] as const;

type FinancialData = Awaited<ReturnType<typeof getStockFinancialDataLight>>;

const CATEGORY_LABELS: Record<keyof AdvancedScoreData['categoryScores'], string> = {
  value: 'Valor',
  growth: 'Crecimiento',
  profitability: 'Rentabilidad',
  cashFlow: 'Flujo de caja',
  momentum: 'Momentum',
  debtLiquidity: 'Salud financiera',
};

const round1 = (n: number) => Math.round(n * 10) / 10;

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

export type SectorCategoryScores = {
  value: number;
  growth: number;
  profitability: number;
  cashFlow: number;
  momentum: number;
  debtLiquidity: number;
};

const SECTOR_NORM_CATEGORIES = ['value', 'growth', 'profitability', 'cashFlow', 'momentum', 'debtLiquidity'] as const;

/**
 * Normalización sectorial de las 6 categorías (z-score winsorizado ±3 por sector).
 *
 * Para cada sector y cada categoría: z = (x - media) / sd; se winsoriza a
 * ±3 (recorta colas extremas) y se reescala a 0-100 como 50 + z·(50/3)
 * (z=0 → 50, z=±3 → 0/100). Sectores de un solo miembro o sin dispersión
 * dan z=0 (50, neutral).
 *
 * Los `categoryScores` finales del pick SIGUEN siendo los crudos y son los que
 * alimentan R4 (score = Σ categoría × peso canónico ±1); lo normalizado solo
 * sirve para comparar/ordenar entre sectores sin sesgo de nivel.
 */
function normalizeSectorCategoryScores(picks: readonly ProPick[]): Map<string, SectorCategoryScores> {
  const bySector = new Map<string, ProPick[]>();
  for (const pick of picks) {
    const sector = pick.sector ?? 'Unknown';
    const group = bySector.get(sector);
    if (group) group.push(pick);
    else bySector.set(sector, [pick]);
  }
  const normalized = new Map<string, SectorCategoryScores>();
  for (const group of bySector.values()) {
    const stats = new Map<(typeof SECTOR_NORM_CATEGORIES)[number], { mean: number; sd: number }>();
    for (const key of SECTOR_NORM_CATEGORIES) {
      const values = group.map((p) => p.categoryScores[key]);
      const mean = values.reduce((a, b) => a + b, 0) / Math.max(1, values.length);
      const variance = values.reduce((a, b) => a + (b - mean) ** 2, 0) / Math.max(1, values.length);
      stats.set(key, { mean, sd: Math.sqrt(variance) });
    }
    for (const pick of group) {
      const entry = {} as SectorCategoryScores;
      for (const key of SECTOR_NORM_CATEGORIES) {
        const { mean, sd } = stats.get(key) ?? { mean: 50, sd: 0 };
        const z = sd < 1e-9 ? 0 : (pick.categoryScores[key] - mean) / sd;
        const winsorized = Math.max(-3, Math.min(3, z));
        entry[key] = Math.round((50 + winsorized * (50 / 3)) * 10) / 10;
      }
      normalized.set(pick.symbol, entry);
    }
  }
  return normalized;
}

/**
 * Confianza explicada del pick (0-100).
 * Fórmula calibrada y sin magia:
 *   base por banda de score: >=80 → 82 · 70-79 → 72 · 60-69 → 60 · <60 → 45
 *   +6 si upside real > 15% (precio objetivo de analista vs precio actual)
 *   +4 si ≥2 categorías superan a su sector en >5 puntos
 *   +4 si la mejor categoría ≥ 80
 *   ±bonus por overlays externos: +2 por overlay positivo, -3 por negativo,
 *   con tope total de ±6 (ver overlayConfidenceDelta). Sin overlays el bonus es 0.
 *   techo 97 (suelo 5). Nivel: Alta (>=80) · Media (>=65) · Baja (<65).
 * Los motivos se eligen solo entre métricas presentes en `facts`.
 */
function buildConfidence(
  score: number,
  advanced: AdvancedScoreData,
  upsidePotential: number,
  targetPrice: number,
  currentPrice: number,
  overlays: SignalOverlay[] = []
): { confidence: number; confidenceLevel: ProPick['confidenceLevel']; confidenceReasons: ConfidenceReason[]; facts: Record<string, number | string> } {
  const facts: Record<string, number | string> = { ...advanced.facts };
  if (targetPrice > 0) facts['targetMean'] = round1(targetPrice);
  if (upsidePotential !== 0) facts['upside'] = round1(upsidePotential);
  (Object.keys(advanced.categoryScores) as Array<keyof AdvancedScoreData['categoryScores']>).forEach((key) => {
    facts[`cat_${key}`] = advanced.categoryScores[key];
  });

  let confidence = score >= 80 ? 82 : score >= 70 ? 72 : score >= 60 ? 60 : 45;
  if (upsidePotential > 15) confidence += 6;
  const strongVsSector = Object.values(advanced.sectorComparison?.vsSector ?? {}).filter((d) => d !== null && d > 5).length;
  if (strongVsSector >= 2) confidence += 4;
  const bestCategory = (Object.entries(advanced.categoryScores) as Array<[keyof AdvancedScoreData['categoryScores'], number]>)
    .sort((a, b) => b[1] - a[1])[0];
  if (bestCategory && bestCategory[1] >= 80) confidence += 4;
  confidence += overlayConfidenceDelta(overlays);
  confidence = Math.max(5, Math.min(97, Math.round(confidence)));
  const confidenceLevel: ProPick['confidenceLevel'] = confidence >= 80 ? 'Alta' : confidence >= 65 ? 'Media' : 'Baja';

  // Motivos: solo métricas reales presentes en facts, valor incluido en el texto.
  const candidates: ConfidenceReason[] = [];
  if (targetPrice > 0 && upsidePotential > 5) {
    const v = round1(upsidePotential);
    candidates.push({
      metric: 'upside',
      value: v,
      text: `Potencial alcista del ${v}% (objetivo $${round1(targetPrice)} vs $${round1(currentPrice)})`,
    });
  }
  const deltas = advanced.sectorComparison?.vsSector;
  const bestDelta = bestCategory ? deltas?.[bestCategory[0]] : null;
  if (bestCategory && bestDelta != null && bestDelta > 5) {
    const [key, catScore] = bestCategory;
    const delta = Math.round(bestDelta);
    candidates.push({
      metric: `cat_${key}`,
      value: catScore,
      text: `${CATEGORY_LABELS[key]} ${catScore}/100 (+${delta} vs sector)`,
    });
  }
  const f = facts;
  if (typeof f['return12M'] === 'number' && f['return12M'] > 10) {
    candidates.push({ metric: 'return12M', value: f['return12M'], text: `Sube un ${f['return12M']}% en 12 meses` });
  }
  if (typeof f['vsSP500'] === 'number' && f['vsSP500'] > 5) {
    candidates.push({ metric: 'vsSP500', value: f['vsSP500'], text: `Supera al S&P 500 en ${f['vsSP500']} puntos` });
  }
  if (typeof f['proximity52W'] === 'number' && f['proximity52W'] > 95) {
    candidates.push({ metric: 'proximity52W', value: f['proximity52W'], text: `Cotiza al ${f['proximity52W']}% de su máximo de 52 semanas` });
  }
  if (typeof f['currentRatio'] === 'number' && f['currentRatio'] > 2) {
    candidates.push({ metric: 'currentRatio', value: f['currentRatio'], text: `Liquidez sólida (ratio ${f['currentRatio']})` });
  }
  // Respaldo trazable: mejores categorías aunque no batan al sector
  // (los números siguen siendo reales). Garantiza ≥2 motivos.
  if (candidates.length < 2) {
    const used = new Set(candidates.map((c) => c.metric));
    const ranked = (Object.entries(advanced.categoryScores) as Array<[keyof AdvancedScoreData['categoryScores'], number]>)
      .sort((a, b) => b[1] - a[1]);
    for (const [key, catScore] of ranked) {
      if (candidates.length >= 2) break;
      if (used.has(`cat_${key}`)) continue;
      candidates.push({
        metric: `cat_${key}`,
        value: catScore,
        text: `Su punto fuerte es ${CATEGORY_LABELS[key]} (${catScore}/100)`,
      });
    }
  }

  return { confidence, confidenceLevel, confidenceReasons: candidates.slice(0, 3), facts };
}

async function evaluateSymbol(symbol: string, strategyId: string): Promise<ProPick | null> {
  try {
    // financialData y candles son independientes: en paralelo en vez de en
    // serie (ahorra ~1 RTT Finnhub por símbolo × 70 del universo).
    const to = Math.floor(Date.now() / 1000);
    const [financialData, candles] = await Promise.all([
      getStockFinancialDataLight(symbol),
      getCandles(symbol, to - 365 * 24 * 60 * 60, to, 'D', 3600).catch(() => null),
    ]);
    const typedFinancialData: FinancialData = financialData;
    if (!typedFinancialData?.profile) return null;

    const profile = typedFinancialData.profile as Record<string, unknown>;
    const quote = typedFinancialData.quote as Record<string, unknown> | undefined;
    const currentPrice = Number(quote?.c ?? quote?.price ?? 0);
    const sector = String(profile.finnhubIndustry ?? profile.industry ?? 'Desconocido');
    const strategy = getStrategyById(strategyId) ?? PROPICKS_STRATEGIES[0];

    let historicalData: { prices: number[]; dates: number[] } | undefined;
    if (candles?.s === 'ok' && candles.c.length > 0) {
      historicalData = { prices: candles.c, dates: candles.t };
    }

    const advanced = await calculateAdvancedStockScore(typedFinancialData, historicalData);
    const targetPrice = Number(typedFinancialData.priceTarget?.targetMean ?? 0);
    const upsidePotential = currentPrice > 0 && targetPrice > 0
      ? ((targetPrice - currentPrice) / currentPrice) * 100
      : 0;

    const strategyScore = calculateStrategyScore(advanced, strategy);
    const explained = buildConfidence(advanced.overallScore, advanced, upsidePotential, targetPrice, currentPrice);

    return {
      symbol,
      company: String(profile.name ?? symbol),
      score: advanced.overallScore,
      grade: advanced.grade,
      strategyScore,
      strategy: strategy.id,
      categoryScores: advanced.categoryScores,
      reasons: [...advanced.reasons.strengths, ...advanced.reasons.opportunities].slice(0, 5),
      confidenceReasons: explained.confidenceReasons,
      confidence: explained.confidence,
      confidenceLevel: explained.confidenceLevel,
      asOf: advanced.asOf,
      facts: explained.facts,
      currentPrice,
      sector,
      exchange: profile.exchange ? String(profile.exchange) : undefined,
      vsSector: advanced.sectorComparison?.vsSector,
      targetPrice: targetPrice || undefined,
      upsidePotential: targetPrice ? upsidePotential : undefined,
      isStrongBuy: advanced.overallScore >= 80 && upsidePotential > 15,
    };
  } catch (error) {
    console.error(`No se pudo evaluar ${symbol}`, error);
    return null;
  }
}

async function evaluateUniverse(strategyId: string): Promise<ProPick[]> {
  const picks: ProPick[] = [];
  const batchSize = 8;
  for (let index = 0; index < LIQUID_UNIVERSE.length; index += batchSize) {
    const batch = LIQUID_UNIVERSE.slice(index, index + batchSize);
    const evaluated = await Promise.all(batch.map((symbol) => evaluateSymbol(symbol, strategyId)));
    picks.push(...evaluated.filter((pick): pick is ProPick => pick !== null));
  }
  return picks;
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
