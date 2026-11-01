/**
 * Copy MEDIDO de las categorías del embudo (caja «Sobre ProPicks IA»).
 *
 * Por qué este módulo: la caja decía antes, en literal, que «valoración y
 * momentum son neutras en los picks actuales sin datos». Eso era una
 * afirmación fija sobre un run concreto: el día que el embudo traiga CFROI/WACC
 * o momentum para todo el universo, la caja seguiría mintiendo, y un «faltan»
 * insinúa una cobertura que nadie va a completar. Aquí la frase se DERIVA de
 * los picks: el componente calcula qué categorías
 * están neutras en el run que está viendo (vía `allNeutralCategory`) y este
 * módulo solo compone el texto y la causa real de cada una.
 *
 * Las causas NO son suposiciones: son exactamente las métricas que consulta el
 * embudo en `lib/actions/propicks-funnel.actions.ts` (funnelCandidateToProPick)
 * para cada categoría. Una categoría sin la suya cae a 50 neutral y se marca
 * n/d en la tarjeta; no es un score malo, es «sin dato».
 *
 * Módulo puro (sin React y sin imports de runtime) para que un guard lo pueda
 * importar con `node --experimental-strip-types` y comprobar el copy.
 */
import type { CategoryKey } from '@/lib/propicks/category-display';

/** Idioma del texto (el módulo es puro: el componente le pasa el locale activo). */
export type CategoryNoteLocale = 'es' | 'en';

/** Orden canónico de las seis categorías del embudo. */
export const CATEGORY_KEYS: readonly CategoryKey[] = [
    'value',
    'growth',
    'profitability',
    'cashFlow',
    'momentum',
    'debtLiquidity',
];

/** Etiqueta de la categoría en la caja del embudo. */
export const CATEGORY_LABEL_ES: Record<CategoryKey, string> = {
    value: 'Valoración',
    growth: 'Crecimiento',
    profitability: 'Rentabilidad',
    cashFlow: 'Flujo de caja',
    momentum: 'Momentum',
    debtLiquidity: 'Deuda y liquidez',
};

/**
 * Qué falta para que la categoría discrimine. Una frase por categoría, con la
 * métrica que el embudo lee (lib/actions/propicks-funnel.actions.ts):
 * cfroi_approx + wacc, revenue_cagr, quality_moat_score_v2, fcf_margin_5y,
 * momentum_12m y net_debt_to_ebitda (que no aplica a bancos).
 */
export const CATEGORY_NEUTRAL_CAUSE: Record<CategoryKey, string> = {
    value: 'sin CFROI y WACC por empresa',
    growth: 'sin la serie de ingresos de 5 años',
    profitability: 'sin el marcador de calidad auditado',
    cashFlow: 'sin el margen de flujo libre de 5 años',
    momentum: 'sin la serie de precios de 12 meses',
    debtLiquidity: 'sin deuda neta sobre EBITDA (no aplica a bancos)',
};

/** Etiqueta en inglés (mismo orden y claves que la española). */
export const CATEGORY_LABEL_EN: Record<CategoryKey, string> = {
    value: 'Valuation',
    growth: 'Growth',
    profitability: 'Profitability',
    cashFlow: 'Cash flow',
    momentum: 'Momentum',
    debtLiquidity: 'Debt & liquidity',
};

/** La misma causa que `CATEGORY_NEUTRAL_CAUSE`, en inglés. */
export const CATEGORY_NEUTRAL_CAUSE_EN: Record<CategoryKey, string> = {
    value: 'missing per-company CFROI and WACC',
    growth: 'missing the 5-year revenue series',
    profitability: 'missing the audited quality score',
    cashFlow: 'missing the 5-year free cash flow margin',
    momentum: 'missing the 12-month price series',
    debtLiquidity: 'missing net debt to EBITDA (not applicable to banks)',
};

export type CategoryNeutralNote = {
    /** Marcador del checklist: ✓ todas con datos, ~ alguna neutra. */
    marker: '✓' | '~';
    /** Frase completa, ya con las causas de cada categoría neutra. */
    text: string;
    /** Categorías neutras en TODOS los picks del run. */
    neutralKeys: CategoryKey[];
};

/**
 * Estado de las categorías en el run que se está viendo.
 *
 * - `pickCount <= 0`: sin picks no hay nada que medir y NO se afirma nada
 *   (`null`). El componente cae entonces en el límite conocido del embudo.
 * - Sin ninguna categoría neutra: se dice que las seis puntúan con datos.
 * - Con alguna neutra: se nombran y se dice qué entrada falta de cada una.
 */
export function categoryNeutralNote(
    neutralKeys: readonly CategoryKey[],
    pickCount: number,
    locale: CategoryNoteLocale = 'es',
): CategoryNeutralNote | null {
    const en = locale === 'en';
    if (pickCount <= 0) return null;
    if (neutralKeys.length === 0) {
        return {
            marker: '✓',
            neutralKeys: [],
            text: en
                ? `All ${CATEGORY_KEYS.length} funnel categories have data for the ${pickCount} picks in this run: ` +
                  'every one scores for real and every one ranks.'
                :
                `Las ${CATEGORY_KEYS.length} categorías del embudo tienen datos en los ` +
                `${pickCount} picks de este run: todas puntúan de verdad y todas ordenan.`,
        };
    }
    const labels = neutralKeys.map((key) => (en ? CATEGORY_LABEL_EN : CATEGORY_LABEL_ES)[key]).join(', ');
    const causes = neutralKeys.map((key) => (en ? CATEGORY_NEUTRAL_CAUSE_EN : CATEGORY_NEUTRAL_CAUSE)[key]).join('; ');
    return {
        marker: '~',
        neutralKeys: [...neutralKeys],
        text: en
            ? `${labels}: data missing for the ${pickCount} picks in this run (${causes}). ` +
              'Without that input the category comes in neutral (50) and does not discriminate: the 50 means “data missing”, not a score.'
            :
            `${labels}: sin datos en los ${pickCount} picks de este run (${causes}). ` +
            'Sin esa entrada la categoría entra neutra (50) y no discrimina: el 50 es «sin dato», no un score.',
    };
}