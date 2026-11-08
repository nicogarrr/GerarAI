import { describe, expect, it } from 'vitest';

import { isFinanciallyRelevant } from '@/lib/newsRelevance';

// Titulares sin compañía («Mercado general») solo se muestran si hablan de
// mercados, economía o empresas: lista determinista, sin modelo.

describe('isFinanciallyRelevant', () => {
    it('con compañía asociada siempre es relevante', () => {
        expect(isFinanciallyRelevant({ headline: 'Cualquier titular', related: 'TSLA' })).toBe(true);
        expect(isFinanciallyRelevant({ headline: 'Cualquier titular', related: ' tsla ' })).toBe(true);
    });

    it('término financiero en el titular: relevante', () => {
        expect(isFinanciallyRelevant({ headline: 'Fed raises interest rates amid inflation' })).toBe(true);
        expect(isFinanciallyRelevant({ headline: 'El IBEX sube por los resultados bancarios' })).toBe(true);
    });

    it('término financiero solo en el resumen: relevante', () => {
        expect(isFinanciallyRelevant({ headline: 'Un anuncio importante', summary: 'The company declared a dividend.' })).toBe(
            true,
        );
    });

    it('consejos de vida que mencionan dinero no son noticia de mercado', () => {
        expect(isFinanciallyRelevant({ headline: 'Parenting coach shares tips to raise kids on a budget' })).toBe(false);
        expect(isFinanciallyRelevant({ headline: 'Cómo ahorrar en la crianza de los peques' })).toBe(false);
    });

    it('consejos de vida que sí hablan de mercados pasan el filtro', () => {
        expect(isFinanciallyRelevant({ headline: 'Parenting coach explains inflation to families' })).toBe(true);
    });

    it('titular sin relación con mercados: no relevante', () => {
        expect(isFinanciallyRelevant({ headline: 'Helicopter tours over the canyon reopen' })).toBe(false);
        expect(isFinanciallyRelevant({ headline: 'Local team wins the championship final' })).toBe(false);
    });
});
