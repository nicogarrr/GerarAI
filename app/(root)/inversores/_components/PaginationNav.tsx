'use client';

import Link from 'next/link';
import { useT } from '@/lib/i18n/client';
import type { PaginationProps } from './Pagination';

function pageHref(basePath: string, page: number, params: Record<string, string>): string {
    const query = new URLSearchParams(params);
    if (page > 1) query.set('pagina', String(page));
    const text = query.toString();
    return text ? `${basePath}?${text}` : basePath;
}

export function PaginationNav({ page, total, basePath, params = {} }: PaginationProps) {
    const t = useT();
    const linkClass = 'inline-flex min-h-[44px] items-center rounded-lg border border-gray-800 px-3 py-1.5 text-sm text-gray-300 hover:border-gray-700 sm:min-h-0';
    const offClass = 'rounded-lg border border-gray-900 px-3 py-1.5 text-sm text-gray-700';
    return (
        <nav aria-label={t('investors.pagination.aria')} className="flex items-center justify-between gap-4">
            {page > 1 ? (
                <Link className={linkClass} href={pageHref(basePath, page - 1, params)} rel="prev">
                    {t('ui.pagination.prev')}
                </Link>
            ) : (
                <span aria-disabled="true" className={offClass}>{t('ui.pagination.prev')}</span>
            )}
            <span className="text-sm text-gray-500">
                {t('investors.pagination.pageOf', { page, total })}
            </span>
            {page < total ? (
                <Link className={linkClass} href={pageHref(basePath, page + 1, params)} rel="next">
                    {t('ui.pagination.next')}
                </Link>
            ) : (
                <span aria-disabled="true" className={offClass}>{t('ui.pagination.next')}</span>
            )}
        </nav>
    );
}
