'use client';

import { useState } from 'react';
import { BookOpen } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { ingestLettersCorpusNow } from '@/lib/actions/research-tools.actions';
import { useT } from '@/lib/i18n/client';

// Interactivo (estado + server action en onClick): no puede ser servidor.
export function IngestLettersButton() {
    const t = useT();
    const [state, setState] = useState<'idle' | 'ingesting' | 'queued' | 'error'>('idle');

    const handleIngest = async () => {
        setState('ingesting');
        let success = false;
        try {
            const result = await ingestLettersCorpusNow();
            success = result.success;
        } catch {
            success = false;
        } finally {
            // Sin finally, un rechazo dejaba el botón en «Encolando…».
            setState(success ? 'queued' : 'error');
        }
    };

    const loading = state === 'ingesting';
    return (
        <div className="flex flex-col items-center gap-3">
            <Button
                onClick={handleIngest}
                disabled={loading || state === 'queued'}
                aria-busy={loading}
                className="gap-2"
            >
                <BookOpen aria-hidden="true" className="h-4 w-4" />
                {loading ? t('investors.ingest.queuing') : t('investors.ingest.download')}
            </Button>
            {state === 'queued' ? (
                <p className="text-sm text-teal-300">{t('investors.ingest.queued')}</p>
            ) : null}
            {state === 'error' ? (
                <p className="text-sm text-red-400">{t('investors.ingest.error')}</p>
            ) : null}
        </div>
    );
}
