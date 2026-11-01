/**
 * Ayudas puras (sin React ni servidor) para el rebalanceo mensual de GerarAI Propicks.
 *
 * - Catálogo canónico de las 4 estrategias públicas. Si el servidor aún no provee
 *   alguna (las añaden otros agentes en lib/utils/proPicksStrategies.ts), se marca
 *   como no disponible y la UI muestra un estado «sin datos» honesto.
 * - Snapshot mensual JSON descargable + diff entra/sale con motivo trazable.
 * - Acceso a campos de otros agentes (overlays, snapshots, métricas netas) siempre
 *   con optional chaining y fallbacks, para no romper si aún no existen.
 */

import type { ProPick } from '@/lib/actions/proPicks.actions';
import { createFormatters, formatNumber } from '@/lib/format';
import type { Locale } from '@/lib/i18n/locale';

export interface StrategyCatalogEntry {
    id: string;
    name: string;
    description: string;
}

/** Catálogo público de las 4 estrategias. Nombres y textos en español. */
export const STRATEGY_CATALOG: StrategyCatalogEntry[] = [
    {
        id: 'adaptive',
        name: 'Selección Adaptativa IA',
        description:
            'La IA reparte el peso entre valor, crecimiento y rentabilidad según el momento de mercado.',
    },
    {
        id: 'value',
        name: 'Value',
        description:
            'Prioriza acciones baratas por fundamentales frente a su sector y con balance sólido.',
    },
    {
        id: 'momentum',
        name: 'Momentum',
        description:
            'Prioriza acciones con tendencia alcista sostenida y fuerza relativa frente al mercado.',
    },
    {
        id: 'defensiva',
        name: 'Defensiva',
        description:
            'Prioriza baja volatilidad, dividendos estables y salud financiera para capear caídas.',
    },
];

export interface ServerStrategy {
    id: string;
    name: string;
    description: string;
}

export interface MergedStrategy extends StrategyCatalogEntry {
    /** true si el servidor la provee (hay selección y backtest reales). */
    available: boolean;
}

/**
 * Fusiona las estrategias del servidor con el catálogo público.
 * Las que el servidor aún no provee quedan como available: false («sin datos»).
 */
export function mergeStrategies(serverStrategies: ServerStrategy[]): MergedStrategy[] {
    const byId = new Map(serverStrategies.map((s) => [s.id, s]));
    return STRATEGY_CATALOG.map((entry) => {
        const server = byId.get(entry.id);
        if (!server) return { ...entry, available: false };
        return {
            id: entry.id,
            name: server.name || entry.name,
            description: server.description || entry.description,
            available: true,
        };
    });
}

/** Motivo trazable de un pick: texto visible + métrica y valor verificables. */
export interface TraceableReason {
    text: string;
    metric?: string;
    value?: number | string;
}

/**
 * Overlay aportado por el pipeline de señales (ver lib/utils/propicksSignals.ts,
 * tipo SignalOverlay: { factor, impact, detail, metric, value, asOf }).
 * Aquí se usa una forma estructural mínima con todo opcional: se accede con
 * optional chaining para no romper si el shape evoluciona. No se importa el
 * módulo de señales porque es solo-uso-en-servidor.
 */
interface OverlayLike {
    detail?: unknown;
    text?: unknown;
    reason?: unknown;
    label?: unknown;
    metric?: unknown;
    value?: unknown;
    factor?: unknown;
}

function overlaysOf(pick: ProPick): OverlayLike[] {
    const raw = (pick as { overlays?: unknown }).overlays;
    return Array.isArray(raw) ? (raw as OverlayLike[]) : [];
}

function overlayText(o: OverlayLike): string | undefined {
    for (const key of ['detail', 'text', 'reason', 'label'] as const) {
        const v = o[key];
        if (typeof v === 'string' && v.length > 0) return v;
    }
    return undefined;
}

/**
 * Motivo principal de un valor: primer confidenceReason (trazable a facts),
 * complementado con overlays si el pipeline los aporta.
 * Ningún número sin fuente: todo sale de confidenceReasons/overlays/facts.
 */
export function pickReason(pick: ProPick): TraceableReason {
    const overlay = overlaysOf(pick).find((o) => overlayText(o));
    if (overlay) {
        const metric = typeof overlay.metric === 'string' ? overlay.metric : undefined;
        const value =
            typeof overlay.value === 'number' || typeof overlay.value === 'string'
                ? overlay.value
                : undefined;
        const text = overlayText(overlay);
        if (text) return { text, metric, value };
    }
    const first = pick.confidenceReasons?.[0];
    if (first?.text) {
        return { text: first.text, metric: first.metric, value: first.value };
    }
    return {
        text: `Score ${formatNumber(pick.score, { maximumFractionDigits: 0 })}/100 con confianza ${pick.confidenceLevel}`,
    };
}

