'use client';

import { useState } from 'react';
import { formatCountEs } from '@/lib/format';
import { useRouter } from 'next/navigation';
import { RefreshCw } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { evaluateDcaSignalsNow } from '@/lib/actions/dca-signals.actions';
import { showErrorToast } from '@/lib/toast';

/** Evaluación manual de las señales DCA (el backend la limita a una por minuto). */
export default function DcaEvaluateButton() {
    const router = useRouter();
    const [loading, setLoading] = useState(false);

    const handleClick = async () => {
        setLoading(true);
        try {
            const res = await evaluateDcaSignalsNow();
            if (res.success && res.summary) {
                const { evaluated, alerted, skipped } = res.summary;
                const parts = [formatCountEs(evaluated, 'evaluado', 'evaluados'), formatCountEs(alerted.length, 'aviso nuevo', 'avisos nuevos')];
                if (skipped.length > 0) parts.push(`${skipped.length} sin datos suficientes`);
                toast.success(`Señales DCA actualizadas: ${parts.join(' · ')}`);
                router.refresh();
            } else {
                showErrorToast(res.message ?? 'No se pudieron evaluar las señales DCA');
            }
        } catch (error) {
            showErrorToast(error);
        } finally {
            setLoading(false);
        }
    };

    return (
        <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={handleClick}
            disabled={loading}
            aria-busy={loading}
            className="min-h-[36px] border-gray-700 text-xs text-gray-300"
        >
            <RefreshCw aria-hidden="true" className={`mr-1 h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
            {loading ? 'Evaluando…' : 'Evaluar ahora'}
        </Button>
    );
}
