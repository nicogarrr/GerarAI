'use client';

import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { scrollToIdWhenReady } from '@/lib/utils/scroll-anchor';
import { BrainCircuit, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { getLatestThesisJob, getThesisJobStatus, startThesisJob, type ThesisJobStatus } from '@/lib/actions/thesis-jobs.actions';
import { thesisPhaseLabel, thesisProgressText } from '@/lib/research/thesis-progress';
import { useLocale, useT } from '@/lib/i18n/client';

const THESIS_STATUS_LABELS = {
    insufficient_data: 'research.thesisGenerate.status.insufficientData',
    draft_failed_audit: 'research.thesisGenerate.status.failedAudit',
} as const;

const POLL_MS = 3000;
// 600 polls x 3 s = 30 min de espera continua por job. Sin corte, un job
// atascado dejaba "Generando en segundo plano..." para siempre: pasado el
// maximo el estado es DESCONOCIDO y se dice, no se sigue fingiendo progreso.
const MAX_POLLS = 600;

export default function ThesisGenerateButton({ ticker, label, emptyCopy }: { ticker: string; label?: string; emptyCopy?: string }) {
    const router = useRouter();
    const t = useT();
    const locale = useLocale();
    const searchParams = useSearchParams();
    const [job, setJob] = useState<ThesisJobStatus | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [recovering, setRecovering] = useState(true);
    const [recoveryCycle, setRecoveryCycle] = useState(0);
    const [starting, setStarting] = useState(false);
    const startingRef = useRef(false);
    // Polling agotado por job: derivado del id del job (no un booleano que
    // hay que resetear en un efecto al cambiar de job).
    const [exhaustedJobId, setExhaustedJobId] = useState<number | null>(null);
    const pollCountRef = useRef(0);
    // Reloj local: se fija en cada sondeo y avanza cada 1 s mientras el job
    // corre, para que los segundos no salten de 3 en 3 con el polling.
    const [polledAt, setPolledAt] = useState(0);
    // El resultado solo se anuncia para el trabajo lanzado en esta sesión: el
    // último job guardado puede ser de una versión anterior a la vigente.
    const [startedHere, setStartedHere] = useState(false);

    const active = job !== null && ['queued', 'running', 'retrying', 'dispatch_failed'].includes(job.status);
    const busy = recovering || starting || active;

    useEffect(() => {
        let disposed = false;
        let timer: ReturnType<typeof setTimeout> | undefined;
        const recover = async () => {
            if (startingRef.current) return;
            try {
                const latest = await getLatestThesisJob(ticker);
                if (!disposed && !startingRef.current) {
                    setJob(latest);
                    setRecovering(false);
                    setError(null);
                }
            } catch {
                if (!disposed) {
                    setError(t('research.thesisGenerate.recoverFailed'));
                    timer = setTimeout(recover, POLL_MS);
                }
            }
        };
        // Losing the page unmounts this observer, not the server-side worker.
        void recover();
        const onVisible = () => {
            if (document.visibilityState === 'visible') void recover();
        };
        document.addEventListener('visibilitychange', onVisible);
        window.addEventListener('focus', recover);
        return () => {
            disposed = true;
            clearTimeout(timer);
            document.removeEventListener('visibilitychange', onVisible);
            window.removeEventListener('focus', recover);
        };
    }, [ticker, recoveryCycle]);

    const jobId = job?.id;
    // Job nuevo (o cambio de job): ventana de polling nueva. El agotamiento
    // se deriva comparando el id del job agotado con el actual.
    const pollExhausted = jobId != null && exhaustedJobId === jobId;

    useEffect(() => {
        if (!active || !jobId || pollExhausted) return;
        // Ventana de polling nueva: el contador arranca con el efecto.
        pollCountRef.current = 0;
        let disposed = false;
        let timer: ReturnType<typeof setTimeout> | undefined;
        const tick = async () => {
            try {
                const next = await getThesisJobStatus(jobId);
                if (disposed) return;
                setJob(next);
                setPolledAt(Date.now());
                // Sin router.refresh() automatico: re-renderizaba la ruta
                // entera (14k px) y el lector perdia su sitio ("reinicio").
                // La nueva version se ofrece con una accion explicita.
                if (next.status === 'succeeded' || next.status === 'failed') {
                    return;
                }
            } catch {
                // A failed poll must never cancel or re-enqueue server work.
            }
            if (disposed) return;
            pollCountRef.current += 1;
            if (pollCountRef.current >= MAX_POLLS) {
                // El trabajo del servidor sigue (o no): aqui ya no lo sabemos
                // y no se re-agenda. El copy pasa a "estado desconocido".
                setExhaustedJobId(jobId);
                return;
            }
            timer = setTimeout(tick, POLL_MS);
        };
        void tick();
        return () => {
            disposed = true;
            clearTimeout(timer);
        };
    }, [active, jobId, router, pollExhausted]);

    const running = job?.status === 'running';
    useEffect(() => {
        if (!running) return;
        const clock = setInterval(() => setPolledAt(Date.now()), 1000);
        return () => clearInterval(clock);
    }, [running]);

    const start = async () => {
        if (busy || startingRef.current) return;
        startingRef.current = true;
        setStarting(true);
        setStartedHere(true);
        setError(null);
        try {
            setJob(await startThesisJob(ticker, true, crypto.randomUUID()));
        } catch {
            // Enqueue may have committed before the connection dropped. Read
            // it back rather than suggesting that another click is needed.
            try {
                setJob(await getLatestThesisJob(ticker));
            } catch {
                setRecovering(true);
            }
            setRecovering(true);
            setRecoveryCycle((cycle) => cycle + 1);
            setError(t('research.thesisGenerate.submitUnconfirmed'));
        } finally {
            startingRef.current = false;
            setStarting(false);
        }
    };

    // Generación lanzada aquí y terminada: el copy de vacío («Sin tesis
    // todavía.») y el botón «primera tesis» ya no son ciertos; el estado de
    // éxito (abajo) es la única verdad en la tarjeta. Sin router.refresh():
    // re-renderizaba la ruta entera y el lector perdía su sitio.
    const succeededHere = startedHere && job?.status === 'succeeded';
    const phaseLabel = job?.current_phase ? thesisPhaseLabel(job.current_phase, locale) : null;
    const progressText = thesisProgressText(job, polledAt, locale);

    return (
        <div className="flex flex-col gap-2">
            <div className="flex flex-wrap items-center gap-3">
                {emptyCopy && !succeededHere ? <span className="text-sm text-gray-400">{emptyCopy}</span> : null}
                {succeededHere && emptyCopy ? null : (
                <Button type="button" onClick={start} disabled={busy} aria-busy={busy}>
                    {busy ? (
                        <Loader2 aria-hidden="true" className="mr-2 h-4 w-4 animate-spin" />
                    ) : (
                        <BrainCircuit aria-hidden="true" className="mr-2 h-4 w-4" />
                    )}
                    {recovering ? t('research.thesisGenerate.recovering') : starting ? t('research.thesisGenerate.queuing') : active ? t('research.thesisGenerate.generating') : label ?? t('research.thesisGenerate.generate')}
                </Button>
                )}
                {active ? (
                    <span className="text-sm text-gray-400">
                        {pollExhausted
                            ? t('research.thesisGenerate.unknownState')
                            : progressText ?? (phaseLabel ?? (job?.status === 'dispatch_failed' ? t('research.thesisGenerate.waitingQueue') : job?.status === 'retrying' ? t('research.thesisGenerate.retrying') : job?.status === 'running' ? t('research.thesisGenerate.preparing') : t('research.thesisGenerate.queued')))}
                    </span>
                ) : null}
            </div>
            {startedHere && job?.status === 'succeeded' ? (
                <p className="text-sm text-teal-300">
                    {t('research.thesisGenerate.generated', { version: job.result?.version ?? '?' })}
                    {job.result?.status && Object.hasOwn(THESIS_STATUS_LABELS, job.result.status) ? ` (${t(THESIS_STATUS_LABELS[job.result.status as keyof typeof THESIS_STATUS_LABELS])})` : ''}.
                    {' '}
                    <Link
                        href={`/research/${encodeURIComponent(ticker)}?view=thesis`}
                        onClick={(event) => {
                            const view = searchParams.get('view');
                            if (view === 'thesis' || view === 'tesis') {
                                // Ya estamos en la vista: refresco anclado a la
                                // tesis en vez de navegacion (que no haria nada
                                // al ser la misma URL).
                                event.preventDefault();
                                router.refresh();
                                scrollToIdWhenReady('tesis-actual');
                            }
                        }}
                        className="font-medium underline decoration-teal-700 underline-offset-4 hover:text-teal-200"
                    >
                        {t('research.thesisGenerate.view', { version: job.result?.version ?? '?' })}
                    </Link>
                </p>
            ) : null}
            {job?.status === 'failed' ? (
                <p className="text-sm text-red-300">
                    {t('research.thesisGenerate.failed', { errorClass: job.error_class ? ` (${job.error_class})` : '' })}
                </p>
            ) : null}
            {error ? <p className="text-sm text-red-300">{error}</p> : null}
        </div>
    );
}
