/**
 * Validadores ProPicks: anti-datos-futuros y anti-alucinación.
 *
 * Módulo puro (sin imports, sin I/O): puede ejecutarse tanto en el servidor
 * como en el test `scripts/propicks-guard.test.ts` con node --experimental-strip-types.
 *
 * Reglas:
 *  - R1 (as_of): todo pick declara `asOf` (ISO) <= ahora. Ningún cálculo puede
 *    usar datos con timestamp posterior al corte.
 *  - R2 (trazabilidad): cada motivo de confianza referencia `metric`, esa clave
 *    existe en `facts` y el valor coincide (tolerancia numérica). Además el texto
 *    del motivo contiene el valor, para que lo mostrado sea verificable.
 *  - R3 (números mostrados): currentPrice/targetPrice/upsidePotential son
 *    coherentes con `facts` (upside = (target-price)/price*100 ± 0.5).
 *  - R4 (score): el score general reproduce la fórmula documentada en
 *    SCORING_WEIGHTS con tolerancia ±1 (redondeo).
 *  - R5 (overlays): cada overlay externo vuelca su valor en `facts` como
 *    `ov_<metric>` (mismo valor ±0.51) y su `detail` contiene el valor,
 *    para que lo mostrado sea verificable.
 */

/** Pesos canónicos del scoring general. Debe coincidir con SCORING_WEIGHTS. */
export const PROPICKS_SCORING_WEIGHTS = {
    value: 0.15,
    growth: 0.20,
    profitability: 0.25,
    cashFlow: 0.15,
    momentum: 0.10,
    debtLiquidity: 0.15,
} as const;

export interface ConfidenceReasonLike {
    text: string;
    metric: string;
    value: number | string;
}

/** Overlay externo mínimo validable (estructural: admite campos extra del módulo de señales). */
export interface OverlayLike {
    metric: string;
    value: number | string;
    /** Debe contener el valor (R5). Opcional en el tipo para tolerar shapes externos; la regla lo exige. */
    detail?: string;
}

export interface PickLike {
    symbol: string;
    asOf: string;
    facts: Record<string, number | string>;
    confidenceReasons: ConfidenceReasonLike[];
    currentPrice?: number;
    targetPrice?: number;
    upsidePotential?: number;
    score: number;
    categoryScores: Record<string, number>;
    overlays?: OverlayLike[];
}

export interface PickIssue {
    symbol: string;
    rule: 'R1-as_of' | 'R2-trazabilidad' | 'R3-numeros' | 'R4-score' | 'R5-overlays';
    message: string;
}

const SKEW_MS = 5 * 60 * 1000; // tolerancia de reloj

/**
 * Formas en texto aceptadas del valor de un motivo: la cruda («50.2») y la
 * es-ES («50,2», también con separador de miles). La UI enseña las cifras en
 * formato español; R2 exige que el valor siga siendo visible y verificable.
 */
export function valueTextVariants(value: number | string): string[] {
    const raw = String(value);
    if (typeof value !== 'number' || !Number.isFinite(value)) return [raw];
    const es = new Intl.NumberFormat('es-ES', { maximumFractionDigits: 2 }).format(value);
    return es === raw ? [raw] : [raw, es];
}

function sameValue(fact: number | string, value: number | string): boolean {
    if (typeof fact === 'string' || typeof value === 'string') {
        return String(fact) === String(value);
    }
    return Math.abs(fact - value) <= 0.51;
}

/** R1: el corte temporal es válido y no está en el futuro. */
export function validateNoFutureData(pick: PickLike, now: Date = new Date()): PickIssue[] {
    const issues: PickIssue[] = [];
    if (!pick.asOf) {
        issues.push({ symbol: pick.symbol, rule: 'R1-as_of', message: 'falta asOf: el pick no declara su corte temporal' });
        return issues;
    }
    const asOf = new Date(pick.asOf);
    if (Number.isNaN(asOf.getTime())) {
        issues.push({ symbol: pick.symbol, rule: 'R1-as_of', message: `asOf inválido: ${pick.asOf}` });
        return issues;
    }
    if (asOf.getTime() > now.getTime() + SKEW_MS) {
        issues.push({
            symbol: pick.symbol,
            rule: 'R1-as_of',
            message: `asOf (${pick.asOf}) posterior a ahora: posible uso de datos futuros`,
        });
    }
    return issues;
}

/** R2: cada motivo de confianza es trazable a facts. */
export function validateReasonsTraceable(pick: PickLike): PickIssue[] {
    const issues: PickIssue[] = [];
    if (!Array.isArray(pick.confidenceReasons) || pick.confidenceReasons.length < 2) {
        issues.push({
            symbol: pick.symbol,
            rule: 'R2-trazabilidad',
            message: 'se exigen al menos 2 motivos de confianza trazables por pick',
        });
        return issues;
    }
    for (const reason of pick.confidenceReasons) {
        if (!(reason.metric in pick.facts)) {
            issues.push({
                symbol: pick.symbol,
                rule: 'R2-trazabilidad',
                message: `motivo "${reason.text}" referencia "${reason.metric}", ausente en facts: número no verificable`,
            });
            continue;
        }
        if (!sameValue(pick.facts[reason.metric], reason.value)) {
            issues.push({
                symbol: pick.symbol,
                rule: 'R2-trazabilidad',
                message: `motivo "${reason.text}": valor ${reason.value} ≠ facts.${reason.metric} (${pick.facts[reason.metric]})`,
            });
        }
        if (!valueTextVariants(reason.value).some((variant) => reason.text.includes(variant))) {
            issues.push({
                symbol: pick.symbol,
                rule: 'R2-trazabilidad',
                message: `motivo "${reason.text}" no muestra su valor (${reason.value}): no es verificable en UI`,
            });
        }
    }
    return issues;
}

