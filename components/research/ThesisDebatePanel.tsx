'use client';

import { useState } from 'react';
import { Scale } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { runThesisDebate, type ThesisDebateResult } from '@/lib/actions/thesis-jobs.actions';
import { isNextRedirectError } from '@/lib/types/errors';

interface ThesisDebatePanelProps {
    ticker: string;
    /** Cuerpo persistido de la seccion thesis_debate (veredicto previo, si existe). */
    initialVerdict?: string | null;
}

/**
 * Debate bull/bear de la tesis (fase "abogado del diablo").
 * Vista bull/bear + badge degraded/determinista cuando el juez LLM no esta
 * disponible. Los fallos muestran el error con reintento, nunca un 500.
 */
export default function ThesisDebatePanel({ ticker, initialVerdict }: ThesisDebatePanelProps) {
    const [debate, setDebate] = useState<ThesisDebateResult | null>(null);
    const [running, setRunning] = useState(false);
    const [error, setError] = useState<string | null>(null);

    const run = async () => {
        setRunning(true);
        setError(null);
        try {
            const outcome = await runThesisDebate(ticker);
            if (outcome.ok) {
                setDebate(outcome.debate);
            } else {
                setError(outcome.error);
            }
        } catch (exc) {
            if (isNextRedirectError(exc)) throw exc;
            setError(exc instanceof Error ? exc.message : 'No se pudo generar el debate');
        } finally {
            setRunning(false);
        }
    };

    return (
        <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-3">
                <Button type="button" variant="outline" onClick={run} disabled={running} aria-busy={running}>
                    <Scale aria-hidden="true" className="mr-2 h-4 w-4" />
                    {running ? 'Debatiendo…' : debate ? 'Reintentar debate' : 'Generar debate bull/bear'}
                </Button>
                {debate?.degraded ? (
                    <Badge variant="outline" className="border-amber-800/60 text-amber-300">
                        degradado · veredicto determinista
                    </Badge>
                ) : debate ? (
                    <Badge>juez LLM</Badge>
                ) : null}
                {debate ? (
                    <span className="text-xs text-gray-500">
                        {debate.llm_calls} llamadas LLM · modelo {debate.model ?? 'determinista'}
                    </span>
                ) : null}
            </div>

            {error ? (
                <div className="rounded-lg border border-red-900/50 bg-red-950/20 p-4" role="alert">
                    <p className="text-sm text-red-200">El debate falló: {error}</p>
                    <Button type="button" size="sm" variant="outline" onClick={run} className="mt-3">
                        Reintentar
                    </Button>
                </div>
            ) : null}

            {debate ? (
                <div className="grid gap-3 md:grid-cols-2">
                    <div className="rounded-lg border border-teal-900/60 bg-teal-950/10 p-4">
                        <h4 className="text-xs font-semibold uppercase tracking-wide text-teal-300">
                            Caso alcista
                        </h4>
                        <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-gray-300">
                            {debate.bull_case || 'Sin caso alcista registrado.'}
                        </p>
                    </div>
                    <div className="rounded-lg border border-red-900/50 bg-red-950/10 p-4">
                        <h4 className="text-xs font-semibold uppercase tracking-wide text-red-300">
                            Caso bajista
                        </h4>
                        <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-gray-300">
                            {debate.bear_case || 'Sin caso bajista registrado.'}
                        </p>
                    </div>
                    <div className="rounded-lg border border-gray-800 bg-black/20 p-4 md:col-span-2">
                        <div className="flex flex-wrap items-center gap-2">
                            <Badge
                                variant={debate.verdict === 'bearish' ? 'outline' : 'default'}
                            >
                                veredicto: {debate.verdict}
                            </Badge>
                            {debate.persisted === false ? (
                                <span className="text-xs text-amber-300">
                                    veredicto no persistido (se muestra igual)
                                </span>
                            ) : null}
                        </div>
                        <p className="mt-2 text-sm leading-6 text-gray-300">
                            {debate.verdict_rationale}
                        </p>
                    </div>
                </div>
            ) : initialVerdict ? (
                <p className="rounded-lg border border-gray-800 bg-black/20 p-4 text-sm leading-6 text-gray-400">
                    {initialVerdict}
                </p>
            ) : (
                <p className="text-sm text-gray-500">
                    Sin debate persistido. Genera el debate para contrastar la tesis con su
                    contraparte bajista antes de aprobarla.
                </p>
            )}
        </div>
    );
}
