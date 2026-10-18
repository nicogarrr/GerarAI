'use client';

import { useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { BrainCircuit, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { getLatestThesisJob, getThesisJobStatus, startThesisJob, type ThesisJobStatus } from '@/lib/actions/thesis-jobs.actions';

const PHASE_LABELS: Record<string, string> = {
    refresh_sec: 'Actualizando financieros SEC',
    collect_evidence: 'Recopilando evidencia (SEC, noticias, filings)',
    build_fundamental_model: 'Construyendo modelo fundamental',
    run_valuation: 'Ejecutando valoración determinista',
    persist_valuation_snapshot: 'Guardando valoración y snapshot',
    source_audit: 'Auditoría de fuentes y claims',
    compose_thesis: 'Redactando la tesis',
    persist_thesis: 'Persistiendo la versión',
};

const THESIS_STATUS_LABELS: Record<string, string> = {
    insufficient_data: 'datos insuficientes',
    draft_failed_audit: 'no superó la auditoría',
};

const POLL_MS = 3000;
// 600 polls x 3 s = 30 min de espera continua por job. Sin corte, un job
// atascado dejaba "Generando en segundo plano..." para siempre: pasado el
// maximo el estado es DESCONOCIDO y se dice, no se sigue fingiendo progreso.
const MAX_POLLS = 600;

export default function ThesisGenerateButton({ ticker, label = 'Generar tesis' }: { ticker: string; label?: string }) {
    const router = useRouter();
    const [job, setJob] = useState<ThesisJobStatus | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [recovering, setRecovering] = useState(true);
    const [recoveryCycle, setRecoveryCycle] = useState(0);
    const [starting, setStarting] = useState(false);
    const startingRef = useRef(false);
    const [pollExhausted, setPollExhausted] = useState(false);
    const pollCountRef = useRef(0);
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
                    setError('No se pudo recuperar la generación. Reintentando…');
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
    // Job nuevo (o cambio de job): ventana de polling nueva.
    useEffect(() => {
        pollCountRef.current = 0;
        setPollExhausted(false);
    }, [jobId]);

    useEffect(() => {
        if (!active || !jobId || pollExhausted) return;
        let disposed = false;
        let timer: ReturnType<typeof setTimeout> | undefined;
        const tick = async () => {
            try {
                const next = await getThesisJobStatus(jobId);
                if (disposed) return;
                setJob(next);
                if (next.status === 'succeeded' || next.status === 'failed') {
                    router.refresh();
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
                setPollExhausted(true);
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
            setError('No se pudo confirmar el envío. Recuperando el estado del servidor…');
        } finally {
            startingRef.current = false;
            setStarting(false);
        }
    };

    const phaseLabel = job?.current_phase ? PHASE_LABELS[job.current_phase] ?? 'Análisis en curso' : null;
    const doneCount = job?.phases.filter((p) => p.status === 'succeeded').length ?? 0;

    return (
        <div className="flex flex-col gap-2">
            <div className="flex flex-wrap items-center gap-3">
                <Button type="button" onClick={start} disabled={busy} aria-busy={busy}>
                    {busy ? (
                        <Loader2 aria-hidden="true" className="mr-2 h-4 w-4 animate-spin" />
                    ) : (
                        <BrainCircuit aria-hidden="true" className="mr-2 h-4 w-4" />
                    )}
                    {recovering ? 'Recuperando generación…' : starting ? 'Encolando…' : active ? 'Generando en segundo plano…' : label}
                </Button>
                {active ? (
                    <span className="text-sm text-gray-400">
                        {pollExhausted
                            ? 'Estado desconocido: la generación no responde desde hace 30 min. El trabajo del servidor no se cancela; recarga la página para volver a leer su estado.'
                            : `${phaseLabel ?? (job?.status === 'dispatch_failed' ? 'Esperando reconexión de la cola' : job?.status === 'retrying' ? 'Reintentando en el servidor' : 'En cola')}${doneCount > 0 ? ` · ${doneCount} fases completadas` : ''}`}
                    </span>
                ) : null}
            </div>
            {startedHere && job?.status === 'succeeded' ? (
                <p className="text-sm text-teal-300">
                    Tesis v{job.result?.version} generada
                    {job.result?.status && THESIS_STATUS_LABELS[job.result.status] ? ` (${THESIS_STATUS_LABELS[job.result.status]})` : ''}.
                </p>
            ) : null}
            {job?.status === 'failed' ? (
                <p className="text-sm text-red-300">
                    La generación falló{job.error_class ? ` (${job.error_class})` : ''}. Puedes reintentar.
                </p>
            ) : null}
            {error ? <p className="text-sm text-red-300">{error}</p> : null}
        </div>
    );
}
