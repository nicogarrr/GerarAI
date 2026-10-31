'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { Button } from '@/components/ui/button';
import { Loader2, RefreshCw } from 'lucide-react';
import { toast } from 'sonner';
import { syncPortfolioDividends } from '@/lib/actions/portfolio.actions';
import { showErrorToast } from '@/lib/toast';
import { useT } from '@/lib/i18n/client';

export default function SyncDividendsButton({ userId }: { userId: string }) {
    const ti = useT();
    const [busy, setBusy] = useState(false);
    const router = useRouter();

    async function run() {
        try {
            setBusy(true);
            await syncPortfolioDividends(userId);
            router.refresh();
            toast.success(ti('portfolio.syncDividends.toast'));
        } catch (error) {
            showErrorToast(error, { onRetry: run });
        } finally {
            setBusy(false);
        }
    }

    return (
        <Button variant="outline" size="sm" onClick={run} disabled={busy} aria-busy={busy}
            className="border-gray-600 hover:bg-gray-700 text-gray-200">
            {busy ? <Loader2 aria-hidden="true" className="mr-2 h-4 w-4 animate-spin" /> : <RefreshCw aria-hidden="true" className="mr-2 h-4 w-4" />}
            {ti('portfolio.syncDividends.label')}
        </Button>
    );
}
