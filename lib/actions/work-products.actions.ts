'use server';

import { requireAuthenticatedUser } from '@/lib/auth/require-user';
import { jsonBody, researchRequest } from '@/lib/research/client';
import { ValidationError } from '@/lib/types/errors';

export type WorkProductType =
    | 'one_page_memo'
    | 'full_thesis'
    | 'earnings_review'
    | 'valuation_memo'
    | 'capital_allocation_analysis'
    | 'comparables'
    | 'portfolio_review'
    | 'risk_report';

export interface WorkProductInput {
    product_type: WorkProductType;
    ticker?: string | null;
    years: number;
}

/** Respuesta de /api/work-products/generate. `markdown` es el documento
 *  legible en español que renderiza el diálogo (QA /research). */
export type WorkProductRecord = {
    product_type?: string;
    title?: string;
    ticker?: string | null;
    markdown?: string;
    manifest?: {
        data_as_of?: string | null;
        source_count?: number;
        warnings?: string[];
        sources?: Array<{ citation: string; title: string }>;
    };
    [key: string]: unknown;
};

/** POST /api/work-products/generate — genera un work product (memo, tesis, review...) */
export async function generateWorkProduct(input: WorkProductInput): Promise<WorkProductRecord> {
    await requireAuthenticatedUser();

    const productType = input.product_type?.trim() as WorkProductType | undefined;
    if (!productType) {
        throw new ValidationError('El tipo de work product es obligatorio', 'product_type');
    }
    const ticker = input.ticker?.trim().toUpperCase() || null;
    const years = Number.isFinite(input.years) && input.years > 0 ? input.years : 10;

    return researchRequest<WorkProductRecord>('/api/work-products/generate', {
        method: 'POST',
        body: jsonBody({
            product_type: productType,
            ticker,
            years,
        }),
    });
}