/** Todos los motivos trazables de un pick (para la vista de rebalanceo). */
export function pickReasons(pick: ProPick): TraceableReason[] {
    const reasons: TraceableReason[] = (pick.confidenceReasons ?? [])
        .filter((r) => r?.text)
        .map((r) => ({ text: r.text, metric: r.metric, value: r.value }));
    for (const o of overlaysOf(pick)) {
        const text = overlayText(o);
        if (text && !reasons.some((r) => r.text === text)) {
            const metric = typeof o.metric === 'string' ? o.metric : undefined;
            const value =
                typeof o.value === 'number' || typeof o.value === 'string' ? o.value : undefined;
            reasons.push({ text, metric, value });
        }
    }
    return reasons.slice(0, 4);
}

export interface SnapshotPick {
    symbol: string;
    company: string;
    score: number;
    confidence: number;
    confidenceLevel: string;
    reasons: TraceableReason[];
    facts: Record<string, number | string>;
    asOf: string;
}

export interface MonthlySnapshot {
    kind: 'cavaai-propicks-monthly-snapshot';
    version: 1;
    /** Mes en formato YYYY-MM. */
    month: string;
    strategyId: string;
    generatedAt: string;
    picks: SnapshotPick[];
}

/** Clave de mes YYYY-MM para una fecha. */
export function monthKey(date: Date = new Date()): string {
    const y = date.getFullYear();
    const m = String(date.getMonth() + 1).padStart(2, '0');
    return `${y}-${m}`;
}

/** Etiqueta de mes en el idioma elegido («septiembre de 2026» / «September 2026»). */
export function monthLabel(month: string, locale: Locale = 'es'): string {
    const [y, m] = month.split('-').map(Number);
    if (!y || !m) return month;
    // Fecha de solo día: formatDate la parsea en hora local, así que el mes
    // sale igual en el servidor (UTC) y en el navegador.
    return createFormatters(locale).formatDate(`${y}-${String(m).padStart(2, '0')}-01`, {
        month: 'long',
        year: 'numeric',
    });
}

/** Etiqueta de mes en español («septiembre de 2026»). */
export function monthLabelEs(month: string): string {
    return monthLabel(month, 'es');
}

/** Motivo de quien sale cuando el snapshot anterior no guardó ninguno. */
export const PREVIOUS_MONTH_REASON = 'Estaba en la selección del mes anterior';

const CONFIDENCE_EN: Record<string, string> = { alta: 'high', media: 'medium', baja: 'low' };

/**
 * Los motivos se guardan tal cual en el snapshot JSON (en español): solo se
 * traducen al pintarlos. Los motivos del backend llegan como vienen.
 */
export function reasonDisplayText(text: string, locale: Locale = 'es'): string {
    if (locale !== 'en') return text;
    if (text === PREVIOUS_MONTH_REASON) return "It was in the previous month's selection";
    const score = /^Score (\S+)\/100 con confianza (.+)$/.exec(text);
    if (score) {
        const level = CONFIDENCE_EN[score[2].trim().toLowerCase()] ?? score[2];
        return `Score ${score[1]}/100 with ${level} confidence`;
    }
    for (const [pattern, render] of SIGNAL_REASONS_EN) {
        const m = pattern.exec(text);
        if (m) return render(m);
    }
    return text;
}

/** Cifra es-ES («12.345,6», «+4,2») en formato en-US («12,345.6», «+4.2»). */
function esToEnNumber(value: string): string {
    return value.replace(/\./g, '\u0007').replace(/,/g, '.').replace(/\u0007/g, ',');
}

const REGIME_EN: Record<string, string> = {
    'pánico': 'panic',
    'aversión al riesgo alta': 'high risk aversion',
    'tensión moderada': 'moderate stress',
    'complacencia/calma': 'complacency/calm',
};

const n = esToEnNumber;
const pluralEn = (count: string, one: string, many: string) => `${n(count)} ${count === '1' ? one : many}`;

/**
 * Motivos del embudo (lib/actions/propicks-funnel.actions.ts) y detalle de las
 * señales de mercado (lib/utils/propicksSignals.ts). El valor crudo «(valor X)»
 * se conserva tal cual (regla R5 de trazabilidad).
 */
