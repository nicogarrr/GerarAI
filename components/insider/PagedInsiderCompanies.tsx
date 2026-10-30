'use client';

import { useState } from 'react';
import { useT } from '@/lib/i18n/client';
import { Pager } from '@/components/research/Pager';
import { CompanyCard } from '@/components/insider/InsiderOperationsView';
import type { InsiderOperationsCompany } from '@/lib/actions/insider.actions';

const PAGE_SIZE = 10;

/** Lista paginada de empresas con operaciones insider: sin páginas, cartera +
 *  watchlist pintaban cientos de tarjetas seguidas y el scroll móvil era
 *  interminable (regla de Nico: paginador arriba y abajo, 2026-10-07). */
export function PagedInsiderCompanies({ companies }: { companies: InsiderOperationsCompany[] }) {
    const t = useT();
    const [page, setPage] = useState(1);
    const pages = Math.max(1, Math.ceil(companies.length / PAGE_SIZE));
    const currentPage = Math.min(page, pages);
    const visible = companies.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE);
    const pager = pages > 1 ? (
        <Pager label={t('insider.operations.pagerUnit')} onPage={setPage} page={currentPage} pages={pages} total={companies.length} />
    ) : null;
    return (
        <>
            {pager}
            {visible.map((company) => <CompanyCard key={company.ticker} company={company} />)}
            {pager}
        </>
    );
}
