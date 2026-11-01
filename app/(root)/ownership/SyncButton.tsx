'use client';

import { useState, useTransition } from 'react';
import { RefreshCw } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { syncOwnershipManagers } from '@/lib/actions/ownership.actions';
import { useT } from '@/lib/i18n/client';

export default function SyncButton() {
    const t = useT();
    const [pending, startTransition] = useTransition();
    const [feedback, setFeedback] = useState<string | null>(null);
    return (
        <div className="space-y-2">
            <Button
                size="sm"
                variant="ghost"
                className="text-gray-400"
                disabled={pending}
                onClick={() => startTransition(async () => {
                    setFeedback(null);
                    try {
                        const result = await syncOwnershipManagers();
                        const failed = result.results.filter((r) => r.status !== 'ok');
                        if (failed.length === 0) {
                            setFeedback(t('ownership.sync.done'));
                        } else {
                            const reason = failed[0]?.reason?.split('\n')[0] ?? t('ownership.sync.unknownError');
                            setFeedback(t('ownership.sync.failed', { manager: failed[0]?.manager ?? t('ownership.sync.theManager'), reason }));
                        }
                    } catch {
                        setFeedback(t('ownership.sync.error'));
                    }
                })}
            >
                <RefreshCw className={`h-4 w-4 ${pending ? 'animate-spin' : ''}`} />
                {pending ? t('ownership.sync.syncing') : t('ownership.page.sync')}
            </Button>
            {feedback ? <p className="text-xs text-amber-300">{feedback}</p> : null}
        </div>
    );
}
