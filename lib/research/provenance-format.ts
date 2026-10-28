// @ts-expect-error TS5097: explicit extension for node strip-types guards.
import { formatMarketCapUsd } from '../format.ts';

/**
 * Fichas «etiqueta / valor» para los inputs inferidos de una tesis (F4).
 * Antes salian claves crudas (addressable_subscribers) y decimales largos
 * (0.1442999). Aqui: etiqueta en español y valor formateado, con un unico
 * criterio: dinero en dolares estilo ingles ($4.87B), porcentajes con coma
 * (14,4 %), cantidades con separador de miles.
 * Sin imports a proposito: se prueba con node --experimental-strip-types.
 */

const NA = "N/D";

const RATIO_UNITS = new Set(["decimal", "ratio", "fraction", "fraccion", "fracción"]);
const PERCENT_UNITS = new Set(["%", "pct", "percent", "percentage", "porcentaje"]);
const UNIT_NAMES: Record<string, string> = { shares: "acciones", share: "acción", x: "x" };

function toNumber(value: number | string | null | undefined): number | null {
    if (value === null || value === undefined || value === "") return null;
    if (typeof value === "string" && value.trim() === "") return null;
    const parsed = typeof value === "number" ? value : Number(String(value).replace(/,/g, ""));
    return Number.isFinite(parsed) ? parsed : null;
}

function isCurrencyCode(unit: string): boolean {
    if (!/^[A-Z]{3}$/.test(unit)) return false;
    try {
        new Intl.NumberFormat("en-US", { style: "currency", currency: unit });
        return true;
    } catch {
        return false;
    }
}

/** Dinero en la divisa DECLARADA, escala inglesa: "$4.87B", "EUR 14.40" segun Intl en-US. */
export function formatMoneyShort(value: number, currency: string): string {
    const abs = Math.abs(value);
    if (currency === "USD" && abs >= 1e6) return formatMarketCapUsd(value);
    return new Intl.NumberFormat("en-US", {
        style: "currency",
        currency,
        notation: abs >= 1e6 ? "compact" : "standard",
        maximumFractionDigits: abs >= 1e6 ? 2 : abs >= 100 ? 0 : 2,
        // Estilo ingles: escala compacta SIEMPRE con 2 decimales
        // ($4.87B, no $4.8B ni $4.5B). Sin minimum, Intl recorta ceros.
        minimumFractionDigits: abs >= 1e6 ? 2 : abs >= 100 ? 0 : 2,
    }).format(value);
}

function plainNumber(parsed: number): string {
    return new Intl.NumberFormat("es-ES", {
        notation: Math.abs(parsed) >= 1e6 ? "compact" : "standard",
        maximumFractionDigits: 2,
    }).format(parsed);
}

/**
 * Valor legible de un input de la tesis. SOLO usa la unidad que declara el
 * dato: nunca adivina por el nombre de la clave ni por la magnitud. Sin unidad
 * declarada el numero va tal cual, sin simbolo ni %.
 *  - unidad "decimal"/"ratio": fraccion -> porcentaje (0,144 -> 14,4 %)
 *  - unidad "%": ya viene en porcentaje (25 -> 25,0 %)
 *  - codigo ISO (USD, EUR): importe en esa divisa
 *  - otra unidad: numero + unidad
 */
export function formatProvenanceValue(
    value: number | string | null | undefined,
    unit?: string | null,
): string {
    const parsed = toNumber(value);
    if (parsed === null) {
        if (typeof value === "string" && value.trim() !== "") return value.trim();
        return NA;
    }
    const rawUnit = (unit ?? "").trim();
    const lower = rawUnit.toLowerCase();
    if (RATIO_UNITS.has(lower) || PERCENT_UNITS.has(lower)) {
        const ratio = PERCENT_UNITS.has(lower) ? parsed / 100 : parsed;
        return new Intl.NumberFormat("es-ES", {
            style: "percent",
            minimumFractionDigits: 1,
            maximumFractionDigits: 1,
        }).format(ratio);
    }
    if (isCurrencyCode(rawUnit)) return formatMoneyShort(parsed, rawUnit);
    if (['pure', 'unitless', 'dimensionless', 'count', 'number', 'units', 'unit'].includes(lower)) return plainNumber(parsed);
    const perUnit = /^([A-Za-z]{3})_per_unit$/.exec(rawUnit);
    if (perUnit) return `${plainNumber(parsed)} ${perUnit[1].toUpperCase()} por unidad`;
    if (rawUnit) return `${plainNumber(parsed)} ${UNIT_NAMES[lower] ?? rawUnit}`;
    return plainNumber(parsed);
}

/** "addressable_subscribers" -> "Suscriptores direccionables" (primera letra en mayuscula). */
export function capitalizeLabel(label: string): string {
    const clean = label.trim();
    return clean ? clean.charAt(0).toUpperCase() + clean.slice(1) : clean;
}
