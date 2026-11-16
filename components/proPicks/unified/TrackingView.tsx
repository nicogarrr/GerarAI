import Link from 'next/link';
import type { TranslateFn } from '@/lib/i18n/translate';
import type { TrackingRow } from '@/lib/propicks/unified';
import { UNIFIED_REASON_KEYS, UnifiedStateNotice, unifiedMissingLabel } from './UnifiedStateNotice';

interface TrackingViewProps {
    t: TranslateFn;
    rows: TrackingRow[];
}

/** Seguimiento (wireframe 08): qué cambió desde la última revisión. Sin
    compras, ventas ni rebalanceo automático; los motivos de revisión son los
    del contrato, con textos de Veracidad. */
export default function TrackingView({ t, rows }: TrackingViewProps) {
    return (
        <section className="space-y-4">
            <header>
                <p className="text-xs uppercase tracking-wide text-gray-500">ProPicks / {t('propicks.unified.trackingTitle')}</p>
                <h2 className="text-lg font-bold text-gray-100">{t('propicks.unified.trackingTitle')}</h2>
                <p className="text-sm text-gray-400">{t('propicks.unified.trackingSubtitle')}</p>
            </header>
            {rows.length === 0 ? (
                <UnifiedStateNotice t={t} state="empty" />
            ) : (
                <div className="space-y-3">
                    {rows.map((row) => (
                        <article key={row.instrumentId} className="rounded-xl border border-gray-700/60 bg-gray-900/60 p-4">
                            <header className="flex min-w-0 flex-wrap items-center gap-2">
                                <h3 className="text-sm font-bold text-gray-200">
                                    {row.ticker} · {row.held ? t('propicks.unified.trackingFollow') : row.watched ? t('propicks.unified.trackingWait') : unifiedMissingLabel(t)}
                                </h3>
                                {row.reviewReasons.length > 0 ? (
                                    <span className="inline-flex rounded-full border border-amber-800 px-2 py-0.5 text-[11px] text-amber-300">
                                        {t('propicks.unified.reviewThesis')}
                                    </span>
                                ) : null}
                            </header>
                            {row.reviewReasons.length > 0 ? (
                                <ul className="mt-2 list-inside list-disc text-xs text-gray-400">
                                    {[...new Set(row.reviewReasons)].map((code) => (
                                        <li key={code}>
                                            {t(Object.hasOwn(UNIFIED_REASON_KEYS, code) ? UNIFIED_REASON_KEYS[code as keyof typeof UNIFIED_REASON_KEYS] : 'propicks.unifiedStates.unknownReason')}
                                        </li>
                                    ))}
                                </ul>
                            ) : null}
                            <p className="mt-3">
                                <Link href={`/research/${encodeURIComponent(row.ticker)}`} className="text-xs text-gray-300 underline-offset-2 hover:underline">
                                    {t('propicks.unified.openFile')} →
                                </Link>
                            </p>
                        </article>
                    ))}
                </div>
            )}
        </section>
    );
}
