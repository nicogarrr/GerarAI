'use client';

import { useEffect, useRef, useState, useTransition } from 'react';
import { useRouter } from 'next/navigation';

import { Button } from '@/components/ui/button';
import { getLatestSotpAgentsJob, startSotpAgentsJob, type SotpAgentsJob } from '@/lib/actions/sotp.actions';
import { useT } from '@/lib/i18n/client';

const POLL_MS = 4000;
const ACTIVE = new Set(['queued', 'running']);

/** «Generar con expertos»: encola el valorador SOTP y sigue el estado real del trabajo. */
export default function SotpAgentsButton({ ticker, hasProposal }: { ticker: string; hasProposal: boolean }) {
  const t = useT();
  const router = useRouter();
  const [job, setJob] = useState<SotpAgentsJob | null>(null);
  const [error, setError] = useState(false);
  const [pending, startTransition] = useTransition();
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const active = job !== null && ACTIVE.has(job.status);

  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);
  useEffect(() => {
    if (!active) return;
    timer.current = setTimeout(async () => {
      try {
        const next = await getLatestSotpAgentsJob(ticker);
        setJob(next);
        if (next?.status === 'succeeded') router.refresh();
      } catch {
        setError(true);
      }
    }, POLL_MS);
    return () => { if (timer.current) clearTimeout(timer.current); };
  }, [active, job, ticker, router]);

  const start = () => startTransition(async () => {
    setError(false);
    try {
      setJob(await startSotpAgentsJob(ticker));
    } catch {
      setError(true);
    }
  });

  const problems = job?.result?.problems?.filter(Boolean) ?? [];
  return (
    <div className="space-y-1" data-testid="sotp-agents">
      <Button className="w-fit" disabled={pending || active} onClick={start} type="button" variant={hasProposal ? 'outline' : 'default'}>
        {hasProposal ? t('research.sotp.agents.regenerate') : t('research.sotp.agents.generate')}
      </Button>
      <p className="text-xs text-gray-500">{t('research.sotp.agents.hint')}</p>
      {active ? <p className="text-xs text-teal-200" role="status">{t('research.sotp.agents.running')}</p> : null}
      {job?.status === 'succeeded' ? <p className="text-xs text-teal-200" role="status">{t('research.sotp.agents.done')}</p> : null}
      {job?.status === 'failed' ? (
        <p className="text-xs text-amber-200" role="status">
          {t('research.sotp.agents.failed')}{problems.length ? ` ${problems.slice(0, 3).join(' · ')}` : ''}
        </p>
      ) : null}
      {error ? <p className="text-xs text-amber-200" role="alert">{t('research.sotp.agents.error')}</p> : null}
    </div>
  );
}
