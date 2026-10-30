import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { DocumentsList, type DocumentRow } from '@/components/research/DocumentsList';
import { tierRankFuente } from '@/lib/labels';

const row = (partial: Partial<DocumentRow> & Pick<DocumentRow, 'id' | 'title'>): DocumentRow => ({
    url: null,
    tier: 'Fuente sin clasificar',
    tierRank: tierRankFuente('tier_unknown'),
    type: 'Documento',
    published: 'fecha desconocida',
    publishedTs: null,
    ...partial,
});

describe('tierRankFuente', () => {
    it('ordena la fuente primaria antes que los artefactos internos o sin clasificar', () => {
        expect(tierRankFuente('tier_1_regulatory')).toBeLessThan(tierRankFuente('tier_5_data_provider'));
        expect(tierRankFuente('tier_5_data_provider')).toBeLessThan(tierRankFuente('tier_unknown'));
        expect(tierRankFuente('clave_futura_desconocida')).toBe(tierRankFuente('tier_unknown'));
    });
});

describe('DocumentsList orden', () => {
    it('muestra los filings oficiales antes que los artefactos internos aunque lleguen más nuevos', () => {
        render(
            <DocumentsList
                documents={[
                    row({ id: 1, title: 'Yahoo Finance market inputs 2026-10-29', tierRank: tierRankFuente('tier_5_data_provider'), tier: 'Proveedor de datos · T5', publishedTs: '2026-10-29' }),
                    row({ id: 2, title: '10-K 2025', tierRank: tierRankFuente('tier_1_regulatory'), tier: 'Regulatoria · T1', publishedTs: '2026-02-01' }),
                    row({ id: 3, title: 'WACC policy assumptions', publishedTs: '2026-10-28' }),
                ]}
            />,
        );
        const ordered = Array.from(document.querySelectorAll('.font-medium')).map((el) => el.textContent);
        expect(ordered[0]).toBe('10-K 2025');
        expect(ordered.indexOf('Yahoo Finance market inputs 2026-10-29')).toBeLessThan(ordered.indexOf('WACC policy assumptions'));
        expect(screen.queryAllByRole('link').length).toBe(0); // sin URL no hay enlace (la ficha queda como texto)
    });

    it('dentro del mismo tier ordena por fecha descendente y sin fecha al final', () => {
        render(
            <DocumentsList
                documents={[
                    row({ id: 1, title: '8-K antiguo', tierRank: tierRankFuente('tier_1_regulatory'), tier: 'Regulatoria · T1', publishedTs: '2026-01-10' }),
                    row({ id: 2, title: '8-K sin fecha', tierRank: tierRankFuente('tier_1_regulatory'), tier: 'Regulatoria · T1' }),
                    row({ id: 3, title: '8-K reciente', tierRank: tierRankFuente('tier_1_regulatory'), tier: 'Regulatoria · T1', publishedTs: '2026-10-01' }),
                ]}
            />,
        );
        const ordered = Array.from(document.querySelectorAll('.font-medium')).map((el) => el.textContent);
        expect(ordered).toEqual(['8-K reciente', '8-K antiguo', '8-K sin fecha']);
    });
});
