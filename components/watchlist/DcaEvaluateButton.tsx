'use client';

import Link from 'next/link';
import { useEffect, useRef, useState } from 'react';
import { formatCountEs } from '@/lib/format';
import { useLocale, useT } from '@/lib/i18n/client';
import { useRouter } from 'next/navigation';
import { RefreshCw } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { getDcaManualJob, startDcaManualJob } from '@/lib/actions/dca-signals.actions';
import { showErrorToast } from '@/lib/toast';

/** Evaluación manual de las señales DCA (el backend la limita a una tanda de diez pendientes cada cinco minutos). */
export default function DcaEvaluateButton() {
    const router = useRouter();
    const t = useT();
    const locale = useLocale();
    const [loading, setLoading] = useState(false);

    const alive = useRef(true);
    const [status, setStatus] = useState<string | null>(null);
    useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);

    const handleClick = async () => {
        setLoading(true);
        try {
            const accepted = await startDcaManualJob();
            if (!accepted.success || !accepted.runId) {
                showErrorToast(accepted.message ?? t('watchlist.dca.run.startFailed'));
                return;
            }
            setStatus(t('watchlist.dca.run.accepted'));
            // Bounded polling. A pending job is not a failed evaluation.
            let res: Awaited<ReturnType<typeof getDcaManualJob>> = { success: true, status: 'running' };
            for (let attempt = 0; attempt < 60 && alive.current; attempt++) {
                await new Promise(resolve => setTimeout(resolve, 5000));
                if (!alive.current) return;
                res = await getDcaManualJob(accepted.runId);
                if (!res.success || res.status !== 'running') break;
            }
            if (!alive.current) return;
            if (res.success && res.status === 'running') {
                setStatus(t('watchlist.dca.run.background'));
                router.refresh();
                return;
            }
            if (res.status === 'interrupted') {
                setStatus(t('watchlist.dca.run.interrupted'));
                router.refresh();
                return;
            }
            if (res.success && res.summary) {
                const { evaluated, alerted, skipped, errors = [] } = res.summary;
                const parts = [formatCountEs(evaluated, t('watchlist.dca.run.evaluatedOne'), t('watchlist.dca.run.evaluatedOther'), locale), formatCountEs(alerted.length, t('watchlist.dca.run.newAlertOne'), t('watchlist.dca.run.newAlertOther'), locale)];
                if (skipped.length > 0) parts.push(t('watchlist.dca.run.skipped', { count: skipped.length }));
                if (res.summary.pending_remaining) parts.push(t('watchlist.dca.run.pending', { count: res.summary.pending_remaining }));
                if (errors.length > 0) {
                    parts.push(formatCountEs(errors.length, t('watchlist.dca.run.errorsOne'), t('watchlist.dca.run.errorsOther'), locale));
                    toast.warning(t('watchlist.dca.run.partial', { parts: parts.join(' · ') }));
                } else {
                    toast.success(t('watchlist.dca.run.updated', { parts: parts.join(' · ') }));
                }
                setStatus(null);
                router.refresh();
            } else {
                showErrorToast(res.message ?? t('watchlist.dca.run.failed'));
            }
        } catch (error) {
            showErrorToast(error);
        } finally {
            if (alive.current) setLoading(false);
        }
    };

    return (
        <div className="grid w-full gap-2 sm:w-auto">
        <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={handleClick}
            disabled={loading}
            aria-busy={loading}
            className="min-h-[44px] border-gray-700 text-xs text-gray-300"
        >
            <RefreshCw aria-hidden="true" className={`mr-1 h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
            {loading ? t('watchlist.dca.run.evaluating') : t('watchlist.dca.run.runNow')}
        </Button>
        {status && <p role="status" className="max-w-sm text-xs text-gray-300">{status}</p>}
        <p className="max-w-sm text-xs text-gray-400">{t('watchlist.dca.run.help')}</p>
        <Link href="/plan" className="inline-flex min-h-[44px] items-center text-xs text-teal-300">{t('watchlist.dca.run.planLink')}</Link>
        </div>
    );
}
