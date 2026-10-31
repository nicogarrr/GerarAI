/**
 * «Crecimiento implícito» (idea Jera Value / Tracking Alpha) en la caja de Reverse DCF:
 * qué crecimiento perpetuo descuenta el precio, de qué años sale el valor y cómo cambia
 * el crecimiento exigido si el WACC o el margen FCF se mueven un poco.
 */

export type ImpliedValueSplit = { years_1_5: number; years_6_10: number; years_11_plus: number };
export type ImpliedSensitivity = { wacc: number[]; fcf_margin: number[]; required_growth: Array<Array<number | null>> };

const pct = (value: number, digits = 1) => `${(value * 100).toLocaleString('es-ES', { minimumFractionDigits: digits, maximumFractionDigits: digits })} %`;

export interface ImpliedGrowthView {
    perpetual: string | null;
    split: Array<{ label: string; share: string; width: number }>;
    grid: { columns: string[]; rows: Array<{ label: string; cells: Array<{ text: string; base: boolean }> }> } | null;
}

/** Textos ya formateados para la ficha; null en cada parte si el dato no existe (nunca se inventa). */
export function impliedGrowthView(input: { implied_perpetual_growth?: number | null; value_split?: ImpliedValueSplit | null; sensitivity?: ImpliedSensitivity | null }): ImpliedGrowthView {
    const perpetual = typeof input.implied_perpetual_growth === 'number' && Number.isFinite(input.implied_perpetual_growth)
        ? pct(input.implied_perpetual_growth)
        : null;
    const s = input.value_split;
    const split = s
        ? ([['Años 1–5', s.years_1_5], ['Años 6–10', s.years_6_10], ['Año 11 en adelante', s.years_11_plus]] as const).map(([label, share]) => ({
            label,
            share: pct(share, 0),
            width: Math.max(0, Math.min(100, Math.round(share * 100))),
        }))
        : [];
    const g = input.sensitivity;
    const grid = g && g.wacc.length === 3 && g.fcf_margin.length === 3
        ? {
            columns: g.fcf_margin.map((margin) => `Margen ${pct(margin)}`),
            rows: g.wacc.map((wacc, i) => ({
                label: `WACC ${pct(wacc)}`,
                cells: g.fcf_margin.map((_, j) => {
                    const value = g.required_growth[i]?.[j];
                    return { text: typeof value === 'number' ? pct(value) : '—', base: i === 1 && j === 1 };
                }),
            })),
        }
        : null;
    return { perpetual, split, grid };
}
