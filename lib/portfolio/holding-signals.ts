// @ts-expect-error TS5097: extension explicita para node --experimental-strip-types (scripts/holding-signals.test.ts, sin alias «@/»).
import { chartPriceUnit } from '../market/chart-price-units.ts';

// Nivel DCA y valor justo por posición: mapeo PURO (sin red) para cartera e inicio.
//
// - Valor justo: el ÚNICO del backend (/api/valuation/fair-value, tesis o motor)
//   con su etiqueta de procedencia; la misma cifra que la watchlist.
// - Nivel DCA: /api/watchlist/dca-signals del motor DCA. Si el endpoint no existe
//   todavía (motor sin mergear) o falla, se degrada a «sin nivel»: nunca se
//   inventa un nivel.

export type FairValueSource = 'tesis' | 'motor' | 'motor_orientativo';

export type HoldingFairValue = {
    value: number;
    source: FairValueSource;
    label: string;
    asOf: string | null;
    currency: string | null;
    publishable: boolean;
};

export type HoldingDcaLevel = {
    level: number;
    label: string;
    forming: boolean;
    signalDate: string | null;
    color: string | null;
    fg: string | null;
};

export type HoldingSignals = {
    fairValues: Record<string, HoldingFairValue>;
    /** null = motor DCA no disponible (endpoint ausente o caído): «sin nivel». */
    dca: Record<string, HoldingDcaLevel> | null;
};

export const NO_DCA_LEVEL = 'Sin nivel';

const SOURCES: readonly FairValueSource[] = ['tesis', 'motor', 'motor_orientativo'];

function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/** Respuesta de /api/valuation/fair-value → mapa por ticker (solo lecturas válidas). */
export function mapFairValues(raw: unknown): Record<string, HoldingFairValue> {
    const out: Record<string, HoldingFairValue> = {};
    const items = isRecord(raw) && isRecord(raw.items) ? raw.items : {};
    for (const [ticker, item] of Object.entries(items)) {
        if (!isRecord(item)) continue;
        const value = typeof item.value === 'number' ? item.value : null;
        const source = SOURCES.find((s) => s === item.source);
        if (value === null || !(value > 0) || !Number.isFinite(value) || !source) continue;
        out[ticker.toUpperCase()] = {
            value,
            source,
            label: typeof item.label === 'string' && item.label ? item.label : 'Valor justo',
            asOf: typeof item.as_of === 'string' ? item.as_of : null,
            currency: typeof item.currency === 'string' ? item.currency : null,
            publishable: item.publishable === true,
        };
    }
    return out;
}

/** Respuesta de /api/watchlist/dca-signals → mapa por ticker; null si no es válida. */
export function mapDcaSignals(raw: unknown): Record<string, HoldingDcaLevel> | null {
    if (!isRecord(raw) || !Array.isArray(raw.items)) return null;
    const out: Record<string, HoldingDcaLevel> = {};
    for (const item of raw.items) {
        if (!isRecord(item) || typeof item.symbol !== 'string' || !isRecord(item.state)) continue;
        const state = item.state;
        if (typeof state.level !== 'number' || typeof state.label !== 'string') continue;
        out[item.symbol.toUpperCase()] = {
            level: state.level,
            label: state.label,
            forming: state.status === 'forming',
            signalDate: typeof state.signal_date === 'string' ? state.signal_date : null,
            color: typeof state.color === 'string' ? state.color : null,
            fg: typeof state.fg === 'string' ? state.fg : null,
        };
    }
    return out;
}

/** Texto del nivel DCA para una posición: «4X DCA», «2X DCA (provisional)» o «Sin nivel». */
export function dcaLevelText(level: HoldingDcaLevel | null | undefined): string {
    if (!level) return NO_DCA_LEVEL;
    return level.forming ? `${level.label} (provisional)` : level.label;
}

/** Distancia del precio al valor justo en % (positivo = margen al alza).
 *  Solo si ambas cifras están en la MISMA divisa; si no, null (no se mezclan
 *  divisas ni peniques/libras). */
export function fairValueGapPercent(
    price: number | null | undefined,
    priceCurrency: string | null | undefined,
    fair: HoldingFairValue | null | undefined,
): number | null {
    if (!fair || price == null || !(price > 0) || !Number.isFinite(price)) return null;
    // Unidad, no solo divisa: «GBp» (peniques) no es «GBP». Pasar a mayúsculas
    // igualaba 1.200 p con un valor justo de 15 £. El precio va a la unidad
    // mayor; un valor justo rotulado en una subunidad no se compara.
    const quoteUnit = chartPriceUnit(priceCurrency);
    const fairUnit = chartPriceUnit(fair.currency);
    if (!quoteUnit || !fairUnit || fairUnit.divisor !== 1 || quoteUnit.currency !== fairUnit.currency) return null;
    const major = price / quoteUnit.divisor;
    return ((fair.value - major) / major) * 100;
}
