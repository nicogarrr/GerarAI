'use client';

import { useState } from 'react';
import { Scale } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { useT } from '@/lib/i18n/client';
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
    const t = useT();
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
            setError(exc instanceof Error ? exc.message : t('research.thesisDebate.failedFallback'));
        } finally {
            setRunning(false);
        }
    };

    return (
        <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-3">
                <Button type="button" variant="outline" onClick={run} disabled={running} aria-busy={running}>
                    <Scale aria-hidden="true" className="mr-2 h-4 w-4" />
                    {running ? t('research.thesisDebate.running') : debate ? t('research.thesisDebate.retryDebate') : t('research.thesisDebate.generate')}
                </Button>
                {debate?.degraded ? (
                    <Badge variant="outline" className="border-amber-800/60 text-amber-300">
                        {t('research.thesisDebate.degraded')}
                    </Badge>
                ) : debate ? (
                    <Badge>{t('research.thesisDebate.llmJudge')}</Badge>
                ) : null}
                {debate ? (
                    <span className="text-xs text-gray-500">
                        {t('research.thesisDebate.calls', { count: debate.llm_calls, model: debate.model ?? t('research.thesisDebate.deterministic') })}
                    </span>
                ) : null}
            </div>

            {error ? (
                <div className="rounded-lg border border-red-900/50 bg-red-950/20 p-4" role="alert">
                    <p className="text-sm text-red-200">{t('research.thesisDebate.failed', { error })}</p>
                    <Button type="button" size="sm" variant="outline" onClick={run} className="mt-3">
                        {t('research.thesisDebate.retry')}
                    </Button>
                </div>
            ) : null}

            {debate ? (
                <div className="grid gap-3 md:grid-cols-2">
                    <div className="rounded-lg border border-teal-900/60 bg-teal-950/10 p-4">
                        <h4 className="text-xs font-semibold uppercase tracking-wide text-teal-300">
                            {t('research.thesisDebate.bullTitle')}
                        </h4>
                        <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-gray-300">
                            {debate.bull_case || t('research.thesisDebate.bullEmpty')}
                        </p>
                    </div>
                    <div className="rounded-lg border border-red-900/50 bg-red-950/10 p-4">
                        <h4 className="text-xs font-semibold uppercase tracking-wide text-red-300">
                            {t('research.thesisDebate.bearTitle')}
                        </h4>
                        <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-gray-300">
                            {debate.bear_case || t('research.thesisDebate.bearEmpty')}
                        </p>
                    </div>
                    <div className="rounded-lg border border-gray-800 bg-black/20 p-4 md:col-span-2">
                        <div className="flex flex-wrap items-center gap-2">
                            <Badge
                                variant={debate.verdict === 'bearish' ? 'outline' : 'default'}
                            >
                                {t('research.thesisDebate.verdict', { verdict: debate.verdict })}
                            </Badge>
                            {debate.persisted === false ? (
                                <span className="text-xs text-amber-300">
                                    {t('research.thesisDebate.notPersisted')}
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
                    {t('research.thesisDebate.empty')}
                </p>
            )}
        </div>
    );
}
