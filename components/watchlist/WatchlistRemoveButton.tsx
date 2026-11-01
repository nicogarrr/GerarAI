'use client';

import { useState } from 'react';
import { useT } from '@/lib/i18n/client';
import { Button } from '@/components/ui/button';
import { Trash2 } from 'lucide-react';
import { removeFromWatchlist } from '@/lib/actions/watchlist.actions';
import { useRouter } from 'next/navigation';
import { toast } from 'sonner';
import { showErrorToast } from '@/lib/toast';
import { useConfirmWatchlistRemoval } from '@/components/watchlist/WatchlistMembership';

interface WatchlistRemoveButtonProps {
    symbol: string;
}

export default function WatchlistRemoveButton({ symbol }: WatchlistRemoveButtonProps) {
    const router = useRouter();
    const t = useT();
    const confirmRemoval = useConfirmWatchlistRemoval();
    const [loading, setLoading] = useState(false);

    const handleRemove = async () => {
        setLoading(true);
        try {
            const res = await removeFromWatchlist(symbol);
            if (res.success) {
                confirmRemoval(symbol);
                toast.success(t('watchlist.remove.removed', { symbol }));
                router.refresh();
            } else {
                showErrorToast(res.message ?? t('watchlist.remove.failed'), {
                    onRetry: handleRemove,
                });
            }
        } catch (error) {
            showErrorToast(error, { onRetry: handleRemove });
        } finally {
            setLoading(false);
        }
    };

    return (
        <Button
            variant="ghost"
            size="icon"
            onClick={handleRemove}
            disabled={loading}
            aria-busy={loading}
            aria-label={t('watchlist.remove.label', { symbol })}
            className="inline-flex min-h-[44px] min-w-[44px] items-center justify-center text-gray-500 hover:text-red-400 hover:bg-red-900/20"
            title={t('watchlist.remove.label', { symbol })}
        >
            <Trash2 aria-hidden="true" className="w-4 h-4" />
        </Button>
    );
}
