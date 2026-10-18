'use client';

import { useState } from 'react';
import { BookOpen } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { ingestLettersCorpusNow } from '@/lib/actions/research-tools.actions';

// Interactivo (estado + server action en onClick): no puede ser servidor.
export function IngestLettersButton() {
    const [state, setState] = useState<'idle' | 'ingesting' | 'queued' | 'error'>('idle');

    const handleIngest = async () => {
        setState('ingesting');
        const result = await ingestLettersCorpusNow();
        setState(result.success ? 'queued' : 'error');
    };

    const loading = state === 'ingesting';
    return (
        <div className="flex flex-col items-center gap-3">
            <Button
                onClick={handleIngest}
                disabled={loading || state === 'queued'}
                aria-busy={loading}
                className="gap-2 bg-teal-600 text-white hover:bg-teal-700"
            >
                <BookOpen aria-hidden="true" className="h-4 w-4" />
                {loading ? 'Encolando descarga...' : 'Descargar cartas gratuitas'}
            </Button>
            {state === 'queued' ? (
                <p className="text-sm text-teal-300">Descarga en curso; recarga la página en unos minutos para ver las cartas.</p>
            ) : null}
            {state === 'error' ? (
                <p className="text-sm text-red-400">No se pudo encolar la descarga. Inténtalo de nuevo.</p>
            ) : null}
        </div>
    );
}
