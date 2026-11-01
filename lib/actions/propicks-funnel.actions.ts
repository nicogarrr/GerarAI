'use server';

/**
 * ProPicks desde el embudo determinista (F1/F2): la pagina /propicks lee el
 * ultimo run persistido en el backend en vez de evaluar ~70 tickers en vivo
 * contra Finnhub (path viejo: rate limit/timeout en serverless -> F11).
 *
 * Veracidad: cada categoria se deriva de metricas reales del run con escalas
 * fijas documentadas aqui; el score general reproduce PROPICKS_SCORING_WEIGHTS
 * por construccion (regla R4 del guard). Nada se inventa: si una metrica
 * falta, la categoria cae a 50 neutral y queda marcada en `facts`.
 */

import { researchRequest } from '@/lib/research/client';
import { getGrade } from '@/lib/utils/advancedStockScoring';
import { moatChecksToScore, MOAT_V2_MAX_CHECKS } from '@/lib/propicks/moat-scale';
import { PROPICKS_SCORING_WEIGHTS } from '@/lib/utils/propicksValidation';
import type { ConfidenceReason, ProPick } from '@/lib/actions/proPicks.actions';
import { backendMessageForRequest } from '@/lib/research/backend-error-locale';

interface FunnelRunSummary {
  id: number;
  as_of: string;
  status: string;
  universe_size: number;
  passed_count: number;
  top_n: number;
}

interface FunnelCandidate {
  company_id: number;
  ticker: string;
  name: string;
  sector: string;
  currency: string;
  passed: boolean;
  rank: number | null;
  score: number | null;
  failed_gates: string[];
  metrics: Record<string, number | null>;
  coverage: Record<string, string>;
  current_price: number | null;
  price_as_of: string | null;
}

interface FunnelRunDetail extends FunnelRunSummary {
  candidates: FunnelCandidate[];
}

export interface FunnelPicksResult {
  picks: ProPick[];
  runId: number;
  runAsOf: string;
  universeSize: number;
  passedCount: number;
}

/** Ultimo run completado con sus candidatos (passed, ordenados por rank). */
export async function getLatestFunnelPicks(): Promise<FunnelPicksResult | null> {
  const runs = await researchRequest<FunnelRunSummary[]>('/api/propicks/runs?limit=5', { fast: true });
  const latest = (runs ?? [])
    .filter((run) => run.status === 'completed')
    .sort((a, b) => b.id - a.id)[0];
  if (!latest) return null;
  const detail = await researchRequest<FunnelRunDetail>(`/api/propicks/runs/${latest.id}?only_passed=true`, { fast: true });
  const ranked = (detail.candidates ?? [])
    .filter((c) => c.passed && c.rank !== null)
    .sort((a, b) => (a.rank ?? 0) - (b.rank ?? 0));
  return {
    picks: ranked.map((c) => funnelCandidateToProPick(c, detail.as_of)),
    runId: detail.id,
    runAsOf: detail.as_of,
    universeSize: detail.universe_size,
    passedCount: detail.passed_count,
  };
}

/** Ejecuta el embudo completo ahora (POST /api/propicks/runs) y devuelve el run creado. */
export async function generateFunnelRunNow(): Promise<FunnelRunSummary | { error: string }> {
  try {
    return await researchRequest<FunnelRunSummary>('/api/propicks/runs', { method: 'POST' });
  } catch (error) {
    console.error('generateFunnelRunNow error:', error);
    return { error: error instanceof Error ? await backendMessageForRequest(error.message) : 'No se pudo generar la selección.' };
  }
}

const clamp = (n: number, lo = 0, hi = 100) => Math.max(lo, Math.min(hi, n));
const round1 = (n: number) => Math.round(n * 10) / 10;
const pct = (ratio: number) => round1(ratio * 100);
/** Cifras de los motivos en formato es-ES (coma decimal), igual que el resto de la UI. */
const esNum = (n: number) => new Intl.NumberFormat('es-ES', { maximumFractionDigits: 1 }).format(n);

/**
 * Mapeo honesto candidato del embudo -> ProPick.
 *
 * Escalas de categoria (0-100, deterministas, documentadas):
 *  - profitability: quality_moat_score_v2 es un recuento de criterios (0-8): se escala a 0-100 (moatChecksToScore).
 *  - value: 50 + (cfroi_approx - wacc) * 500 (spread +10% -> 100, -10% -> 0).
 *  - growth: 50 + revenue_cagr * 250 (+20% anual -> 100, -20% -> 0).
 *  - cashFlow: fcf_margin_5y * 400 (margen 25% -> 100).
 *  - momentum: 50 + momentum_12m * 100 (+50% -> 100); si el run no lo trae
 *    (runs anteriores al F2) cae a 50 y facts['momentum_neutral_sin_datos'].
 *  - debtLiquidity: 100 - net_debt_to_ebitda * 25 (0x -> 100, 4x -> 0);
 *    bancos (sin deuda neta/EBITDA aplicable) caen a 50 y facts['deuda_neutral_banco'].
 */
