'use client';

import { useState } from 'react';
import { Headphones } from 'lucide-react';

/**
 * Escuchar la tesis: un `<audio controls>` que lee el audio ya generado para
 * (ticker, versión). El audio lo produce el backend; aquí solo se reproduce.
 * Si todavía no existe para esa versión, se dice en una línea.
 */
export default function ThesisAudioPlayer({ ticker, version }: { ticker: string; version: number }) {
    const [failed, setFailed] = useState(false);
    const src = `/api/thesis/${encodeURIComponent(ticker)}/audio?v=${version}`;
    return (
        <div aria-label="Escuchar la tesis" className="flex flex-wrap items-center gap-3" role="group">
            <span className="inline-flex items-center gap-2 text-sm font-medium text-gray-200">
                <Headphones className="h-4 w-4" />Escuchar la tesis
            </span>
            {failed ? (
                <span className="text-xs text-gray-500">El audio de la v{version} aún no está disponible.</span>
            ) : (
                <audio className="h-10 max-w-full" controls key={src} onError={() => setFailed(true)} preload="none" src={src} />
            )}
        </div>
    );
}
