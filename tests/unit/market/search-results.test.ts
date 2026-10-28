// @vitest-environment node
import { describe, expect, it } from 'vitest';

import { exactSymbolFirst, marketPriority, onePerIssuer } from '@/lib/market/search-results';

const r = (symbol: string, description?: string) => ({ symbol, description });
const syms = (rows: { symbol: string }[]) => rows.map((x) => x.symbol);

describe('onePerIssuer', () => {
    it('oculta el ADR desnudo si existe el listado base con sufijo del mismo emisor', () => {
        const rows = [r('ASML', 'ASML Holding NV'), r('ASML.AS', 'ASML Holding N.V.')];
        expect(syms(onePerIssuer(rows))).toEqual(['ASML.AS']);
    });
    it('NO funde emisores distintos con el mismo ticker base (Almonty vs Almirall)', () => {
        const rows = [r('ALM', 'Almonty Industries'), r('ALM.MC', 'Almirall SA')];
        expect(syms(onePerIssuer(rows))).toEqual(['ALM', 'ALM.MC']);
    });
    it('un ticker exacto escrito gana al listado con sufijo del mismo emisor', () => {
        const rows = [r('KO', 'Coca-Cola Co'), r('KO.MX', 'Femsa SAB'), r('KO.VI', 'Coca Cola Co')];
        expect(syms(onePerIssuer(rows, 'ko'))).toEqual(['KO', 'KO.MX']); // KO.MX es otro emisor (primer término distinto) y se conserva; KO.VI se oculta
    });
    it('sin descripción no se oculta nada', () => {
        expect(syms(onePerIssuer([r('AAA'), r('AAA.L')]))).toEqual(['AAA', 'AAA.L']);
    });
});

describe('orden de resultados', () => {
    it('exactSymbolFirst sube la coincidencia exacta (por símbolo o displaySymbol) y conserva el resto', () => {
        const rows = [{ symbol: 'SAP.TO' }, { symbol: 'SAPX', displaySymbol: 'SAP' }, { symbol: 'SAP' }];
        expect(syms(exactSymbolFirst(rows, ' sap '))).toEqual(['SAPX', 'SAP', 'SAP.TO']);
        expect(exactSymbolFirst(rows, '  ')).toBe(rows);
    });
    it('marketPriority: exacto, luego EE. UU., luego bolsas líquidas, luego el resto, estable', () => {
        const rows = [r('CPT.BK'), r('CPT.MC'), r('CPT'), r('CPT.XX'), r('CPT.L')];
        expect(syms(marketPriority(rows, 'cpt.l'))).toEqual(['CPT.L', 'CPT', 'CPT.MC', 'CPT.BK', 'CPT.XX']);
        // sin exacto: US primero y el orden del proveedor se mantiene dentro de cada grupo
        expect(syms(marketPriority([r('A.BK'), r('A.ZZ'), r('A.MC'), r('A')], ''))).toEqual(['A', 'A.MC', 'A.BK', 'A.ZZ']);
    });
});
