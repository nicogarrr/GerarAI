import Link from 'next/link';
import type { TranslateFn } from '@/lib/i18n/translate';
import type { OpportunityRow, UnifiedViewState } from '@/lib/propicks/unified';
import { UNIFIED_ELIGIBILITY_KEYS, UnifiedStateNotice, unifiedMissingLabel } from './UnifiedStateNotice';

interface OpportunitiesViewProps {
    t: TranslateFn;
    view: UnifiedViewState;
    rows: OpportunityRow[];
}

function OpportunityCard({ t, row, missing }: { t: TranslateFn; row: OpportunityRow; missing: string }) {
    const eligibilityKey = Object.hasOwn(UNIFIED_ELIGIBILITY_KEYS, row.eligibility) ? UNIFIED_ELIGIBILITY_KEYS[row.eligibility as keyof typeof UNIFIED_ELIGIBILITY_KEYS] : undefined;
    return (
        <article className="rounded-xl border border-gray-700/60 bg-gray-900/60 p-4">
            <header className="min-w-0">
                <h3 className="text-sm font-bold text-gray-200">{row.ticker}</h3>
                {row.name && row.name.trim().toUpperCase() !== row.ticker.toUpperCase() ? (
                    <p className="truncate text-xs text-gray-500">{row.name}</p>
                ) : null}
            </header>
            <dl className="mt-2 grid grid-cols-3 gap-2 text-xs">
                <div>
                    <dt className="text-gray-500">{t('propicks.unified.colQuality')}</dt>
                    <dd className="text-gray-200">
                        {row.qualityScore === null || row.qualityPassed === null
                            ? missing
                            : row.qualityPassed === true
                              ? t('propicks.unified.qualityPassed')
                              : t('propicks.unified.qualityNotPassed')}
                    </dd>
                </div>
                <div>
                    <dt className="text-gray-500">{t('propicks.unified.colValuation')}</dt>
                    <dd className="text-gray-200">
                        {row.valuationStatus === 'ok' && row.valuationPrice !== null ? t('propicks.unified.valuationValid') : missing}
                    </dd>
                </div>
                <div>
                    <dt className="text-gray-500">{t('propicks.unified.colDca')}</dt>
                    <dd>
                        {row.dcaLevel === null || row.dcaPeriodState === null ? (
                            <span className="text-gray-200">{missing}</span>
                        ) : (
                            <span className={`inline-flex rounded-full border px-2 py-0.5 text-xs ${row.dcaPeriodState === 'confirmed' ? 'border-emerald-800 text-emerald-300' : 'border-amber-800 text-amber-300'}`}>
                                {row.dcaPeriodState === 'confirmed' ? t('propicks.unified.dcaConfirmed') : t('propicks.unified.dcaForming')}
                            </span>
                        )}
                    </dd>
                </div>
            </dl>
            <p className="mt-3">
                <Link href={`/research/${encodeURIComponent(row.ticker)}`} className="text-xs text-gray-300 underline-offset-2 hover:underline">
                    {(eligibilityKey ? t(eligibilityKey) : t('propicks.unified.openFile'))} →
                </Link>
            </p>
        </article>
    );
}

/** Oportunidades (wireframes 01-05): el estado lo decide el contrato y los
    avisos son de Veracidad; las ausencias se declaran, nunca se inventan. */
export default function OpportunitiesView({ t, view, rows }: OpportunitiesViewProps) {
    const missing = unifiedMissingLabel(t);
    const isMain = (row: OpportunityRow) => row.eligibility === 'investigate' || row.eligibility === 'quality_waiting_price';
    const main = rows.filter(isMain);
    const out = rows.filter((row) => !isMain(row));
    return (
        <section className="space-y-4">
            <header>
                <p className="text-xs uppercase tracking-wide text-gray-500">ProPicks</p>
                <h2 className="text-lg font-bold text-gray-100">{t('propicks.unified.heading')}</h2>
                <p className="text-sm text-gray-400">{t('propicks.unified.subheading')}</p>
            </header>
            {view.state !== 'ok' ? (
                <UnifiedStateNotice t={t} state={view.state} errorKind={view.errorKind} affectedBlocks={view.affectedBlocks} asOf={view.asOf} />
            ) : null}
            {main.length > 0 ? (
                <div className="grid gap-3 md:grid-cols-2">
                    {main.map((row) => <OpportunityCard key={row.instrumentId} t={t} row={row} missing={missing} />)}
                </div>
            ) : null}
            {out.length > 0 ? (
                <details className="rounded-xl border border-gray-700/60 p-4">
                    <summary className="cursor-pointer text-sm font-semibold text-gray-300">{t('propicks.unified.outOfMainTitle')}</summary>
                    <p className="mt-1 text-xs text-gray-500">{t('propicks.unified.outOfMainNote')}</p>
                    <div className="mt-3 grid gap-3 md:grid-cols-2">
                        {out.map((row) => <OpportunityCard key={row.instrumentId} t={t} row={row} missing={missing} />)}
                    </div>
                </details>
            ) : null}
        </section>
    );
}
