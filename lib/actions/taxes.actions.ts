'use server';

import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import { researchRequest } from '@/lib/research/client';
import { assertYear } from '@/lib/validation/pathParams';

export type TaxRecord = Record<string, unknown>;

/** GET /api/taxes/holdings — posiciones con base de coste para impuestos */
export async function getTaxHoldings(): Promise<TaxRecord[]> {
    await requireAuthenticatedUser();
    return researchRequest<TaxRecord[]>('/api/taxes/holdings');
}

/** GET /api/taxes/report/{fiscal_year} — reporte fiscal anual */
export async function getTaxReport(fiscalYear: number): Promise<TaxRecord> {
    await requireAuthenticatedUser();
    return researchRequest<TaxRecord>(`/api/taxes/report/${assertYear(fiscalYear, 'fiscalYear')}`);
}

/** POST /api/taxes/report/{fiscal_year}/regenerate — regenera el reporte fiscal */
export async function regenerateTaxReport(fiscalYear: number): Promise<TaxRecord> {
    await requireAuthenticatedUser();
    return researchRequest<TaxRecord>(`/api/taxes/report/${assertYear(fiscalYear, 'fiscalYear')}/regenerate`, {
        method: 'POST',
    });
}

/** GET /api/taxes/modelo720/{fiscal_year}/thresholds — umbrales 720 por categoría (tri-estado) */
export async function getModelo720Thresholds(fiscalYear: number): Promise<TaxRecord> {
    await requireAuthenticatedUser();
    return researchRequest<TaxRecord>(`/api/taxes/modelo720/${assertYear(fiscalYear, 'fiscalYear')}/thresholds`);
}

/** GET /api/taxes/modelo720/{fiscal_year}/file — fichero 720 (ayuda de cómputo) */
export async function getModelo720File(fiscalYear: number): Promise<TaxRecord> {
    await requireAuthenticatedUser();
    return researchRequest<TaxRecord>(`/api/taxes/modelo720/${assertYear(fiscalYear, 'fiscalYear')}/file`);
}

/** Vista previa del Modelo 100 con TME manual, sin guardar datos fiscales. */
export async function previewTaxFiling(fiscalYear: number, tmePercent: number): Promise<TaxRecord> {
    await requireAuthenticatedUser();
    if (!Number.isFinite(tmePercent) || tmePercent < 0 || tmePercent > 100) {
        throw new Error('El tipo medio efectivo debe estar entre 0 y 100 %.');
    }
    return researchRequest<TaxRecord>(`/api/taxes/report/${assertYear(fiscalYear, 'fiscalYear')}/preview`, {
        method: 'POST',
        body: JSON.stringify({ tme_percent: tmePercent }),
    });
}

export type TaxDeclarant = {
    nif: string;
    apellidos_nombre: string;
    numero_declaracion: string;
    telefono: string;
    filed_720_before: boolean | null;
    custody: Record<string, string>;
    partidas: string[];
};

export type TaxDeclarantInput = Partial<Omit<TaxDeclarant, 'partidas' | 'custody'>> & {
    custody?: Record<string, string | null>;
};

/** GET /api/taxes/declarant — datos del declarante y partidas a las que asignar custodia */
export async function getTaxDeclarant(): Promise<TaxDeclarant> {
    await requireAuthenticatedUser();
    return researchRequest<TaxDeclarant>('/api/taxes/declarant', { cache: 'no-store' });
}

/** PUT /api/taxes/declarant — guarda los datos que lee el Modelo 720 */
export async function saveTaxDeclarant(input: TaxDeclarantInput): Promise<TaxDeclarant> {
    await requireAuthenticatedUser();
    return researchRequest<TaxDeclarant>('/api/taxes/declarant', {
        method: 'PUT',
        body: JSON.stringify(input),
    });
}