function funnelCandidateToProPick(c: FunnelCandidate, runAsOf: string): ProPick {
  const m = c.metrics ?? {};
  const facts: Record<string, number | string> = {};

  const moat = m.quality_moat_score_v2 ?? null;
  const cfroi = m.cfroi_approx ?? null;
  const wacc = m.wacc ?? null;
  const cagr = m.revenue_cagr ?? null;
  const fcfMargin = m.fcf_margin_5y ?? null;
  const momentum = m.momentum_12m ?? null;
  const leverage = m.net_debt_to_ebitda ?? null;
  const roic = m.roic ?? null;
  const roe5y = m.roe_5y ?? null;

  if (moat !== null) facts['quality_moat_score_v2'] = round1(moat);
  if (cfroi !== null) facts['cfroi_approx'] = round1(cfroi * 100);
  if (wacc !== null) facts['wacc'] = round1(wacc * 100);
  if (cagr !== null) facts['revenue_cagr'] = pct(cagr);
  if (fcfMargin !== null) facts['fcf_margin_5y'] = pct(fcfMargin);
  if (momentum !== null) facts['momentum_12m'] = pct(momentum);
  if (leverage !== null) facts['net_debt_to_ebitda'] = round1(leverage);
  if (roic !== null) facts['roic'] = pct(roic);
  if (roe5y !== null) facts['roe_5y'] = pct(roe5y);

  const profitability = moat !== null ? clamp(moatChecksToScore(moat)) : 50;
  if (moat === null) facts['moat_neutral_sin_datos'] = 'si';
  const value = cfroi !== null && wacc !== null ? clamp(round1(50 + (cfroi - wacc) * 500)) : 50;
  if (cfroi === null || wacc === null) facts['valoracion_neutral_sin_datos'] = 'si';
  const growth = cagr !== null ? clamp(round1(50 + cagr * 250)) : 50;
  if (cagr === null) facts['crecimiento_neutral_sin_datos'] = 'si';
  const cashFlow = fcfMargin !== null ? clamp(round1(fcfMargin * 400)) : 50;
  if (fcfMargin === null) facts['fcf_neutral_sin_datos'] = 'si';
  const momentumScore = momentum !== null ? clamp(round1(50 + momentum * 100)) : 50;
  if (momentum === null) facts['momentum_neutral_sin_datos'] = 'si';
  const debtLiquidity = leverage !== null ? clamp(round1(100 - leverage * 25)) : 50;
  if (leverage === null) facts['deuda_neutral_sin_datos'] = 'si';

  const categoryScores = {
    value,
    growth,
    profitability,
    cashFlow,
    momentum: momentumScore,
    debtLiquidity,
  };
  const w = PROPICKS_SCORING_WEIGHTS;
  const score = Math.round(
    categoryScores.value * w.value +
      categoryScores.growth * w.growth +
      categoryScores.profitability * w.profitability +
      categoryScores.cashFlow * w.cashFlow +
      categoryScores.momentum * w.momentum +
      categoryScores.debtLiquidity * w.debtLiquidity
  );
  (Object.keys(categoryScores) as Array<keyof typeof categoryScores>).forEach((key) => {
    facts[`cat_${key}`] = categoryScores[key];
  });

  const currentPrice = c.current_price ?? 0;
  if (currentPrice > 0) {
    facts['currentPrice'] = currentPrice;
    if (c.price_as_of) facts['price_as_of'] = c.price_as_of;
  } else {
    facts['precio_pendiente'] = 'si';
  }

  // Motivos: solo metricas presentes en facts, valor incluido en el texto (R2).
  const confidenceReasons: ConfidenceReason[] = [];
  if (moat !== null) {
    confidenceReasons.push({
      metric: 'quality_moat_score_v2',
      value: facts['quality_moat_score_v2'],
      text: `Marco de calidad ${facts['quality_moat_score_v2']}/${MOAT_V2_MAX_CHECKS} criterios superados según fundamentales auditados`,
    });
  }
  if (cfroi !== null && wacc !== null) {
    const spread = round1((cfroi - wacc) * 100);
    facts['spread_cfroi_wacc'] = spread;
    confidenceReasons.push({
      metric: 'spread_cfroi_wacc',
      value: spread,
      text: `CFROI ${esNum(Number(facts['cfroi_approx']))} % vs WACC ${esNum(Number(facts['wacc']))} %: spread de ${esNum(spread)} puntos`,
    });
  }
  if (cagr !== null) {
    confidenceReasons.push({
      metric: 'revenue_cagr',
      value: facts['revenue_cagr'],
      text: `Ingresos creciendo al ${esNum(Number(facts['revenue_cagr']))} % anual (5 años)`,
    });
  }
  if (fcfMargin !== null) {
    confidenceReasons.push({
      metric: 'fcf_margin_5y',
      value: facts['fcf_margin_5y'],
      text: `Margen FCF medio del ${esNum(Number(facts['fcf_margin_5y']))} % (5 años)`,
    });
  }
  const topReasons = confidenceReasons.slice(0, 3);

  // Confianza: bandas del buildConfidence original (base por score + bonus categoria alta).
  let confidence = score >= 80 ? 82 : score >= 70 ? 72 : score >= 60 ? 60 : 45;
  const bestCategory = Object.values(categoryScores).sort((a, b) => b - a)[0];
  if (bestCategory >= 80) confidence += 4;
  confidence = Math.max(5, Math.min(97, Math.round(confidence)));

  return {
    symbol: c.ticker,
    company: c.name,
    score,
    grade: getGrade(score),
    categoryScores,
    reasons: topReasons.map((r) => r.text),
    confidenceReasons: topReasons,
    confidence,
    confidenceLevel: confidence >= 80 ? 'Alta' : confidence >= 65 ? 'Media' : 'Baja',
    asOf: runAsOf,
    facts,
    currentPrice,
    priceAsOf: c.price_as_of ?? undefined,
    priceCurrency: c.currency || undefined,
    sector: c.sector,
    overlays: [],
  };
}
