'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Button } from '@/components/ui/button';
import { useT } from '@/lib/i18n/client';

/** A known 429 is rendered on the server, not thrown through Next's redaction. */
export default function ResearchRateLimited({ waitSeconds }: { waitSeconds: number }) {
    const t = useT();
    const router = useRouter();
    const [remaining, setRemaining] = useState(waitSeconds);
    const [attempt, setAttempt] = useState(0);
    useEffect(() => {
        const until = Date.now() + waitSeconds * 1000;
        const timer = setInterval(() => {
            setRemaining(Math.max(0, Math.ceil((until - Date.now()) / 1000)));
        }, 1000);
        return () => clearInterval(timer);
    }, [waitSeconds, attempt]);

    return (
        <main id="content" tabIndex={-1} className="mx-auto w-full max-w-2xl px-4 py-12">
            <section role="alert" className="rounded-lg border border-amber-800/60 bg-amber-950/20 p-6">
                <h1 className="text-lg font-semibold text-gray-100">{t('ui.rateLimit.title')}</h1>
                <p className="mt-2 text-sm leading-6 text-gray-300">{t('ui.rateLimit.message')}</p>
                <Button className="mt-4 min-h-11" variant="outline" disabled={remaining > 0} onClick={() => {
                    setRemaining(waitSeconds);
                    setAttempt((value) => value + 1);
                    router.refresh();
                }}>
                    {remaining > 0 ? t('ui.rateLimit.wait', { seconds: remaining }) : t('ui.rootError.retry')}
                </Button>
            </section>
        </main>
    );
}