/** R3: los números mostrados derivan de facts/quotes. */
export function validateNumbersTraceable(pick: PickLike): PickIssue[] {
    const issues: PickIssue[] = [];
    const price = pick.facts['price'];
    if (pick.currentPrice !== undefined && pick.currentPrice > 0) {
        if (typeof price !== 'number' || Math.abs(pick.currentPrice - price) > Math.max(0.5, price * 0.02)) {
            issues.push({
                symbol: pick.symbol,
                rule: 'R3-numeros',
                message: `currentPrice (${pick.currentPrice}) no coincide con facts.price (${price})`,
            });
        }
    }
    const target = pick.facts['targetMean'];
    if (pick.targetPrice !== undefined && pick.targetPrice > 0) {
        if (typeof target !== 'number' || Math.abs(pick.targetPrice - target) > Math.max(0.5, target * 0.02)) {
            issues.push({
                symbol: pick.symbol,
                rule: 'R3-numeros',
                message: `targetPrice (${pick.targetPrice}) no coincide con facts.targetMean (${target})`,
            });
        }
    }
    if (
        pick.upsidePotential !== undefined &&
        pick.currentPrice !== undefined && pick.currentPrice > 0 &&
        pick.targetPrice !== undefined && pick.targetPrice > 0
    ) {
        const expected = ((pick.targetPrice - pick.currentPrice) / pick.currentPrice) * 100;
        if (Math.abs(pick.upsidePotential - expected) > 0.5) {
            issues.push({
                symbol: pick.symbol,
                rule: 'R3-numeros',
                message: `upsidePotential (${pick.upsidePotential}) ≠ calculado (${expected.toFixed(2)})`,
            });
        }
    }
    return issues;
}

/** R4: el score reproduce la fórmula documentada (pesos canónicos, ±1 por redondeo). */
export function validateScoreFormula(pick: PickLike): PickIssue[] {
    const w = PROPICKS_SCORING_WEIGHTS;
    const c = pick.categoryScores;
    const keys = Object.keys(w) as Array<keyof typeof w>;
    for (const key of keys) {
        if (typeof c[key] !== 'number' || !Number.isFinite(c[key])) {
            return [{ symbol: pick.symbol, rule: 'R4-score', message: `categoría "${key}" sin puntuación numérica` }];
        }
    }
    const expected = Math.round(keys.reduce((sum, key) => sum + c[key] * w[key], 0));
    if (Math.abs(pick.score - expected) > 1) {
        return [{
            symbol: pick.symbol,
            rule: 'R4-score',
            message: `score (${pick.score}) ≠ fórmula documentada (${expected}): pesos o cálculo divergentes`,
        }];
    }
    return [];
}

/** R5: cada overlay externo vuelca su valor en facts (clave `ov_<metric>`, sin duplicar el prefijo si la métrica ya lo trae) y lo muestra en `detail`. */
export function validateOverlays(pick: PickLike): PickIssue[] {
    const issues: PickIssue[] = [];
    for (const overlay of pick.overlays ?? []) {
        if (!overlay || typeof overlay.metric !== 'string' || overlay.metric.length === 0) {
            issues.push({
                symbol: pick.symbol,
                rule: 'R5-overlays',
                message: 'overlay sin metric: no se puede trazar a facts',
            });
            continue;
        }
        // Misma normalización que overlayFactsKey en proPicks.actions.ts.
        const key = overlay.metric.startsWith('ov_') ? overlay.metric : `ov_${overlay.metric}`;
        if (!(key in pick.facts)) {
            issues.push({
                symbol: pick.symbol,
                rule: 'R5-overlays',
                message: `overlay "${overlay.metric}": falta facts.${key} (valor ${String(overlay.value)}): número no verificable`,
            });
        } else if (!sameValue(pick.facts[key], overlay.value)) {
            issues.push({
                symbol: pick.symbol,
                rule: 'R5-overlays',
                message: `overlay "${overlay.metric}": valor ${String(overlay.value)} ≠ facts.${key} (${String(pick.facts[key])})`,
            });
        }
        if (typeof overlay.detail !== 'string' || !overlay.detail.includes(String(overlay.value))) {
            issues.push({
                symbol: pick.symbol,
                rule: 'R5-overlays',
                message: `overlay "${overlay.metric}": detail no muestra su valor (${String(overlay.value)}): no es verificable en UI`,
            });
        }
    }
    return issues;
}

/** Ejecuta las 5 reglas sobre una lista de picks. Vacío = todo válido. */
export function validatePicks(picks: PickLike[], now: Date = new Date()): PickIssue[] {
    return picks.flatMap((pick) => [
        ...validateNoFutureData(pick, now),
        ...validateReasonsTraceable(pick),
        ...validateNumbersTraceable(pick),
        ...validateScoreFormula(pick),
        ...validateOverlays(pick),
    ]);
}
