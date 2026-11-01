'use client';

import Link from 'next/link';
import { MoreHorizontal } from 'lucide-react';

import { GuideBrainButton } from '@/components/research/GuideBrainButton';
import { DecisionJournalEntryLink } from '@/components/research/DecisionJournalEntryLink';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { useT } from '@/lib/i18n/client';

const ITEM = 'flex min-h-[44px] items-center text-sm text-teal-300 hover:text-teal-200';

/** Enlaces secundarios de la ficha en un único menú de cabecera (antes seis enlaces sueltos). */
export default function CompanyActionsMenu({ ticker, changeCount }: { ticker: string; changeCount: number }) {
    const t = encodeURIComponent(ticker);
    const tr = useT();
    return (
        <Popover>
            <PopoverTrigger asChild>
                <button
                    aria-label={tr('research.companyMenu.moreActions')}
                    className="flex size-11 items-center justify-center rounded-lg text-gray-300 hover:text-teal-300"
                    type="button"
                >
                    <MoreHorizontal aria-hidden="true" className="h-5 w-5" />
                </button>
            </PopoverTrigger>
            <PopoverContent align="end" className="max-h-[min(75dvh,34rem)] w-60 overflow-y-auto border-gray-700 bg-gray-900 p-2">
                <nav aria-label={tr('research.companyMenu.navLabel')} className="flex flex-col">
                    <GuideBrainButton ticker={ticker} />
                    <Link className={ITEM} href={`/research/${t}?view=seguimiento`}>
                        {tr('research.companyMenu.whatChanged')}{changeCount ? ` (${changeCount})` : ''}
                    </Link>
                    <DecisionJournalEntryLink className={ITEM} ticker={ticker} />
                    <p className="mt-1 border-t border-gray-700/60 px-0 pb-0.5 pt-2 text-xs font-semibold uppercase tracking-wide text-gray-500">{tr('research.companyMenu.deepAnalysis')}</p>
                    <Link className={ITEM} href={`/research/${t}?view=finanzas#terminal`}>{tr('research.companyMenu.terminal')}</Link>
                    <Link className={ITEM} href={`/research/${t}?view=valoracion#supuestos`}>{tr('research.companyMenu.driverAssumptions')}</Link>
                    <Link className={ITEM} href={`/research/${t}?view=seguimiento#lecciones`}>{tr('research.companyMenu.decisionLessons')}</Link>
                    <Link className={ITEM} href={`/research/${t}?view=seguimiento#directiva`}>{tr('research.companyMenu.managementCredibility')}</Link>
                    <Link className={ITEM} href={`/research/${t}?view=finanzas#dilucion`}>{tr('research.companyMenu.dilution')}</Link>
                    <p className="mt-1 border-t border-gray-700/60 px-0 pb-0.5 pt-2 text-xs font-semibold uppercase tracking-wide text-gray-500">{tr('research.companyMenu.externalSignals')}</p>
                    <Link className={ITEM} href={`/research/${t}/shorts`}>{tr('research.companyMenu.publicShorts')}</Link>
                    <Link className={ITEM} href={`/research/news?ticker=${t}`}>{tr('research.companyMenu.news')}</Link>
                    <Link className={ITEM} href={`/insider?ticker=${t}`}>{tr('research.companyMenu.insiders')}</Link>
                    <Link className={ITEM} href={`/corporate-actions?ticker=${t}`}>{tr('research.companyMenu.dividends')}</Link>
                </nav>
            </PopoverContent>
        </Popover>
    );
}