const SIGNAL_REASONS_EN: Array<[RegExp, (m: RegExpExecArray) => string]> = [
    [/^Marco de calidad (\d+)\/(\d+) criterios superados según fundamentales auditados$/,
        (m) => `Quality framework: ${m[1]}/${m[2]} criteria passed on audited fundamentals`],
    [/^CFROI (\S+) % vs WACC (\S+) %: spread de (\S+) puntos$/,
        (m) => `CFROI ${n(m[1])}% vs WACC ${n(m[2])}%: spread of ${n(m[3])} points`],
    [/^Ingresos creciendo al (\S+) % anual \(5 años\)$/, (m) => `Revenue growing ${n(m[1])}% a year (5 years)`],
    [/^Margen FCF medio del (\S+) % \(5 años\)$/, (m) => `Average FCF margin of ${n(m[1])}% (5 years)`],
    [/^Sorpresa media de beneficios (\S+) % en (\S+) trimestres? hasta (.+) \(valor (\S+)\)$/,
        (m) => `Average earnings surprise ${n(m[1])}% over ${pluralEn(m[2], 'quarter', 'quarters')} through ${m[3]} (value ${m[4]})`],
    [/^Compra neta insider: (\S+) compras? frente a (\S+) ventas? en 90 días hasta (.+) \(valor (\S+)\)$/,
        (m) => `Net insider buying: ${pluralEn(m[1], 'buy', 'buys')} vs ${pluralEn(m[2], 'sale', 'sales')} in 90 days through ${m[3]} (value ${m[4]})`],
    [/^Interés en corto FINRA de (\S+) acciones a (.+) \(valor (\S+)\)$/,
        (m) => `FINRA short interest of ${n(m[1])} shares as of ${m[2]} (value ${m[3]})`],
    [/^VIX en (\S+) el (\S+) \(régimen de (.+)\) \(valor (\S+)\)$/,
        (m) => `VIX at ${n(m[1])} on ${m[2]} (${REGIME_EN[m[3]] ?? m[3]} regime) (value ${m[4]})`],
];

export function toSnapshotPick(pick: ProPick): SnapshotPick {
    return {
        symbol: pick.symbol,
        company: pick.company,
        score: pick.score,
        confidence: pick.confidence,
        confidenceLevel: pick.confidenceLevel,
        reasons: pickReasons(pick),
        facts: { ...(pick.facts ?? {}) },
        asOf: pick.asOf,
    };
}

export function buildMonthlySnapshot(
    picks: ProPick[],
    strategyId: string,
    month: string = monthKey(),
    generatedAt: string = new Date().toISOString(),
): MonthlySnapshot {
    return {
        kind: 'cavaai-propicks-monthly-snapshot',
        version: 1,
        month,
        strategyId,
        generatedAt,
        picks: picks.map(toSnapshotPick),
    };
}

export interface RebalanceMove {
    symbol: string;
    company: string;
    reason: TraceableReason;
}

export interface RebalanceDiff {
    entered: RebalanceMove[];
    exited: RebalanceMove[];
    kept: string[];
}

/**
 * Diff entra/sale entre la selección actual y el snapshot del mes anterior.
 * Sin snapshot previo: todo es «entra» respecto a vacío y `hasPrevious` es false,
 * para que la UI lo diga honestamente en lugar de inventar un mes anterior.
 */
export function diffSnapshots(
    current: ProPick[],
    previous: MonthlySnapshot | null | undefined,
): RebalanceDiff & { hasPrevious: boolean } {
    if (!previous || !Array.isArray(previous.picks)) {
        return {
            entered: current.map((p) => ({
                symbol: p.symbol,
                company: p.company,
                reason: pickReason(p),
            })),
            exited: [],
            kept: [],
            hasPrevious: false,
        };
    }
    const prevBySymbol = new Map(previous.picks.map((p) => [p.symbol, p]));
    const currBySymbol = new Map(current.map((p) => [p.symbol, p]));
    const entered: RebalanceMove[] = [];
    const exited: RebalanceMove[] = [];
    const kept: string[] = [];
    for (const pick of current) {
        if (prevBySymbol.has(pick.symbol)) kept.push(pick.symbol);
        else entered.push({ symbol: pick.symbol, company: pick.company, reason: pickReason(pick) });
    }
    for (const prev of previous.picks) {
        if (!currBySymbol.has(prev.symbol)) {
            const reason = prev.reasons?.[0] ?? { text: PREVIOUS_MONTH_REASON };
            exited.push({ symbol: prev.symbol, company: prev.company, reason });
        }
    }
    return { entered, exited, kept, hasPrevious: true };
}

export { isMonthlySnapshot, previousSnapshotError, previousSnapshotRejection } from './snapshotValidation';
