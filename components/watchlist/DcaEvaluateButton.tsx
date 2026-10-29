'use client';

import Link from 'next/link';
import { useEffect, useRef, useState } from 'react';
import { formatCountEs } from '@/lib/format';
import { useRouter } from 'next/navigation';
import { RefreshCw } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { getDcaManualJob, startDcaManualJob } from '@/lib/actions/dca-signals.actions';
import { showErrorToast } from '@/lib/toast';

/** Evaluación manual de las señales DCA (el backend la limita a una tanda de diez pendientes cada cinco minutos). */
export default function DcaEvaluateButton() {
    const router = useRouter();
    const [loading, setLoading] = useState(false);

    const alive = useRef(true);
    const [status, setStatus] = useState<string | null>(null);
    useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);

    const handleClick = async () => {
        setLoading(true);
        try {
            const accepted = await startDcaManualJob();
            if (!accepted.success || !accepted.runId) {
                showErrorToast(accepted.message ?? 'No se pudo iniciar la evaluación');
                return;
            }
            setStatus('Tanda aceptada. Puedes salir: continúa en segundo plano.');
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
                setStatus('Sigue en segundo plano. Consulta el resultado en la watchlist.');
                router.refresh();
                return;
            }
            if (res.status === 'interrupted') {
                setStatus('Ejecución interrumpida. Revisa su estado antes de repetir.');
                router.refresh();
                return;
            }
            if (res.success && res.summary) {
                const { evaluated, alerted, skipped, errors = [] } = res.summary;
                const parts = [formatCountEs(evaluated, 'evaluado', 'evaluados'), formatCountEs(alerted.length, 'aviso nuevo', 'avisos nuevos')];
                if (skipped.length > 0) parts.push(`${skipped.length} sin datos suficientes`);
                if (res.summary.pending_remaining) parts.push(`${res.summary.pending_remaining} pendientes de otra tanda`);
                if (errors.length > 0) {
                    parts.push(formatCountEs(errors.length, 'empresa con errores', 'empresas con errores'));
                    toast.warning(`Evaluación DCA parcial: ${parts.join(' · ')}`);
                } else {
                    toast.success(`Señales DCA actualizadas: ${parts.join(' · ')}`);
                }
                setStatus(null);
                router.refresh();
            } else {
                showErrorToast(res.message ?? 'No se pudieron evaluar las señales DCA');
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
            {loading ? 'Evaluando…' : 'Ejecutar pendientes ahora'}
        </Button>
        {status && <p role="status" className="max-w-sm text-xs text-gray-300">{status}</p>}
        <p className="max-w-sm text-xs text-gray-400">Solo faltantes o desactualizadas. Hasta 10 empresas por tanda, 5 min entre tandas. Sin LLM de pago; no activa correos ni realiza compras.</p>
        <Link href="/plan" className="inline-flex min-h-[44px] items-center text-xs text-teal-300">Ver mi plan, reparto DCA y ahorro →</Link>
        </div>
    );
}
